"""Project settings from `.reviewrc.json` (optional), overridable on the CLI."""

import json
from dataclasses import dataclass, field, fields
from pathlib import Path


@dataclass
class Config:
    model: str | None = None
    ignore_categories: list[str] = field(default_factory=lambda: ["style"])
    min_severity: str = "low"
    min_confidence: float = 0.5
    context: str = ""  # free text appended to every prompt, e.g. "Django 5 app; we use pytest"
    max_chunk_lines: int = 220
    ignore_paths: list[str] = field(default_factory=lambda: [
        "*.lock", "*.min.js", "*.min.css", "package-lock.json", "*.svg", "node_modules/*", ".venv/*",
        "venv/*", "dist/*", "build/*", "*.map"])
    use_static: bool = True
    use_cache: bool = True


def load_config(directory: str = ".") -> Config:
    cfg = Config()
    p = Path(directory) / ".reviewrc.json"
    if p.is_file():
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError as e:
            raise SystemExit(f"error: {p} is not valid JSON: {e}")
        known = {f.name for f in fields(Config)}
        for k, v in data.items():
            if k not in known:
                raise SystemExit(f"error: unknown option '{k}' in {p}")
            setattr(cfg, k, v)
    return cfg
