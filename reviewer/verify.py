"""Turn raw LLM output into trustworthy findings.

The model is asked to quote the offending code. A finding whose quote cannot be found
in the file is a hallucination and is dropped; real ones get their line numbers snapped
to where the quote actually is.
"""

import re

from reviewer.models import SEVERITY_RANK, Finding

_NOISE = re.compile(r"docstring|type hint|type annotation|add (a )?comment|add logging|naming convention",
                    re.I)


_NO_TRIGGER = re.compile(r"^\W*(none|n/?a|unknown|not applicable|no specific|nothing|-+|\?+)\b", re.I)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _clean_evidence(ev: str) -> str:
    # models sometimes emit a literal backslash-n for a line break, or copy the `12| ` prefix
    ev = ev.replace("\\r\\n", "\n").replace("\\n", "\n")
    return "\n".join(re.sub(r"^\s*\d+\|\s?", "", l) for l in ev.splitlines()).strip()


def verify_llm_findings(raw: list[dict], path: str, lines: list[str], min_confidence: float,
                        stats: dict) -> list[Finding]:
    n = len(lines)
    normed = [_norm(l) for l in lines]
    out: list[Finding] = []
    for r in raw:
        try:
            ls, le = int(r["line_start"]), int(r["line_end"])
            ev = _clean_evidence(str(r.get("evidence", "")))
            first = next((_norm(l) for l in ev.splitlines() if _norm(l)), "")
            if len(first) < 4:
                stats["dropped_no_evidence"] = stats.get("dropped_no_evidence", 0) + 1
                continue
            cands = [i + 1 for i, l in enumerate(normed) if first in l]
            if not cands:
                stats["dropped_hallucinated"] = stats.get("dropped_hallucinated", 0) + 1
                continue
            if le < ls:
                ls, le = le, ls
            best = min(cands, key=lambda c: abs(c - ls))
            if not (ls <= best <= le):
                span = le - ls
                ls, le = best, min(n, best + span)
            ls, le = max(1, min(ls, n)), max(1, min(le, n))
            trigger = str(r.get("trigger", "")).strip()
            if len(trigger) < 6 or _NO_TRIGGER.search(trigger):
                stats["dropped_no_trigger"] = stats.get("dropped_no_trigger", 0) + 1
                continue
            conf = float(r.get("confidence", 0.7))
            if conf < min_confidence:
                stats["dropped_low_confidence"] = stats.get("dropped_low_confidence", 0) + 1
                continue
            title = str(r.get("title", "")).strip()
            if _NOISE.search(title):
                stats["dropped_noise"] = stats.get("dropped_noise", 0) + 1
                continue
            out.append(Finding(
                file=path, line_start=ls, line_end=le, severity=r["severity"], category=r["category"],
                title=title, description=str(r.get("description", "")).strip(),
                fix=str(r.get("fix", "")).replace("\\n", "\n").strip(), evidence=first, trigger=trigger, confidence=conf, source="llm"))
        except (KeyError, ValueError, TypeError):
            stats["dropped_malformed"] = stats.get("dropped_malformed", 0) + 1
    return out


def _overlap(a: Finding, b: Finding) -> bool:
    return a.line_start <= b.line_end and b.line_start <= a.line_end


def dedupe(static: list[Finding], llm: list[Finding]) -> list[Finding]:
    """Static findings win; LLM findings merge when they overlap on the same lines+category."""
    kept = list(static)
    for f in sorted(llm, key=lambda f: SEVERITY_RANK.get(f.severity, 9)):
        if any(_overlap(f, k) and f.category == k.category for k in kept):
            continue
        kept.append(f)
    return kept


def sort_findings(fs: list[Finding]) -> list[Finding]:
    return sorted(fs, key=lambda f: (SEVERITY_RANK.get(f.severity, 9), f.file, f.line_start))
