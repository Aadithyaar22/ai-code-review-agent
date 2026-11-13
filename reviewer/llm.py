"""Local LLM backend: Ollama, no API key.

Env vars: OLLAMA_HOST (default http://localhost:11434), OLLAMA_MODEL (default phi4)
"""

import json
import os
import re

import httpx

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "phi4")


class LLMError(RuntimeError):
    pass


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
    return re.sub(r"```$", "", text.strip()).strip()


async def chat_json(system: str, user: str, schema: dict, model: str | None = None,
                    timeout: float = 600.0) -> dict:
    """One chat call whose output is constrained to `schema` (retries once on bad JSON)."""
    payload = {
        "model": model or DEFAULT_MODEL,
        "stream": False,
        "format": schema,  # grammar-constrained structured output
        "keep_alive": "30m",  # keep the model loaded between files
        "options": {"temperature": 0.1, "seed": 7, "num_ctx": 8192},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    last_err = "unknown"
    for _ in range(2):
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
            raise LLMError(f"model '{payload['model']}' not found — run `ollama pull {payload['model']}`")
        if resp.status_code != 200:
            raise LLMError(f"Ollama error {resp.status_code}: {resp.text[:200]}")
        raw = _strip_fences(resp.json().get("message", {}).get("content", ""))
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
            last_err = "JSON is not an object"
        except json.JSONDecodeError as e:
            last_err = f"malformed JSON: {e}"
    raise LLMError(f"model returned {last_err}")
