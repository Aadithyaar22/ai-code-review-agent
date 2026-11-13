import asyncio

import pytest

from reviewer import fixer
from reviewer.llm import LLMError
from reviewer.models import Finding

CODE = "def total(items):\n    t = 0\n    for i in range(len(items) + 1):\n        t += items[i]\n    return t\n"
FIXED = CODE.replace("len(items) + 1", "len(items)")
FINDING = Finding(file="f.py", line_start=3, line_end=3, severity="critical", category="bug",
                  title="Off by one", evidence="for i in range(len(items) + 1):", fix="range(len(items))")


def run(monkeypatch, replies, code=CODE, findings=(FINDING,), language="python"):
    calls = []

    async def fake(system, user, schema, model=None, **k):
        calls.append(user)
        return {"corrected_code": replies[min(len(calls) - 1, len(replies) - 1)]}
    monkeypatch.setattr(fixer, "chat_json", fake)
    return asyncio.run(fixer.apply_fixes(code, language, list(findings), use_cache=False)), calls


def test_happy_path_returns_code_and_diff(monkeypatch):
    r, _ = run(monkeypatch, [FIXED])
    assert r["corrected_code"] == FIXED and r["valid"] is True and r["unresolved"] == []
    assert "-    for i in range(len(items) + 1):" in r["diff"] and r["changed"] == 1
    assert r["note"].startswith("All fixes applied")


def test_fences_and_missing_trailing_newline_are_normalised(monkeypatch):
    r, _ = run(monkeypatch, ["```python\n" + FIXED.rstrip("\n") + "\n```"])
    assert r["corrected_code"] == FIXED


def test_syntax_error_triggers_one_retry(monkeypatch):
    r, calls = run(monkeypatch, ["def total(items:\n", FIXED])
    assert len(calls) == 2 and "syntax error" in calls[1] and r["valid"] is True


def test_persistent_syntax_error_is_flagged(monkeypatch):
    r, _ = run(monkeypatch, ["def total(items:\n"])
    assert r["valid"] is False and "syntax error" in r["note"]


def test_unresolved_finding_is_reported(monkeypatch):
    r, _ = run(monkeypatch, [CODE.replace("t = 0", "t = 1")])  # touched something else
    assert r["unresolved"] == ["Off by one"] and "may not be fully fixed" in r["note"]


def test_no_change_and_empty_output(monkeypatch):
    assert run(monkeypatch, [CODE])[0]["note"] == "The model made no changes."
    with pytest.raises(LLMError):
        run(monkeypatch, ["   "])


def test_input_validation(monkeypatch):
    with pytest.raises(ValueError):
        asyncio.run(fixer.apply_fixes(CODE, "python", []))
    with pytest.raises(ValueError):
        asyncio.run(fixer.apply_fixes("x\n" * 301, "python", [FINDING]))


def test_non_python_has_no_syntax_check(monkeypatch):
    r, _ = run(monkeypatch, ["function f() {}\n"], code="function f( {}\n", language="javascript")
    assert r["valid"] is None


def test_confine_reverts_unrelated_edits_but_keeps_the_fix():
    original = "import sqlite3\n\ndef a():\n    pass\n\ndef total(items):\n    t = 0\n    for i in range(len(items) + 1):\n        t += items[i]\n    return t\n"
    messy = original.replace("import sqlite3\n\n", "import sqlite3\n\n\n").replace("pass", "return None").replace("len(items) + 1", "len(items)")
    f = Finding(file="f.py", line_start=8, line_end=8, severity="high", category="bug", title="x", evidence="range")
    out, reverted = fixer.confine(original, messy, [f])
    assert out == original.replace("len(items) + 1", "len(items)") and reverted == 2


def test_confine_allows_new_imports_and_nearby_insertions():
    original = "def f(x):\n    return eval(x)\n"
    fixed = "import ast\n\ndef f(x):\n    return ast.literal_eval(x)\n"
    f = Finding(file="f.py", line_start=2, line_end=2, severity="high", category="security", title="x", evidence="eval")
    out, reverted = fixer.confine(original, fixed, [f])
    assert out == fixed and reverted == 0
    guarded = "def f(x):\n    if not x:\n        raise ValueError\n    return eval(x)\n"
    assert fixer.confine(original, guarded, [f]) == (guarded, 0)


def test_apply_fixes_reports_reverted_edits(monkeypatch):
    messy = FIXED.replace("    return t", "    return t  # done")
    r, _ = run(monkeypatch, [messy])
    assert r["corrected_code"] == FIXED and "Reverted 1 unrelated" in r["note"]
