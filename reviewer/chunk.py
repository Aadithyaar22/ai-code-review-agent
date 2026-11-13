"""Split large files into model-sized chunks at natural top-level boundaries."""


def chunk_ranges(lines: list[str], max_lines: int = 220) -> list[tuple[int, int]]:
    """Return 1-indexed inclusive (start, end) ranges covering the file."""
    n = len(lines)
    if n <= max_lines:
        return [(1, n)] if n else []

    def is_boundary(i: int) -> bool:  # 0-indexed line starts a new top-level unit
        return (i > 0 and not lines[i - 1].strip() and bool(lines[i].strip())
                and not lines[i][0].isspace() and not lines[i].startswith(("}", ")", "]")))

    out, start = [], 0
    while start < n:
        end = min(start + max_lines, n)  # exclusive
        if end < n:
            cut = next((i for i in range(end, start + max_lines // 2, -1) if is_boundary(i)), None)
            if cut is not None:
                end = cut
        out.append((start + 1, end))
        start = end
    return out
