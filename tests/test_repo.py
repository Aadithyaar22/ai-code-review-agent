"""Repo-level logic: secrets, hygiene, scoring, actions, prioritisation, orchestration."""

import asyncio

import pytest

from reviewer import engine, repo
from reviewer.config import Config
from reviewer.models import Finding, Report
from reviewer.repo import (build_actions, compute_scores, grade, hygiene_checks, penalty_score, priority,
                           review_repo, scan_secrets)


def F(sev="high", cat="bug", file="a.py", line=1, rule="", title="t", source="ruff"):
    return Finding(file=file, line_start=line, line_end=line, severity=sev, category=cat, title=title, rule=rule, source=source)


def write(tmp, files):
    for name, text in files.items():
        p = tmp / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def test_secret_scan_finds_real_keys_and_redacts(tmp_path):
    write(tmp_path, {
        "cfg.py": 'AWS = "AKIAABCDEFGHIJKLMNOP"\npassword = "hunter2hunter2"\nok = "password123"  # not matched\n',
        "app.py": 'api_key = "your-api-key-here"\n',          # placeholder -> ignored
        "tests/test_x.py": 'KEY = "AKIAABCDEFGHIJKLMNOP"\n',   # tests ignored
        ".env": "TOKEN=abc\n", ".env.example": "TOKEN=\n",
    })
    found = scan_secrets(str(tmp_path), ["cfg.py", "app.py", "tests/test_x.py", ".env", ".env.example"])
    titles = sorted((f.file, f.title) for f in found)
    assert (".env", "Sensitive file committed to the repo") in titles
    assert ("cfg.py", "AWS access key committed to the repo") in titles
    assert any(f.file == "cfg.py" and f.title.startswith("Hardcoded credential") for f in found)
    assert not any(f.file in ("app.py", "tests/test_x.py", ".env.example") for f in found)
    assert all("ABCDEFGHIJKLMNOP" not in f.evidence for f in found)  # redacted


def test_hygiene_flags_missing_basics(tmp_path):
    write(tmp_path, {"app.py": "x = 1\n" * 5, "requirements.txt": "flask\nrequests\n"})
    checks = {c.id: c for c in hygiene_checks(str(tmp_path), ["app.py", "requirements.txt"], [])}
    for bad in ("readme", "license", "gitignore", "tests", "ci", "dependencies"):
        assert not checks[bad].ok, bad
    assert checks["secrets"].ok


def test_hygiene_passes_for_a_healthy_repo(tmp_path):
    files = {"README.md": "x" * 500, "LICENSE": "MIT", ".gitignore": "*.pyc", "app.py": "x = 1\n",
             "tests/test_app.py": "def test(): pass\n", ".github/workflows/ci.yml": "on: push\n",
             "requirements.txt": "flask==3.0.0\n", "ruff.toml": ""}
    write(tmp_path, files)
    assert all(c.ok for c in hygiene_checks(str(tmp_path), list(files), []))


def test_penalty_score_serious_counts_fully_minor_scales_with_size():
    assert penalty_score([F("critical")], 100) == 6.0
    assert penalty_score([F("low")] * 8, 100) == 8.0                       # small repo: 2.0 penalty
    assert penalty_score([F("low")] * 8, 10_000) == pytest.approx(9.8)     # large repo: diluted
    assert penalty_score([F("critical")] * 5, 100) == 1.0


def test_critical_issue_caps_overall_rating():
    clean = Report(target="a.py", score=10, stats={"lines": 100})
    hyg = [type("C", (), {"weight": 1, "ok": True})()]
    assert compute_scores([clean], [], hyg)[0] == 10.0
    crit = [F("critical", "security")]
    clean2 = Report(target="a.py", score=10, stats={"lines": 100}, findings=crit)
    assert compute_scores([clean2], [], hyg)[0] <= 7.0


def test_ai_only_findings_count_less_than_static_ones():
    assert penalty_score([F("critical", source="llm")], 100) == pytest.approx(7.6)
    assert penalty_score([F("critical", source="ruff")], 100) == 6.0
    assert penalty_score([F("critical", source="secret-scan")], 100) == 6.0


def test_grades():
    assert [grade(x) for x in (9.5, 8.2, 7, 5.5, 3)] == ["A", "B", "C", "D", "F"]


def test_actions_are_prioritised_and_secrets_first():
    r1 = Report(target="a.py", findings=[F("low", file="a.py", line=9), F("high", file="a.py", line=2)])
    r2 = Report(target="b.py", findings=[F("critical", file="b.py", line=5)])
    secret = F("critical", "security", file="c.py", line=1)
    hyg = [repo.Check(id="tests", ok=False, weight=3, message="Automated tests exist", fix="add tests")]
    acts = build_actions([r1, r2], [secret], hyg)
    assert [a.priority for a in acts] == ["P0", "P0", "P1", "P1", "P3"]
    assert acts[0].kind == "secret" and acts[1].location == "b.py:5"
    assert acts[3].kind == "hygiene" or acts[2].kind == "hygiene"


def test_priority_prefers_risky_serious_code_over_tests():
    serious = [F("high")]
    assert priority("auth/login.py", 200, serious) > priority("utils/strings.py", 200, [])
    assert priority("tests/test_auth.py", 200, []) < priority("utils/strings.py", 200, [])


def test_review_repo_end_to_end(tmp_path, monkeypatch):
    write(tmp_path, {
        "app.py": "import os\n\ndef run(s):\n    return eval(s)\n",
        "auth/login.py": 'def login(u, p):\n    return db.execute("SELECT * FROM u WHERE n=" + u)\n\n\n',
        "util.py": "def add(a, b):\n    return a + b\n\n\n",
        "README.md": "hi", ".env": "SECRET=1\n",
    })
    seen = []

    async def fake_chat(system, user, schema, model=None, **k):
        seen.append(user)
        return {"language": "python", "summary": "", "positives": [], "findings": []}
    monkeypatch.setattr(engine, "chat_json", fake_chat)
    events = []
    rep = asyncio.run(review_repo(str(tmp_path), Config(), max_files=2, on_progress=events.append))
    assert rep.stats["files_reviewed"] == 2 and rep.stats["files_total"] == 3
    assert len(rep.stats["files_skipped"]) == 1
    # risky files get reviewed first (eval / sqli found by ruff, "auth" in the path)
    assert {r.target for r in rep.files} == {"app.py", "auth/login.py"}
    assert any(s.title.startswith("Sensitive file") for s in rep.secrets)
    assert rep.score <= 7.0 and rep.grade in "CDF"
    assert rep.actions[0].priority == "P0" and rep.actions[0].kind == "secret"
    assert rep.stats["confidence"] in ("high", "medium", "low") and events[0]["phase"] == "scanning"


def test_review_repo_rejects_empty_dir(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(review_repo(str(tmp_path), Config()))


def test_github_url_validation():
    assert repo.GITHUB_RE.match("https://github.com/Aadithyaar22/ai-code-review-agent")
    assert repo.GITHUB_RE.match("https://github.com/a/b.git")
    assert not repo.GITHUB_RE.match("https://evil.com/a/b")
    assert not repo.GITHUB_RE.match("https://github.com/a/b; rm -rf /")
    assert not repo.GITHUB_RE.match("file:///etc/passwd")
