"""Skeptical second pass: a separate model call tries to knock down each AI finding.

The first pass is rewarded for finding things; this one is told to look for existing protection,
impossible scenarios and generic advice. Findings it marks `not_real` are dropped. It fails open:
if the verifier errors or returns junk, findings are kept (we never lose recall silently).
"""

from typing import Awaitable, Callable

from reviewer import cache
from reviewer.llm import LLMError
from reviewer.models import Finding
from reviewer.prompt import number_lines

PROMPT_VERSION = "2"

SCHEMA = {
    "type": "object",
    "properties": {"verdicts": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "integer"},
        "reason": {"type": "string"},
        "verdict": {"type": "string", "enum": ["real", "not_real"]},
    }, "required": ["id", "reason", "verdict"]}}},
    "required": ["verdicts"],
}

SYSTEM = """\
You are a skeptical senior engineer double-checking an automated code review. For each numbered
finding, decide whether it is a REAL defect in the code shown.

Answer `not_real` if ANY of these hold:
- the code already guards against it (validation, parameterised queries, bounds checks, locks,
  escaping, safe APIs, null checks, early returns, narrow exception handling);
- the scenario cannot actually happen given the code shown;
- it is general advice (add error handling, add validation, use a library) rather than a concrete
  failure;
- the finding misreads the code, or the quoted trigger does not actually cause the claimed failure.

Answer `real` only if you can state concretely how this code fails or is exploited, and the code
does not already prevent it. Give the reason in ONE short sentence (max 25 words), then the verdict.
"""

CallFn = Callable[..., Awaitable[dict]]


def _prompt(path: str, language: str, lines: list[str], start: int, findings: list[Finding]) -> str:
    items = []
    for i, f in enumerate(findings, 1):
        where = f"line {f.line_start}" if f.line_start == f.line_end else f"lines {f.line_start}-{f.line_end}"
        items.append(f"#{i} [{f.severity} {f.category}] {where}: {f.title}\n"
                     f"   claim: {f.description}\n   quoted line: {f.evidence}\n   trigger: {f.trigger}")
    return (f"File: {path}\nLanguage: {language}\n\nCode:\n```\n{number_lines(lines, start)}\n```\n\n"
            "Findings to check:\n" + "\n".join(items))


async def challenge_findings(call: CallFn, model: str, path: str, language: str, lines: list[str], start: int,
                             findings: list[Finding], stats: dict, use_cache: bool = True) -> list[Finding]:
    if not findings:
        return findings
    prompt = _prompt(path, language, lines, start, findings)
    key = cache.make_key("challenge", PROMPT_VERSION, model, SYSTEM, prompt)
    data = cache.get(key) if use_cache else None
    if data is None:
        try:
            data = await call(SYSTEM, prompt, SCHEMA, model=model)
        except LLMError:
            stats["verifier_errors"] = stats.get("verifier_errors", 0) + 1
            return findings  # fail open
        if use_cache:
            cache.put(key, data)
    verdicts: dict[int, dict] = {}
    for v in data.get("verdicts") or []:
        try:
            verdicts[int(v["id"])] = v
        except (KeyError, ValueError, TypeError):
            continue
    kept = []
    for i, f in enumerate(findings, 1):
        v = verdicts.get(i)
        if v and v.get("verdict") == "not_real":
            stats["dropped_challenged"] = stats.get("dropped_challenged", 0) + 1
            stats.setdefault("challenged", []).append({"title": f.title, "line": f.line_start,
                                                       "severity": f.severity, "reason": str(v.get("reason", ""))[:300]})
        else:
            kept.append(f)
    return kept
