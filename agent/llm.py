"""
Local LLM backend: talks to an Ollama server, no API key needed.

Env vars
────────
  OLLAMA_HOST   default http://localhost:11434
  OLLAMA_MODEL  default qwen2.5:7b
"""

import json
import os
import re

import httpx

from agent.agent import SYSTEM_INSTRUCTION

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
MODEL = os.getenv("OLLAMA_MODEL", "phi4")


class LLMError(RuntimeError):
    pass


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
    return re.sub(r"```$", "", text.strip()).strip()


async def review_json(prompt: str, timeout: float = 300.0) -> dict:
    """Send a review prompt to Ollama and return the parsed JSON report."""
    payload = {
        "model": MODEL,
        "stream": False,
        "format": "json",  # constrains output to valid JSON
        "options": {"temperature": 0.2},
        "messages": [
            {"role": "system", "content": SYSTEM_INSTRUCTION},
            {"role": "user", "content": prompt},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{OLLAMA_HOST}/api/chat", json=payload)
    except httpx.ConnectError as e:
        raise LLMError(
            f"cannot reach Ollama at {OLLAMA_HOST} — is `ollama serve` running?"
        ) from e
    except httpx.TimeoutException as e:
        raise LLMError("Ollama timed out") from e

    if resp.status_code == 404:
        raise LLMError(f"model '{MODEL}' not found — run `ollama pull {MODEL}`")
    if resp.status_code != 200:
        raise LLMError(f"Ollama error {resp.status_code}: {resp.text[:200]}")

    raw = _strip_fences(resp.json().get("message", {}).get("content", ""))
    if not raw:
        raise LLMError("model returned an empty response")
    try:
        report = json.loads(raw)
    except json.JSONDecodeError as e:
        raise LLMError(f"model returned malformed JSON: {e}") from e
    if not isinstance(report, dict):
        raise LLMError("model returned JSON that is not an object")
    for key in ("bugs", "security_issues", "suggestions", "positives"):
        if not isinstance(report.get(key), list):
            report[key] = []
    return report
