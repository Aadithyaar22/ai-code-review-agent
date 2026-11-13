"""
main.py — local REST API + web UI for the code review agent.

  GET  /          web UI
  GET  /health    status + model
  POST /review    { "code": "...", "language": "(optional)", "filename": "(optional)" }
"""

import asyncio
import logging
import os
import uuid

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional

from reviewer.config import load_config
from reviewer.engine import legacy_view, review_source
from reviewer.llm import DEFAULT_MODEL, LLMError

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
    return {"status": "ok", "agent": "code_review_agent", "model": load_config().model or DEFAULT_MODEL}


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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8080")))
