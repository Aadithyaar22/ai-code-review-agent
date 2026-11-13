"""Prompt + output schema for the LLM review pass."""

from reviewer.models import CATEGORIES, SEVERITIES

# Property order matters: with constrained decoding the model fills fields in this
# order, so `evidence` (a verbatim quote) comes before the judgement fields.
LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "language": {"type": "string"},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "evidence": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {"type": "string", "enum": SEVERITIES},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "fix": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["line_start", "line_end", "evidence", "title",
                             "description", "severity", "category", "fix", "confidence"],
            },
        },
        "positives": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["language", "summary", "findings", "positives"],
}

SYSTEM_PROMPT = """\
You are a senior engineer doing a strict, evidence-based code review.
The code is shown with line numbers in the form `  12| code`.

Report ONLY real problems you can point to in the code shown:
- bug: logic errors, crashes, wrong results, unhandled edge cases, resource leaks, races
- security: injection, eval/unsafe deserialization, hardcoded secrets, path traversal,
  missing validation/authorization, weak crypto
- performance: clear algorithmic or I/O inefficiency (N+1 queries, quadratic loops)
- maintainability / testing: only when it causes a concrete risk

Hard rules:
1. `evidence` MUST be copied VERBATIM from ONE line of the code shown (no line-number
   prefix). If you cannot quote it, do not report it.
2. line_start / line_end use the numbers from the prefixes.
3. NEVER report: missing docstrings, type hints, comments, naming taste, formatting,
   "add logging", or hypothetical issues in code that is not shown.
4. Do not repeat anything listed under ALREADY DETECTED.
5. severity: critical = exploitable, or certain crash/data loss in normal use;
   high = likely bug or vulnerability; medium = fails on edge cases / real risk; low = minor.
6. confidence is 0-1: how sure you are the issue is real. Use < 0.5 if speculative.
7. `fix` must be concrete; show corrected code when it is short.
8. Clean code is a valid answer: return "findings": [].
9. `summary` is one sentence. `positives` has at most 3 specific items.

Example finding:
{"line_start": 3, "line_end": 3, "evidence": "q = \\"SELECT * FROM t WHERE id=\\" + uid",
 "title": "SQL injection", "description": "uid is concatenated into the query, so a crafted id changes the SQL.",
 "severity": "critical", "category": "security",
 "fix": "db.execute(\\"SELECT * FROM t WHERE id = ?\\", (uid,))", "confidence": 0.97}
"""


def number_lines(lines: list[str], start: int) -> str:
    width = len(str(start + len(lines)))
    return "\n".join(f"{start + i:>{width}}| {l}" for i, l in enumerate(lines))


def ranges(nums: set[int]) -> str:
    out, run = [], []
    for n in sorted(nums):
        if run and n == run[-1] + 1:
            run.append(n)
        else:
            if run:
                out.append(run)
            run = [n]
    if run:
        out.append(run)
    return ", ".join(f"{r[0]}-{r[-1]}" if len(r) > 1 else str(r[0]) for r in out)


def build_user_prompt(path: str, language: str, lines: list[str], start: int, total: int,
                      context: str = "", changed: set[int] | None = None,
                      known: list[str] | None = None) -> str:
    parts = [f"File: {path}", f"Language: {language}"]
    if context:
        parts.append(f"Project context: {context}")
    if changed is not None:
        parts.append("This is a code change. ONLY report issues on these changed lines "
                     f"(use the rest as context): {ranges(changed)}")
    if known:
        parts.append("ALREADY DETECTED by static analysis (do not repeat):\n" +
                     "\n".join(f"- {k}" for k in known))
    end = start + len(lines) - 1
    parts.append(f"Code (lines {start}-{end} of {total}):\n```\n{number_lines(lines, start)}\n```")
    return "\n\n".join(parts)
