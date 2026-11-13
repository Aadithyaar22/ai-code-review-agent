"""Fast unit tests: the LLM call is mocked, so no Ollama needed."""

import pytest
from fastapi.testclient import TestClient

import main
from agent import llm
from agent.llm import LLMError

client = TestClient(main.app)

REPORT = {
    "language": "python", "overall_score": 3, "summary": "bad",
    "bugs": [{"line": "2", "severity": "critical", "description": "x", "fix": "y"}],
    "security_issues": [], "suggestions": [], "positives": [],
}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_review_ok(monkeypatch):
    async def fake(prompt):
        return REPORT
    monkeypatch.setattr(main, "review_json", fake)
    r = client.post("/review", json={"code": "print(1)"})
    assert r.status_code == 200
    assert r.json()["review"]["overall_score"] == 3


def test_empty_code_rejected():
    assert client.post("/review", json={"code": "   "}).status_code == 400


def test_oversized_code_rejected():
    assert client.post("/review", json={"code": "x" * 100_001}).status_code == 413


def test_llm_failure_is_502(monkeypatch):
    async def boom(prompt):
        raise LLMError("cannot reach Ollama")
    monkeypatch.setattr(main, "review_json", boom)
    r = client.post("/review", json={"code": "print(1)"})
    assert r.status_code == 502 and "Ollama" in r.json()["detail"]


def test_strip_fences():
    assert llm._strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
