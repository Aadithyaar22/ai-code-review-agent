"""
main.py — local REST API + web UI for the code review agent.

  GET  /          web UI
  GET  /health    status + model
  POST /review    { "code": "...", "language": "(optional)", "filename": "(optional)" }
"""

import asyncio
import logging
import os
import shutil
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional

from reviewer.config import load_config
from reviewer.engine import legacy_view, review_source
from reviewer.fixer import apply_fixes
from reviewer.llm import DEFAULT_MODEL, LLMError
from reviewer.models import Finding
from reviewer.repo import GITHUB_RE, clone, review_repo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
log = logging.getLogger(__name__)

MAX_CHARS = 100_000
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = FastAPI(
    title="Code Review Agent",
    description="Evidence-checked AI code review running on a local Ollama model.",
    version="2.0.0",
)
# Local tool: only allow browser pages served from this machine.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_methods=["*"],
    allow_headers=["*"],
)
# Blocks DNS-rebinding: a web page on another domain cannot talk to this local server.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# The local model handles one request at a time; queue the rest instead of thrashing it.
_gpu_lock = asyncio.Lock()


class ReviewRequest(BaseModel):
    code: str = Field(..., description="The source code to review.")
    language: Optional[str] = Field(None, description="Optional language hint (auto-detected if omitted).")
    filename: Optional[str] = Field(None, description="Optional file name; used for language detection.")


@app.get("/")
async def serve_ui():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok", "agent": "code_review_agent", "model": load_config().model or DEFAULT_MODEL,
            "project_dir": BASE_DIR}


@app.post("/review")
async def review(req: ReviewRequest):
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="'code' must not be empty.")
    if len(req.code) > MAX_CHARS:
        raise HTTPException(status_code=413, detail=f"'code' exceeds {MAX_CHARS:,} characters.")
    try:
        async with _gpu_lock:
            report = await review_source(req.filename or "snippet", req.code, req.language, config=load_config())
    except LLMError as exc:
        log.error("LLM failure: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))
    log.info("Reviewed %d chars of %s → score %s/10, %d findings in %ss",
             len(req.code), report.language, report.score, len(report.findings), report.stats.get("seconds"))
    return JSONResponse(content={"session_id": str(uuid.uuid4()), "review": legacy_view(report)})


class FixRequest(BaseModel):
    code: str
    language: Optional[str] = None
    findings: list[Finding] = Field(..., min_length=1, max_length=50)


@app.post("/fix")
async def fix(req: FixRequest):
    """Apply the findings' fixes to `code` and return the corrected file + diff."""
    if len(req.code) > MAX_CHARS:
        raise HTTPException(status_code=413, detail=f"'code' exceeds {MAX_CHARS:,} characters.")
    try:
        async with _gpu_lock:
            result = await apply_fixes(req.code, (req.language or "unknown").lower(), req.findings,
                                       model=load_config().model)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except LLMError as exc:
        log.error("LLM failure: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))
    return result


# ── whole-repository review (long-running → background job + polling) ─────────
_jobs: dict[str, dict] = {}


class RepoRequest(BaseModel):
    target: str = Field(..., description="Local directory path or https://github.com/<owner>/<repo> URL.")
    max_files: int = Field(15, ge=1, le=100, description="How many files get a full AI review (riskiest first).")


async def _run_repo_job(job_id: str, target: str, max_files: int) -> None:
    job, tmp = _jobs[job_id], None
    try:
        root = target
        if GITHUB_RE.match(target):
            job["progress"] = {"phase": "cloning", "done": 0, "total": 0, "current": target}
            tmp, root = await clone(target)
        cfg = load_config()
        report = await review_repo(root, cfg, max_files, lock=_gpu_lock,
                                   on_progress=lambda e: job.__setitem__("progress", e))
        job.update(status="done", result=report.model_dump())
        log.info("Repo review %s → %s/10 (%s), %d files, %ss", target, report.score, report.grade,
                 report.stats["files_reviewed"], report.stats["seconds"])
    except (ValueError, LLMError) as exc:
        job.update(status="error", error=str(exc))
    except Exception as exc:  # noqa: BLE001 — surface anything unexpected to the UI, don't hang the poller
        log.exception("repo job failed")
        job.update(status="error", error=f"Unexpected error: {exc}")
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)


@app.post("/repo-review", status_code=202)
async def start_repo_review(req: RepoRequest):
    target = req.target.strip()
    if not GITHUB_RE.match(target):
        path = Path(target).expanduser()
        if not path.is_dir():
            raise HTTPException(status_code=400, detail="Not a directory on this machine, and not a https://github.com/<owner>/<repo> URL.")
        target = str(path.resolve())
    if any(j["status"] == "running" for j in _jobs.values()):
        raise HTTPException(status_code=409, detail="A repository review is already running.")
    for jid in [k for k, j in _jobs.items() if time.time() - j["created"] > 3600]:
        _jobs.pop(jid)
    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {"status": "running", "created": time.time(), "target": target,
                     "progress": {"phase": "starting", "done": 0, "total": 0, "current": ""}}
    asyncio.create_task(_run_repo_job(job_id, target, req.max_files))
    return {"job_id": job_id}


@app.get("/repo-review/{job_id}")
async def repo_review_status(job_id: str):
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Unknown job.")
    return {k: v for k, v in job.items() if k != "created"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8080")))
