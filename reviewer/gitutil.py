"""Thin wrappers around git."""

import subprocess


class GitError(RuntimeError):
    pass


def _git(*args: str, cwd: str | None = None) -> str:
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True, check=True, cwd=cwd)
    except FileNotFoundError as e:
        raise GitError("git is not installed") from e
    except subprocess.CalledProcessError as e:
        raise GitError(e.stderr.strip() or f"git {args[0]} failed") from e
    return r.stdout


def repo_root() -> str:
    return _git("rev-parse", "--show-toplevel").strip()


def diff(args: list[str]) -> str:
    return _git("diff", "--no-color", "-U3", *args)


def file_at_index(path: str, root: str) -> str:
    return _git("show", f":{path}", cwd=root)


def tracked_files(path: str) -> list[str]:
    out = _git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", path)
    return [p for p in out.split("\0") if p]
