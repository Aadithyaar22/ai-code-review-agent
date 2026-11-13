"""Fast, deterministic checks that run before the LLM (Python only, via ruff + ast)."""

import ast
import json
import re
import shutil
import subprocess
import sys

from reviewer.models import Finding

RUFF_SELECT = "E9,F,B,S,PLE,PLW"

HIGH = {"F821", "F822", "F823", "S102", "S307", "S301", "S302", "S506", "S602", "S605", "S608",
        "S105", "S106", "S107", "S324", "S501", "S507", "S701", "PLE0604", "PLE0605"}
LOW = {"B904", "S603", "S607", "S404", "F401", "F841", "F811", "S101", "S311", "S110", "S112", "PLW0603", "PLW2901", "B007"}


_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|specs?)/|(^|/)test_[^/]*$|_test\.[a-z]+$|conftest\.py$")


def _severity(code: str) -> str:
    if code in HIGH:
        return "high"
    if code in LOW:
        return "low"
    return "medium"


def _category(code: str) -> str:
    return "security" if code.startswith("S") else "bug"


def _ruff_cmd() -> list[str] | None:
    exe = shutil.which("ruff")
    if exe:
        return [exe]
    try:
        subprocess.run([sys.executable, "-m", "ruff", "--version"], capture_output=True, check=True)
        return [sys.executable, "-m", "ruff"]
    except (subprocess.CalledProcessError, OSError):
        return None


def run_static(path: str, code: str, language: str) -> list[Finding]:
    if language != "python":
        return []
    findings: list[Finding] = []
    try:
        ast.parse(code)
    except SyntaxError as e:
        line = e.lineno or 1
        return [Finding(file=path, line_start=line, line_end=line, severity="high", category="bug",
                        title="Syntax error", description=str(e.msg), source="syntax",
                        evidence=(e.text or "").strip(), rule="E999")]
    cmd = _ruff_cmd()
    if not cmd:
        return findings
    try:
        out = subprocess.run(
            cmd + ["check", "--stdin-filename", "file.py", "--output-format", "json",
                   "--select", RUFF_SELECT, "--no-cache", "-"],
            input=code, capture_output=True, text=True, timeout=30,
        )
        items = json.loads(out.stdout or "[]")
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        return findings
    lines = code.splitlines()
    for it in items:
        rule = it.get("code") or ""
        if rule.startswith("S") and _TEST_PATH.search(path):
            continue  # asserts / hardcoded values / subprocess in tests are expected
        start = it["location"]["row"]
        end = it.get("end_location", {}).get("row", start)
        findings.append(Finding(
            file=path, line_start=start, line_end=max(start, end), severity=_severity(rule),
            category=_category(rule), title=f"{rule}: {it.get('message', '')}",
            description=it.get("message", ""), source="ruff", rule=rule,
            evidence=lines[start - 1].strip() if 0 < start <= len(lines) else "",
        ))
    return findings
