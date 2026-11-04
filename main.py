"""
main.py — HTTP server that exposes the Code Review Agent via REST.

Endpoints
─────────
POST /review    { "code": "...", "language": "(optional hint)" }
                → structured JSON code review report
GET  /health    → { "status": "ok" }
GET  /          → API usage info
"""

import os
import re
import uuid
import logging

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from agent.llm import MODEL, LLMError, review_json

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Code Review Agent",
    description=(
        "An AI-powered code review agent running on a local Ollama model. "
        "Paste any code snippet and receive a structured JSON report covering "
        "bugs, security issues, improvement suggestions, and a quality score."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
async def serve_ui():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

# ── Schemas ───────────────────────────────────────────────────────────────────
class ReviewRequest(BaseModel):
    code: str = Field(..., description="The source code snippet to review.")
    language: Optional[str] = Field(
        None,
        description="Optional language hint (e.g. 'python', 'javascript'). "
                    "The agent auto-detects if omitted.",
    )

    class Config:
        json_schema_extra = {
            "example": {
                "code": "def divide(a, b):\n    return a / b\n",
                "language": "python",
            }
        }


# ── Helpers ───────────────────────────────────────────────────────────────────
def _build_prompt(req: ReviewRequest) -> str:
    lang_hint = f"Language: {req.language}\n\n" if req.language else ""
    return f"{lang_hint}```\n{req.code}\n```"





@app.get("/health")
async def health():
    return {"status": "ok", "agent": "code_review_agent", "model": MODEL}


@app.post("/review")
async def review(req: ReviewRequest):
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="'code' must not be empty.")
    if len(req.code) > 100_000:
        raise HTTPException(status_code=413, detail="'code' exceeds 100,000 characters.")

    try:
        review_json_ = await review_json(_build_prompt(req))
    except LLMError as exc:
        log.error("LLM failure: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    log.info(
        "Reviewed %d chars of %s  →  score %s/10  |  %d bugs  |  %d security issues",
        len(req.code),
        review_json_.get("language", "unknown"),
        review_json_.get("overall_score", "?"),
        len(review_json_.get("bugs", [])),
        len(review_json_.get("security_issues", [])),
    )
    return JSONResponse(content={"session_id": str(uuid.uuid4()), "review": review_json_})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("PORT", "8080")))
