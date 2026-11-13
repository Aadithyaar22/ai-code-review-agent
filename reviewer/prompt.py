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
                    "trigger": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "severity": {"type": "string", "enum": SEVERITIES},
                    "category": {"type": "string", "enum": CATEGORIES},
                    "fix": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["line_start", "line_end", "evidence", "trigger", "title",
                             "description", "severity", "category", "fix", "confidence"],
            },
        },
        "positives": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["language", "summary", "findings", "positives"],
}

SYSTEM_PROMPT = """\
You are a senior engineer doing a strict, evidence-based code review. Precision matters more than
volume: a wrong finding wastes the reader's time and destroys trust. Reporting nothing is fine.
The code is shown with line numbers in the form `  12| code`.

Report ONLY real problems you can point to in the code shown:
- bug: logic errors, crashes, wrong results, resource leaks, races, off-by-one, missing await
- security: injection, eval/unsafe deserialization, hardcoded secrets, path traversal, XSS,
  missing authorization, weak crypto / predictable tokens
- performance: clear algorithmic or I/O inefficiency (N+1 queries, quadratic loops)

Before reporting anything, FIRST look for protection already in the code (validation, parameterised
queries, bounds checks, locks, escaping, safe APIs, null checks, early returns). Report only if that
protection is absent or wrong.

Hard rules:
1. `evidence` MUST be copied VERBATIM from ONE line of the code shown (no line-number prefix).
2. `trigger` MUST be a concrete input or scenario in which this code visibly fails or is exploited,
   e.g. `values = []` or `name = "x' OR '1'='1"`. If you cannot write one, do NOT report the issue.
3. line_start / line_end use the numbers from the prefixes.
4. NEVER report: missing docstrings/type hints/comments/logging, naming, formatting; "unhandled
   exception" or "missing validation" remarks that are just defensive-programming advice (callers can
   reasonably handle FileNotFoundError, JSON errors, bad types); inputs of the wrong type; hypothetical
   future changes; anything in code that is not shown.
5. Do not repeat anything listed under ALREADY DETECTED.
6. severity: critical = exploitable, or certain crash/data loss in normal use; high = likely bug or
   vulnerability; medium = real failure on an edge case; low = minor. Never use critical/high for
   something the code already guards against.
7. confidence is 0-1; use < 0.5 if speculative (speculative findings should simply be omitted).
8. `fix` must be concrete; show corrected code when it is short.
9. Clean code is a valid answer: return "findings": []. `summary` is one sentence; `positives` at most 3.

These are SAFE and must not be reported: parameterised queries / bound placeholders; subprocess with an
argument list and no shell; assigning to textContent; ast.literal_eval; hmac.compare_digest or the
secrets module; bounded copies (snprintf / strncpy with sizeof); updates made while holding a lock;
the `x=None` then `if x is None: x = []` default idiom; a path checked with realpath plus a prefix
test; secrets read from environment variables.

Example finding:
{"line_start": 3, "line_end": 3, "evidence": "q = \\"SELECT * FROM t WHERE id=\\" + uid",
 "trigger": "uid = \\"1 OR 1=1\\" returns every row",
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
