"""Live golden tests through the full pipeline: need `ollama serve` and the model pulled.

Run with:  pytest -m live
Each snippet has a flaw that must be reported at critical/high severity on the right line.
"""

import asyncio

import pytest

from reviewer.config import Config
from reviewer.engine import review_source
from reviewer.llm import LLMError

pytestmark = pytest.mark.live

CASES = {  # name: (filename, code, lines where the flaw may legitimately be reported)
    "sql_injection": ("a.py", 'def get(db, uid):\n    return db.execute("SELECT * FROM users WHERE id = " + uid).fetchall()\n', (2,)),
    "div_zero": ("b.py", "def divide(a, b):\n    return a / b\n\nprint(divide(10, 0))\n", (2, 4)),
    "hardcoded_secret": ("c.py", 'import requests\nAPI_KEY = "sk-live-1234567890abcdef"\n\ndef call():\n    return requests.get("https://x", headers={"Authorization": API_KEY})\n', (2,)),
    "js_eval": ("d.js", "function run(s) {\n  return eval(s);\n}\n", (2,)),
    "off_by_one": ("e.py", "def last(xs):\n    return xs[len(xs)]\n", (2,)),
}


@pytest.mark.parametrize("name", CASES)
def test_flaw_is_caught_on_the_right_line(name):
    fname, code, lines = CASES[name]
    try:
        r = asyncio.run(review_source(fname, code, config=Config(use_cache=False)))
    except LLMError as e:
        pytest.skip(str(e))
    hits = [f for f in r.findings if f.severity in ("critical", "high") and any(f.line_start <= l <= f.line_end for l in lines)]
    assert hits, r.findings


def test_clean_code_has_no_serious_findings():
    code = 'def add(a: int, b: int) -> int:\n    """Return the sum."""\n    return a + b\n'
    try:
        r = asyncio.run(review_source("ok.py", code, config=Config(use_cache=False)))
    except LLMError as e:
        pytest.skip(str(e))
    assert not [f for f in r.findings if f.severity in ("critical", "high")], r.findings
