"""SQLite cache of LLM results: unchanged code is never re-reviewed (the model is slow)."""

import hashlib
import json
import os
import sqlite3
from pathlib import Path


def _db_path() -> Path:
    base = os.getenv("REVIEW_CACHE_DIR") or str(Path.home() / ".cache" / "code-review-agent")
    Path(base).mkdir(parents=True, exist_ok=True)
    return Path(base) / "cache.db"


def make_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_db_path())
    c.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, ts REAL DEFAULT (strftime('%s','now')))")
    return c


def get(key: str) -> dict | None:
    try:
        with _conn() as c:
            row = c.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None
    except (sqlite3.Error, OSError, json.JSONDecodeError):
        return None


def put(key: str, value: dict) -> None:
    try:
        with _conn() as c:
            c.execute("INSERT OR REPLACE INTO cache (key, value) VALUES (?, ?)", (key, json.dumps(value)))
    except (sqlite3.Error, OSError):
        pass
