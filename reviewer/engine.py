"""Review pipeline: static checks -> chunked LLM review -> verify -> dedupe -> score."""

import time
from pathlib import PurePath
from typing import Callable

from reviewer import cache
from reviewer.chunk import chunk_ranges
from reviewer.config import Config
from reviewer.llm import DEFAULT_MODEL, chat_json
from reviewer.models import SEVERITY_RANK, Finding, Report, compute_score
from reviewer.prompt import LLM_SCHEMA, SYSTEM_PROMPT, build_user_prompt
from reviewer.static import run_static
from reviewer.verify import dedupe, sort_findings, verify_llm_findings

PROMPT_VERSION = "2"

EXT_LANG = {
    ".py": "python", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript", ".java": "java", ".go": "go", ".rs": "rust",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp", ".cs": "csharp",
    ".rb": "ruby", ".php": "php", ".swift": "swift", ".kt": "kotlin", ".sh": "bash",
    ".sql": "sql", ".scala": "scala", ".lua": "lua", ".dart": "dart",
}
ALIASES = {"js": "javascript", "py": "python", "ts": "typescript", "rs": "rust", "sh": "bash",
           "c++": "cpp", "c#": "csharp", "golang": "go", "rb": "ruby"}


def detect_language(path: str, hint: str | None = None) -> str:
    if hint and hint.strip():
        h = hint.strip().lower()
        return ALIASES.get(h, h)
    return EXT_LANG.get(PurePath(path).suffix.lower(), "unknown")


def is_reviewable(path: str) -> bool:
    return PurePath(path).suffix.lower() in EXT_LANG


async def review_source(path: str, code: str, language: str | None = None, *, config: Config | None = None,
                        changed: set[int] | None = None,
                        on_progress: Callable[[str], None] | None = None) -> Report:
    """Review one file's contents. `changed` (new-file line numbers) restricts findings to a diff."""
    cfg = config or Config()
    model = cfg.model or DEFAULT_MODEL
    lang = detect_language(path, language)
    lines = code.splitlines()
    t0 = time.time()
    stats: dict = {"chunks": 0, "cached_chunks": 0, "model": model, "lines": len(lines)}
    say = on_progress or (lambda _m: None)

    static = run_static(path, code, lang) if cfg.use_static else []
    if changed is not None:
        static = [f for f in static if any(f.line_start <= c <= f.line_end for c in changed)]
    known = [f"line {f.line_start}: {f.title}" for f in static]

    raw: list[dict] = []
    positives: list[str] = []
    for start, end in chunk_ranges(lines, cfg.max_chunk_lines):
        if changed is not None and not any(start <= c <= end for c in changed):
            continue
        chunk_changed = None if changed is None else {c for c in changed if start <= c <= end}
        chunk_known = [k for k, f in zip(known, static) if start <= f.line_start <= end]
        user = build_user_prompt(path, lang, lines[start - 1:end], start, len(lines), cfg.context,
                                 chunk_changed, chunk_known)
        key = cache.make_key(PROMPT_VERSION, model, SYSTEM_PROMPT, user)
        data = cache.get(key) if cfg.use_cache else None
        if data is None:
            say(f"  reviewing {path} lines {start}-{end} …")
            data = await chat_json(SYSTEM_PROMPT, user, LLM_SCHEMA, model=model)
            if cfg.use_cache:
                cache.put(key, data)
        else:
            stats["cached_chunks"] += 1
        stats["chunks"] += 1
        raw.extend(data.get("findings") or [])
        positives.extend(str(p) for p in (data.get("positives") or []))
        if lang == "unknown" and data.get("language"):
            lang = str(data["language"]).lower()

    stats["llm_findings"] = len(raw)
    llm_findings = verify_llm_findings(raw, path, lines, cfg.min_confidence, stats)
    if changed is not None:
        llm_findings = [f for f in llm_findings if any(f.line_start <= c <= f.line_end for c in changed)]

    findings = dedupe(static, llm_findings)
    floor = SEVERITY_RANK.get(cfg.min_severity, 3)
    findings = [f for f in findings if f.category not in cfg.ignore_categories
                and SEVERITY_RANK.get(f.severity, 9) <= floor]
    findings = sort_findings(findings)

    summary = summarize(findings)

    stats["seconds"] = round(time.time() - t0, 1)
    return Report(target=path, language=lang, score=compute_score(findings), summary=summary,
                  findings=findings, positives=positives[:3], stats=stats)


def summarize(findings: list[Finding]) -> str:
    """Deterministic summary, so it can never contradict the (verified) findings."""
    if not findings:
        return "No issues found."
    counts = ", ".join(f"{sum(f.severity == s for f in findings)} {s}"
                       for s in SEVERITY_RANK if any(f.severity == s for f in findings))
    top = findings[0]
    return f"{len(findings)} issue(s) ({counts}). Most serious: {top.title} (line {top.line_start})."


def legacy_view(r: Report) -> dict:
    """The original API/UI shape (bugs / security_issues / suggestions) plus the new fields."""
    def line(f: Finding) -> str:
        return str(f.line_start) if f.line_start == f.line_end else f"{f.line_start}-{f.line_end}"

    def issue(f: Finding) -> dict:
        return {"line": line(f), "severity": f.severity, "description": f"{f.title}. {f.description}".strip(),
                "fix": f.fix}

    return {
        "language": r.language, "overall_score": r.score, "summary": r.summary,
        "bugs": [issue(f) for f in r.findings if f.category == "bug"],
        "security_issues": [issue(f) for f in r.findings if f.category == "security"],
        "suggestions": [{"category": f.category, "description": f"(line {line(f)}) {f.title}. {f.description}",
                         "example": f.fix or None}
                        for f in r.findings if f.category not in ("bug", "security")],
        "positives": r.positives,
        "findings": [f.model_dump() for f in r.findings],
        "stats": r.stats,
    }
