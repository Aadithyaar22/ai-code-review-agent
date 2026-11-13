"""Unit tests for verification, diff parsing, chunking, static analysis, scoring and the engine."""

import asyncio


from reviewer import engine
from reviewer.chunk import chunk_ranges
from reviewer.config import Config
from reviewer.diffparse import parse_diff
from reviewer.models import Finding, compute_score
from reviewer.static import run_static
from reviewer.verify import dedupe, verify_llm_findings

CODE = 'import os\n\ndef run(s):\n    return eval(s)\n\ndef div(a, b):\n    return a / b\n'
LINES = CODE.splitlines()


def raw(**kw):
    base = {"line_start": 4, "line_end": 4, "evidence": "return eval(s)", "title": "eval",
            "description": "d", "severity": "high", "category": "security", "fix": "f", "confidence": 0.9,
            "trigger": "s = \"__import__('os').system('id')\" runs a shell command"}
    return {**base, **kw}


def verify(items, **kw):
    stats = {}
    return verify_llm_findings(items, "f.py", LINES, kw.get("min_conf", 0.5), stats), stats


def test_hallucinated_evidence_is_dropped():
    out, stats = verify([raw(evidence="os.system(cmd)")])
    assert out == [] and stats["dropped_hallucinated"] == 1


def test_empty_evidence_is_dropped():
    out, stats = verify([raw(evidence="")])
    assert out == [] and stats["dropped_no_evidence"] == 1


def test_wrong_line_number_is_snapped_to_evidence():
    out, _ = verify([raw(line_start=1, line_end=1)])
    assert out[0].line_start == 4


def test_line_prefix_copied_by_model_is_tolerated():
    out, _ = verify([raw(evidence="4|     return eval(s)")])
    assert len(out) == 1


def test_literal_backslash_n_in_evidence_is_tolerated():
    out, _ = verify([raw(evidence="def div(a, b):\\n    return a / b", line_start=6, line_end=7, category="bug")])
    assert len(out) == 1 and out[0].line_start == 6


def test_low_confidence_and_noise_dropped():
    out, _ = verify([raw(confidence=0.2), raw(title="Add type hints to run")])
    assert out == []


def test_static_wins_over_overlapping_llm_finding():
    s = [Finding(file="f.py", line_start=4, line_end=4, severity="high", category="security",
                 title="S307", source="ruff")]
    l = [Finding(file="f.py", line_start=4, line_end=4, severity="critical", category="security",
                 title="eval is unsafe", source="llm")]
    merged = dedupe(s, l)
    assert len(merged) == 1 and merged[0].source == "ruff"


def test_parse_diff_collects_new_line_numbers():
    diff = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,4 @@\n x = 1\n-y = 2\n+y = 3\n+z = 4\n w = 5\n"
            "diff --git a/gone.py b/gone.py\n--- a/gone.py\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n")
    assert parse_diff(diff) == {"a.py": {2, 3}}


def test_chunking_covers_file_without_gaps():
    lines = []
    for i in range(30):
        lines += [f"def f{i}():", "    pass", ""]
    rs = chunk_ranges(lines, max_lines=25)
    assert rs[0][0] == 1 and rs[-1][1] == len(lines)
    assert all(a[1] + 1 == b[0] for a, b in zip(rs, rs[1:], strict=False))
    assert all(e - s + 1 <= 25 for s, e in rs)
    assert all(lines[s - 1].startswith("def") for s, _ in rs)  # cuts land on top-level boundaries


def test_small_file_is_one_chunk():
    assert chunk_ranges(["a", "b"], 220) == [(1, 2)]


def test_static_finds_eval_and_syntax_errors():
    rules = {f.rule for f in run_static("f.py", CODE, "python")}
    assert "S307" in rules
    syn = run_static("f.py", "def broken(:\n", "python")
    assert syn[0].title == "Syntax error"
    assert run_static("f.js", "eval(x)", "javascript") == []


def test_score_is_deterministic():
    mk = lambda s: Finding(line_start=1, line_end=1, severity=s, category="bug", title="t")
    assert compute_score([]) == 10
    assert compute_score([mk("critical")]) == 6
    assert compute_score([mk("critical")] * 5) == 1


def test_engine_end_to_end_with_fake_llm(monkeypatch):
    calls = []

    async def fake_chat(system, user, schema, model=None, **k):
        calls.append(user)
        return {"language": "python", "summary": "Unsafe eval.", "positives": [],
                "findings": [raw(), raw(evidence="totally made up line", title="ghost")]}
    monkeypatch.setattr(engine, "chat_json", fake_chat)
    cfg = Config(use_static=False)
    r = asyncio.run(engine.review_source("f.py", CODE, config=cfg))
    assert [f.title for f in r.findings] == ["eval"] and r.stats["dropped_hallucinated"] == 1
    assert "eval" in r.summary and "1 high" in r.summary
    assert "   4|" in calls[0] or "4|" in calls[0]
    # review + skeptical pass; a second run is served entirely from the cache
    assert len(calls) == 2
    asyncio.run(engine.review_source("f.py", CODE, config=cfg))
    assert len(calls) == 2


