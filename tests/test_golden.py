"""Live golden tests: need `ollama serve` and the model pulled.

Run with:  pytest -m live
Each snippet has a flaw the reviewer must report at critical/high severity.
"""

import asyncio

import pytest

from agent.llm import LLMError, review_json

pytestmark = pytest.mark.live

CASES = {
    "sql_injection": 'def get(db, uid):\n    return db.execute("SELECT * FROM users WHERE id = " + uid).fetchall()\n',
    "eval": "def run(s):\n    return eval(s)\n",
    "div_zero": "def divide(a, b):\n    return a / b\n\nprint(divide(10, 0))\n",
    "hardcoded_secret": 'API_KEY = "sk-live-1234567890abcdef"\n\ndef call():\n    return requests.get("https://x", headers={"Authorization": API_KEY})\n',
}


@pytest.mark.parametrize("name", CASES)
def test_flaw_is_caught(name):
    try:
        r = asyncio.run(review_json(f"```\n{CASES[name]}\n```"))
    except LLMError as e:
        pytest.skip(str(e))
    issues = r["bugs"] + r["security_issues"]
    assert any(i.get("severity") in ("critical", "high") for i in issues), r
