"""Command line interface. See README for examples."""

import argparse
import asyncio
import fnmatch
import shutil
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from reviewer import gitutil
from reviewer.config import load_config
from reviewer.diffparse import parse_diff
from reviewer.engine import is_reviewable, review_source
from reviewer.formats import RENDERERS, REPO_RENDERERS
from reviewer.llm import DEFAULT_MODEL, LLMError
from reviewer.models import SEVERITY_RANK
from reviewer.repo import GITHUB_RE, clone, review_repo

MAX_FILE_BYTES = 200_000


@dataclass
class Target:
    path: str
    code: str
    changed: set[int] | None = None


def _ignored(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(path, p) or fnmatch.fnmatch(Path(path).name, p) for p in patterns)


def collect_paths(paths: list[str], patterns: list[str]) -> list[Target]:
    targets: list[Target] = []
    for p in paths:
        if p == "-":
            targets.append(Target("stdin", sys.stdin.read()))
            continue
        path = Path(p)
        if path.is_dir():
            try:
                files = gitutil.tracked_files(str(path))
            except gitutil.GitError:
                files = [str(f) for f in path.rglob("*") if f.is_file()]
            candidates = [f for f in files if is_reviewable(f) and not _ignored(f, patterns)]
        elif path.is_file():
            candidates = [str(path)]
        else:
            sys.exit(f"error: no such file or directory: {p}")
        for f in sorted(candidates):
            fp = Path(f)
            if not fp.is_file():
                continue
            if fp.stat().st_size > MAX_FILE_BYTES:
                print(f"skipping {f}: larger than {MAX_FILE_BYTES // 1000} KB", file=sys.stderr)
                continue
            code = fp.read_text(errors="replace")
            if code.strip():
                targets.append(Target(f, code))
    return targets


def collect_diff(staged: bool, ref: str | None, patterns: list[str]) -> list[Target]:
    root = gitutil.repo_root()
    diff = gitutil.diff(["--staged"] if staged else ([ref] if ref else []))
    targets = []
    for rel, changed in parse_diff(diff).items():
        if not is_reviewable(rel) or _ignored(rel, patterns):
            continue
        try:
            code = gitutil.file_at_index(rel, root) if staged else (Path(root) / rel).read_text(errors="replace")
        except (gitutil.GitError, OSError):
            continue
        if len(code) <= MAX_FILE_BYTES:
            targets.append(Target(rel, code, changed))
    return targets


def install_hook(fail_on: str) -> int:
    root = gitutil.repo_root()
    hook = Path(root) / ".git" / "hooks" / "pre-commit"
    if hook.exists():
        print(f"{hook} already exists; not overwriting. Remove it first to reinstall.", file=sys.stderr)
        return 1
    script = Path(__file__).resolve().parent.parent / "cli.py"
    hook.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" --staged --fail-on {fail_on}\n')
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC)
    print(f"Installed pre-commit hook → {hook}\nBypass once with: git commit --no-verify")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="cli.py", description="Local AI code review (Ollama, no API key)")
    ap.add_argument("paths", nargs="*", help="files or directories to review, or - for stdin")
    ap.add_argument("--staged", action="store_true", help="review staged changes (only changed lines are reported)")
    ap.add_argument("--diff", nargs="?", const="", metavar="REF", help="review unstaged changes, or changes vs REF")
    ap.add_argument("--repo", nargs="?", const=".", metavar="PATH_OR_GITHUB_URL",
                    help="rate a whole repository and list the changes required (default: current directory)")
    ap.add_argument("--max-files", type=int, default=15,
                    help="with --repo: how many files get a full AI review, riskiest first (default 15)")
    ap.add_argument("--format", choices=RENDERERS, default="text")
    ap.add_argument("-o", "--output", help="write the report to a file")
    ap.add_argument("--fail-on", choices=[*SEVERITY_RANK, "never"], default="high",
                    help="exit 1 if a finding at/above this severity exists (default: high)")
    ap.add_argument("--min-severity", choices=list(SEVERITY_RANK), help="hide findings below this severity")
    ap.add_argument("--include-style", action="store_true", help="include style findings (hidden by default)")
    ap.add_argument("--language", help="language hint (for stdin)")
    ap.add_argument("--model", help=f"Ollama model (default {DEFAULT_MODEL})")
    ap.add_argument("--context", help="extra project context for the reviewer")
    ap.add_argument("--no-cache", action="store_true", help="ignore cached results")
    ap.add_argument("--no-verifier", action="store_true",
                    help="skip the skeptical second pass (faster, but more false alarms)")
    ap.add_argument("--no-static", action="store_true", help="skip ruff/syntax pre-checks")
    ap.add_argument("--install-hook", action="store_true", help="install a git pre-commit hook and exit")
    return ap