def test_diff_mode_only_reports_changed_lines(monkeypatch):
    async def fake_chat(*a, **k):
        return {"language": "python", "summary": "s", "positives": [],
                "findings": [raw(), raw(line_start=7, line_end=7, evidence="return a / b", title="div",
                                        category="bug")]}
    monkeypatch.setattr(engine, "chat_json", fake_chat)
    r = asyncio.run(engine.review_source("f.py", CODE, config=Config(use_static=False), changed={7}))
    assert [f.title for f in r.findings] == ["div"]


def test_style_findings_hidden_by_default(monkeypatch):
    async def fake_chat(*a, **k):
        return {"language": "python", "summary": "s", "positives": [],
                "findings": [raw(category="style", title="odd layout")]}
    monkeypatch.setattr(engine, "chat_json", fake_chat)
    r = asyncio.run(engine.review_source("f.py", CODE, config=Config(use_static=False)))
    assert r.findings == []


def test_static_ignores_security_rules_in_tests_and_downgrades_subprocess():
    code = "import subprocess\n\ndef t(cmd):\n    assert 1 == 1\n    subprocess.run(cmd)\n    subprocess.run(['git', 'status'])\n"
    in_tests = {f.rule for f in run_static("tests/test_x.py", code, "python")}
    assert not any(r.startswith("S") for r in in_tests)
    prod = {f.rule: f.severity for f in run_static("app.py", code, "python")}
    assert prod["S101"] == "low" and prod["S603"] == "low" and prod["S607"] == "low"


def test_findings_without_a_concrete_trigger_are_dropped():
    for bad in ("", "n/a", "None", "unknown", "-", "no specific input"):
        out, stats = verify([raw(trigger=bad)])
        assert out == [] and stats["dropped_no_trigger"] == 1, bad
    out, _ = verify([raw(trigger="s = '1+1' evaluates attacker-supplied code")])
    assert len(out) == 1 and "attacker" in out[0].trigger


def _two_pass_fake(verdicts, review_findings=None, fail_verifier=False):
    """A fake chat_json: answers the review call and the verifier call, and records both."""
    calls = []

    async def fake(system, user, schema, model=None, **k):
        calls.append("verifier" if "verdicts" in schema["properties"] else "review")
        if calls[-1] == "verifier":
            if fail_verifier:
                from reviewer.llm import LLMError
                raise LLMError("verifier down")
            return {"verdicts": verdicts}
        return {"language": "python", "summary": "", "positives": [],
                "findings": review_findings if review_findings is not None else [raw()]}
    return fake, calls


def test_verifier_drops_findings_it_marks_not_real(monkeypatch):
    fake, calls = _two_pass_fake([{"id": 1, "reason": "code already guards this", "verdict": "not_real"}])
    monkeypatch.setattr(engine, "chat_json", fake)
    r = asyncio.run(engine.review_source("f.py", CODE, config=Config(use_static=False)))
    assert r.findings == [] and calls == ["review", "verifier"]
    assert r.stats["dropped_challenged"] == 1 and r.stats["challenged"][0]["reason"].startswith("code already")


def test_verifier_keeps_findings_it_confirms(monkeypatch):
    fake, _ = _two_pass_fake([{"id": 1, "reason": "eval of attacker input", "verdict": "real"}])
    monkeypatch.setattr(engine, "chat_json", fake)
    r = asyncio.run(engine.review_source("f.py", CODE, config=Config(use_static=False)))
    assert [f.title for f in r.findings] == ["eval"]


def test_verifier_fails_open_on_error_or_junk(monkeypatch):
    for kwargs in ({"fail_verifier": True, "verdicts": []}, {"verdicts": [{"nonsense": 1}]}, {"verdicts": []}):
        fake, _ = _two_pass_fake(**kwargs)
        monkeypatch.setattr(engine, "chat_json", fake)
        r = asyncio.run(engine.review_source("f.py", CODE + "# x\n" * len(kwargs), config=Config(use_static=False, use_cache=False)))
        assert len(r.findings) == 1, kwargs  # never lose a finding because the verifier misbehaved


def test_verifier_can_be_disabled_and_skipped_when_nothing_to_check(monkeypatch):
    fake, calls = _two_pass_fake([{"id": 1, "reason": "", "verdict": "not_real"}])
    monkeypatch.setattr(engine, "chat_json", fake)
    r = asyncio.run(engine.review_source("f.py", CODE, config=Config(use_static=False, use_verifier=False)))
    assert len(r.findings) == 1 and calls == ["review"]
    fake2, calls2 = _two_pass_fake([], review_findings=[])
    monkeypatch.setattr(engine, "chat_json", fake2)
    asyncio.run(engine.review_source("g.py", CODE + "# y\n", config=Config(use_static=False)))
    assert calls2 == ["review"]  # no findings -> no second call


def test_verifier_only_sees_findings_on_changed_lines(monkeypatch):
    seen = []

    async def fake(system, user, schema, model=None, **k):
        if "verdicts" in schema["properties"]:
            seen.append(user)
            return {"verdicts": []}
        return {"language": "python", "summary": "", "positives": [], "findings": [
            raw(), raw(line_start=7, line_end=7, evidence="return a / b", title="div", category="bug")]}
    monkeypatch.setattr(engine, "chat_json", fake)
    asyncio.run(engine.review_source("f.py", CODE, config=Config(use_static=False), changed={7}))
    assert len(seen) == 1 and "div" in seen[0] and "#2" not in seen[0]
