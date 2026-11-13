"""Parse unified diffs into {path: set(new-file line numbers that were added/changed)}."""

import re

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def parse_diff(diff: str) -> dict[str, set[int]]:
    files: dict[str, set[int]] = {}
    path: str | None = None
    new_line = 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            p = line[4:].strip()
            path = None if p == "/dev/null" else (p[2:] if p.startswith("b/") else p)
            if path is not None:
                files.setdefault(path, set())
        elif line.startswith("@@") and path is not None:
            m = _HUNK.match(line)
            if m:
                new_line = int(m.group(1))
        elif path is not None and new_line:
            if line.startswith("+") and not line.startswith("+++"):
                files[path].add(new_line)
                new_line += 1
            elif line.startswith("-"):
                continue
            elif line.startswith("\\"):
                continue
            else:
                new_line += 1
    return {p: s for p, s in files.items() if s}
