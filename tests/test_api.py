"""API tests: the LLM call is mocked, so no Ollama needed."""

from fastapi.testclient import TestClient

import main
from reviewer.llm import LLMError
from reviewer.models import Finding, Report

client = TestClient(main.app)


def _report():
    f = Finding(file="snippet", line_start=2, line_end=2, severity="critical", category="bug",
                title="Division by zero", description="b can be 0", fix="check b", evidence="return a / b")
    return Report(target="snippet", language="python", score=6, summary="bad", findings=[f])


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_review_ok_and_legacy_shape(monkeypatch):
    async def fake(*a, **k):
        return _report()
    monkeypatch.setattr(main, "review_source", fake)
    r = client.post("/review", json={"code": "print(1)"})
    assert r.status_code == 200
    rev = r.json()["review"]
    assert rev["overall_score"] == 6
    assert rev["bugs"][0]["line"] == "2" and rev["findings"][0]["severity"] == "critical"


def test_empty_code_rejected():
    assert client.post("/review", json={"code": "   "}).status_code == 400


def test_oversized_code_rejected():
    assert client.post("/review", json={"code": "x" * 100_001}).status_code == 413


def test_llm_failure_is_502(monkeypatch):
    async def boom(*a, **k):
        raise LLMError("cannot reach Ollama")
    monkeypatch.setattr(main, "review_source", boom)
    r = client.post("/review", json={"code": "print(1)"})
    assert r.status_code == 502 and "Ollama" in r.json()["detail"]


def test_cors_rejects_foreign_origin():
    r = client.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers


# ── repository review jobs ───────────────────────────────────────────────────
def test_repo_review_rejects_bad_targets():
    assert client.post("/repo-review", json={"target": "/definitely/not/a/dir"}).status_code == 400
    assert client.post("/repo-review", json={"target": "https://evil.com/a/b"}).status_code == 400
    assert client.post("/repo-review", json={"target": ".", "max_files": 0}).status_code == 422


def test_repo_review_job_lifecycle(tmp_path, monkeypatch):
    from reviewer.repo import RepoReport

    async def fake(root, cfg, max_files, **kw):
        kw["on_progress"]({"phase": "reviewing", "done": 1, "total": 2, "current": "a.py"})
        return RepoReport(root=root, score=7.5, grade="C", breakdown={"code_quality": 8}, stats={
            "files_reviewed": 1, "files_total": 1, "coverage": 1.0, "seconds": 0.1})
    monkeypatch.setattr(main, "review_repo", fake)
    main._jobs.clear()
    r = client.post("/repo-review", json={"target": str(tmp_path)})
    assert r.status_code == 202
    jid = r.json()["job_id"]
    body = client.get(f"/repo-review/{jid}").json()
    assert body["status"] in ("running", "done")
    import time
    for _ in range(50):
        body = client.get(f"/repo-review/{jid}").json()
        if body["status"] != "running":
            break
        time.sleep(0.05)
    assert body["status"] == "done" and body["result"]["score"] == 7.5
    assert client.get("/repo-review/nope").status_code == 404


def test_host_header_rebinding_blocked():
    r = client.get("/health", headers={"Host": "evil.example.com"})
    assert r.status_code == 400


def test_fix_endpoint(monkeypatch):
    async def fake(code, language, findings, model=None, **k):
        return {"corrected_code": "x = 2\n", "diff": "", "changed": 1, "valid": True, "unresolved": [], "note": "ok"}
    monkeypatch.setattr(main, "apply_fixes", fake)
    f = {"line_start": 1, "line_end": 1, "severity": "high", "category": "bug", "title": "t", "fix": "x = 2"}
    r = client.post("/fix", json={"code": "x = 1\n", "language": "python", "findings": [f]})
    assert r.status_code == 200 and r.json()["corrected_code"] == "x = 2\n"
    assert client.post("/fix", json={"code": "x", "findings": []}).status_code == 422
