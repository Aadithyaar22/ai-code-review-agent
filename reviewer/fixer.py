"""Apply verified review findings to the code and return a corrected version (+ diff).

The model is told to make the smallest possible edits; the result is then checked:
Python must still parse, and each finding's quoted line must actually be gone.
"""

import ast
import difflib
import re

from reviewer import cache
from reviewer.llm import DEFAULT_MODEL, LLMError, chat_json
from reviewer.models import Finding

MAX_LINES = 300
FIX_SCHEMA = {"type": "object", "properties": {"corrected_code": {"type": "string"}}, "required": ["corrected_code"]}
SYSTEM = """\
You apply code-review fixes to a source file.

Rules:
1. Apply ONLY the listed fixes, using the smallest possible edit for each.
2. Do NOT rename, reformat, reorder, re-indent, add comments or change anything else.
3. Keep every untouched line exactly as it is.
4. Return the COMPLETE corrected file in `corrected_code` — no markdown fences, no explanations, no "..." placeholders.
"""


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _strip_fences(s: str) -> str:
    s = re.sub(r"^```[a-zA-Z]*\n", "", s.strip("\n"))
    return re.sub(r"\n```\s*$", "", s)


def _parses(code: str, language: str) -> bool | None:
    if language != "python":
        return None  # can't check
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


_IMPORT = re.compile(r"^\s*(import |from \S+ import |#include|using |use |require|const .*= require\()")


def confine(original: str, corrected: str, findings: list[Finding]) -> tuple[str, int]:
    """Revert edits that are not near a finding (models like to "tidy" other lines).

    Added import lines are always allowed since a fix may need them. Returns (code, reverted_hunks).
    """
    a, b = original.splitlines(True), corrected.splitlines(True)
    ranges = [(f.line_start - 2, f.line_end + 1) for f in findings]  # 1-indexed, with a little slack
    out, reverted = [], 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            out += a[i1:i2]
            continue
        lo, hi = i1 + 1, max(i2, i1 + 1)  # original line span touched (insertions touch the gap at i1)
        near = any(lo <= r_hi and hi >= r_lo for r_lo, r_hi in ranges)
        only_imports = tag == "insert" and all(_IMPORT.match(l) for l in b[j1:j2])
        if near or only_imports:
            out += b[j1:j2]
        else:
            out += a[i1:i2]
            reverted += 1
    return "".join(out), reverted


def _prompt(code: str, language: str, findings: list[Finding], extra: str = "") -> str:
    items = []
    for f in findings:
        where = f"line {f.line_start}" if f.line_start == f.line_end else f"lines {f.line_start}-{f.line_end}"
        items.append(f"- {where} [{f.severity} {f.category}] {f.title}\n    quoted line: {f.evidence}\n    fix: {f.fix or f.description}")
    return (f"Language: {language}\n\nFixes to apply:\n" + "\n".join(items) + extra +
            f"\n\nOriginal file:\n```\n{code}\n```")


async def apply_fixes(code: str, language: str, findings: list[Finding], model: str | None = None,
                      use_cache: bool = True) -> dict:
    """Return {corrected_code, diff, changed, valid, unresolved, note}. Raises ValueError / LLMError."""
    findings = [f for f in findings if f.fix or f.description]
    if not findings:
        raise ValueError("No findings with fixes to apply.")
    if len(code.splitlines()) > MAX_LINES:
        raise ValueError(f"File is longer than {MAX_LINES} lines; apply fixes per finding instead.")
    model = model or DEFAULT_MODEL
    key = cache.make_key("fix2", model, language, code, *[f"{f.line_start}|{f.title}|{f.fix}" for f in findings])
    if use_cache and (hit := cache.get(key)):
        return hit

    original_ok = _parses(code, language)
    corrected, extra = "", ""
    for attempt in range(2):
        data = await chat_json(SYSTEM, _prompt(code, language, findings, extra), FIX_SCHEMA, model=model)
        corrected = _strip_fences(str(data.get("corrected_code", "")))
        if code.endswith("\n") and not corrected.endswith("\n"):
            corrected += "\n"
        if not corrected.strip():
            raise LLMError("model returned empty corrected code")
        if _parses(corrected, language) is not False or original_ok is False:
            break
        extra = "\n\nYour previous attempt had a syntax error. Fix only the listed problems and keep the file valid."

    reverted = 0
    if corrected != code:
        confined, reverted = confine(code, corrected, findings)
        # keep the tidy-up reverted only if that doesn't break the file
        if reverted and _parses(confined, language) is not False:
            corrected = confined
        else:
            reverted = 0
    valid = _parses(corrected, language)
    body = _norm(corrected)
    unresolved = [f.title for f in findings if f.evidence and _norm(f.evidence) in body]
    diff = "".join(difflib.unified_diff(code.splitlines(True), corrected.splitlines(True),
                                        "original", "corrected", n=2))
    changed = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    if corrected == code:
        note = "The model made no changes."
    elif valid is False:
        note = "The corrected code has a syntax error — review it carefully before using it."
    elif unresolved:
        note = f"{len(unresolved)} finding(s) may not be fully fixed: " + "; ".join(unresolved[:3])
    else:
        note = "All fixes applied." + (" Syntax check passed." if valid else "")
    if reverted and corrected != code:
        note += f" Reverted {reverted} unrelated edit(s) the model made."
    result = {"corrected_code": corrected, "diff": diff, "changed": changed, "valid": valid,
              "unresolved": unresolved, "note": note}
    if use_cache and corrected != code and valid is not False:
        cache.put(key, result)
    return result