async def run_repo(args: argparse.Namespace, cfg) -> int:
    target, tmp = args.repo, None
    try:
        if GITHUB_RE.match(target):
            print(f"Cloning {target} …", file=sys.stderr)
            try:
                tmp, target = await clone(target)
            except ValueError as e:
                print(f"error: {e}", file=sys.stderr)
                return 2
        elif not Path(target).is_dir():
            print(f"error: not a directory or GitHub URL: {target}", file=sys.stderr)
            return 2
        last = {"cur": ""}

        def progress(e: dict) -> None:
            if e["phase"] == "reviewing" and e["current"] != last["cur"]:
                last["cur"] = e["current"]
                print(f"  [{e['done'] + 1}/{e['total']}] {e['current']}", file=sys.stderr)

        print(f"Rating repository with {cfg.model or DEFAULT_MODEL} (up to {args.max_files} files) …", file=sys.stderr)
        try:
            report = await review_repo(target, cfg, args.max_files, on_progress=progress)
        except (ValueError, LLMError) as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    text = REPO_RENDERERS[args.format](report)
    if args.output:
        Path(args.output).write_text(text)
        print(f"Wrote {args.format} report to {args.output}", file=sys.stderr)
    else:
        print(text)
    if args.fail_on != "never":
        limit = SEVERITY_RANK[args.fail_on]
        if any(SEVERITY_RANK.get(f.severity, 9) <= limit for f in report.all_findings()):
            return 1
    return 0


async def run(args: argparse.Namespace) -> int:
    if args.install_hook:
        return install_hook(args.fail_on if args.fail_on != "never" else "high")
    cfg = load_config()
    if args.model:
        cfg.model = args.model
    if args.context:
        cfg.context = args.context
    if args.min_severity:
        cfg.min_severity = args.min_severity
    if args.include_style:
        cfg.ignore_categories = [c for c in cfg.ignore_categories if c != "style"]
    cfg.use_cache = cfg.use_cache and not args.no_cache
    cfg.use_static = cfg.use_static and not args.no_static
    cfg.use_verifier = cfg.use_verifier and not args.no_verifier

    if args.repo is not None:
        return await run_repo(args, cfg)

    targets: list[Target] = []
    try:
        if args.staged or args.diff is not None:
            targets += collect_diff(args.staged, args.diff or None, cfg.ignore_paths)
            if not targets:
                print("No reviewable changes.", file=sys.stderr)
                return 0
        targets += collect_paths(args.paths, cfg.ignore_paths)
    except gitutil.GitError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if not targets:
        build_parser().error("nothing to review: give files/dirs, -, --staged or --diff")

    progress = lambda m: print(m, file=sys.stderr)
    print(f"Reviewing {len(targets)} file(s) with {cfg.model or DEFAULT_MODEL} …", file=sys.stderr)
    reports, failed = [], False
    for t in targets:
        try:
            reports.append(await review_source(t.path, t.code, args.language, config=cfg,
                                               changed=t.changed, on_progress=progress))
        except LLMError as e:
            print(f"error reviewing {t.path}: {e}", file=sys.stderr)
            failed = True

    text = RENDERERS[args.format](reports)
    if args.output:
        Path(args.output).write_text(text)
        print(f"Wrote {args.format} report to {args.output}", file=sys.stderr)
    else:
        print(text)

    if failed:
        return 2
    if args.fail_on != "never":
        limit = SEVERITY_RANK[args.fail_on]
        if any(SEVERITY_RANK.get(f.severity, 9) <= limit for r in reports for f in r.findings):
            return 1
    return 0


def main() -> None:
    sys.exit(asyncio.run(run(build_parser().parse_args())))
