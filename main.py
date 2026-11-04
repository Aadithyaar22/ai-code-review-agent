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
import json
import logging

from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from agent.agent import root_agent

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

# ── ADK globals ───────────────────────────────────────────────────────────────
APP_NAME = "code_review_agent_app"
session_service: InMemorySessionService | None = None
runner: Runner | None = None




@asynccontextmanager
async def lifespan(app: FastAPI):
    global session_service, runner
    log.info("Initialising ADK runner …")
    session_service = InMemorySessionService()
    try:
        runner = Runner(
            agent=root_agent,
            app_name=APP_NAME,
            session_service=session_service,
        )
        log.info("ADK runner ready → model: %s", root_agent.model)
    except Exception as e:
        log.error("Runner failed to initialize: %s", str(e))
        runner = None
    
    yield
    log.info("Server shutting down.")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Code Review Agent",
    description=(
        "An AI-powered code review agent built with Google ADK and Gemini. "
        "Paste any code snippet and receive a structured JSON report covering "
        "bugs, security issues, improvement suggestions, and a quality score."
    ),
    version="1.0.0",
    lifespan=lifespan,
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
def _strip_fences(text: str) -> str:
    """Remove markdown code fences the model may accidentally emit."""
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    return text.strip()


def _build_prompt(req: ReviewRequest) -> str:
    lang_hint = f"Language: {req.language}\n\n" if req.language else ""
    return f"{lang_hint}```\n{req.code}\n```"





@app.get("/health")
async def health():
    return {"status": "ok", "agent": root_agent.name, "model": root_agent.model}


@app.post("/review")
async def review(req: ReviewRequest):

    if runner is None:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    if not req.code.strip():
        raise HTTPException(status_code=400, detail="'code' must not be empty.")

    session_id = str(uuid.uuid4())
    user_id = "api_user"

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )

    prompt = _build_prompt(req)
    user_message = genai_types.Content(
        role="user",
        parts=[genai_types.Part(text=prompt)],
    )

    raw_parts: list[str] = []

    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=user_message,
    ):
        if event.is_final_response():
            for part in event.content.parts:
                if part.text:
                    raw_parts.append(part.text)

    raw_text = _strip_fences("".join(raw_parts))

    if not raw_text:
        raise HTTPException(status_code=500, detail="Agent returned an empty response.")

    try:
        review_json = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        log.error("Failed to parse agent JSON: %s\nRaw: %s", exc, raw_text[:500])
        raise HTTPException(
            status_code=500,
            detail="Agent returned malformed JSON. Try again.",
        )

    log.info(
        "Reviewed %d chars of %s  →  score %s/10  |  %d bugs  |  %d security issues",
        len(req.code),
        review_json.get("language", "unknown"),
        review_json.get("overall_score", "?"),
        len(review_json.get("bugs", [])),
        len(review_json.get("security_issues", [])),
    )

    return JSONResponse(content={"session_id": session_id, "review": review_json})

