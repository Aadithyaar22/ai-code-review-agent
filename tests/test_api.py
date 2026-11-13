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
