"""
cli.py — run the Code Review Agent locally, no server needed.

Usage
─────
  python cli.py path/to/file.py [more files ...]   review files
  python cli.py --staged                           review `git diff --staged`
  python cli.py --diff                             review unstaged `git diff`
  python cli.py --diff main                        review `git diff main`
  cat snippet.py | python cli.py -                 review stdin

Add --json for raw JSON. Exit code is 1 if any critical/high issue is found,
so it can be used from a git hook or CI.
"""

import argparse
import asyncio
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types as genai_types

from agent.agent import root_agent

APP_NAME = "code_review_agent_cli"
MAX_CHARS = 100_000
SEVERITY_ICON = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🔵"}


def _strip_fences(text: str) -> str:
    text = re.sub(r"^```[a-zA-Z]*\n?", "", text.strip())
    return re.sub(r"```$", "", text.strip()).strip()


def git_diff(args: list[str]) -> str:
    try:
        out = subprocess.run(
            ["git", "diff", *args], capture_output=True, text=True, check=True
        )
    except FileNotFoundError:
        sys.exit("error: git is not installed")
    except subprocess.CalledProcessError as e:
        sys.exit(f"error: git diff failed: {e.stderr.strip()}")
    return out.stdout


async def review(runner: Runner, sessions: InMemorySessionService, prompt: str) -> dict:
    session_id = str(uuid.uuid4())
    await sessions.create_session(
        app_name=APP_NAME, user_id="cli", session_id=session_id
    )
    message = genai_types.Content(role="user", parts=[genai_types.Part(text=prompt)])
    parts: list[str] = []
    async for event in runner.run_async(
        user_id="cli", session_id=session_id, new_message=message
    ):
        if event.is_final_response() and event.content and event.content.parts:
            parts.extend(p.text for p in event.content.parts if p.text)
    raw = _strip_fences("".join(parts))
    if not raw:
        raise RuntimeError("agent returned an empty response")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"agent returned malformed JSON: {e}") from e


def file_prompt(path: str, code: str) -> str:
    return f"File: {path}\n\n```\n{code}\n```"


def diff_prompt(diff: str) -> str:
    return (
        "This is a unified git diff. Review ONLY the changed lines (+/-), using "
        "surrounding context to judge them. Use file names and new-file line "
        "numbers in the 'line' fields.\n\n```diff\n" + diff + "\n```"
    )


def print_report(title: str, r: dict) -> None:
    print(f"\n━━ {title} ━━  ⭐ {r.get('overall_score', '?')}/10  ({r.get('language', '?')})")
    print(r.get("summary", ""))
    for label, key in (("Bugs", "bugs"), ("Security", "security_issues")):
        items = r.get(key) or []
        if items:
            print(f"\n{label}:")
        for i in items:
            icon = SEVERITY_ICON.get(i.get("severity", ""), "•")
            print(f"  {icon} [{i.get('severity')}] line {i.get('line')}: {i.get('description')}")
            print(f"       fix: {i.get('fix')}")
    if r.get("suggestions"):
        print("\nSuggestions:")
        for s in r["suggestions"]:
            print(f"  💡 ({s.get('category')}) {s.get('description')}")
    if r.get("positives"):
        print("\nPositives:")
        for p in r["positives"]:
            print(f"  ✅ {p}")


def has_blocker(r: dict) -> bool:
    return any(
        i.get("severity") in ("critical", "high")
        for i in (r.get("bugs") or []) + (r.get("security_issues") or [])
    )


async def main() -> int:
    ap = argparse.ArgumentParser(description="Local AI code review")
    ap.add_argument("files", nargs="*", help="files to review, or - for stdin")
    ap.add_argument("--staged", action="store_true", help="review staged changes")
    ap.add_argument("--diff", nargs="?", const="", metavar="REF",
                    help="review unstaged changes, or diff against REF")
    ap.add_argument("--json", action="store_true", help="print raw JSON")
    args = ap.parse_args()

    jobs: list[tuple[str, str]] = []  # (title, prompt)
    if args.staged or args.diff is not None:
        diff = git_diff(["--staged"] if args.staged else ([args.diff] if args.diff else []))
        if not diff.strip():
            print("No changes to review.")
            return 0
        jobs.append(("git diff", diff_prompt(diff[:MAX_CHARS])))
    for f in args.files:
        code = sys.stdin.read() if f == "-" else Path(f).read_text(errors="replace")
        if not code.strip():
            print(f"skipping empty input: {f}")
            continue
        jobs.append((f if f != "-" else "stdin", file_prompt(f, code[:MAX_CHARS])))
    if not jobs:
        ap.error("nothing to review: give files, -, --staged or --diff")

    sessions = InMemorySessionService()
    runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=sessions)

    blocked = False
    for title, prompt in jobs:
        try:
            report = await review(runner, sessions, prompt)
        except Exception as e:
            print(f"error reviewing {title}: {e}", file=sys.stderr)
            blocked = True
            continue
        if args.json:
            print(json.dumps({"target": title, "review": report}, indent=2))
        else:
            print_report(title, report)
        blocked |= has_blocker(report)
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
