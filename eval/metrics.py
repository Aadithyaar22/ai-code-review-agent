"""Scoring for the benchmark: matching findings to labeled bugs and computing P/R/F1.

Definitions (used consistently everywhere):
  * a finding is a TRUE POSITIVE if its line span touches a labeled bug's line (±1 line tolerance);
    otherwise it is a FALSE POSITIVE. (Several findings on the same bug are all counted as true positives.)
  * a labeled bug is FOUND if at least one finding touches it, otherwise MISSED (false negative).
  * precision = TP findings / all findings;  recall = bugs found / all labeled bugs.
  * file-level: a file is "flagged" if it has >= 1 finding at the severity threshold.
"""

import math
import re
from collections import defaultdict

SEV_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
TOL = 1


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion k/n (honest uncertainty on small samples)."""
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, (c - m) / d), min(1.0, (c + m) / d))


def locate(case: dict) -> list[dict]:
    """Resolve each labeled bug to a (start, end) line span by finding its anchor text."""
    lines = case["code"].splitlines()
    out = []
    for b in case["bugs"]:
        start = next((i + 1 for i, l in enumerate(lines) if b["at"] in l), None)
        if start is None:
            raise ValueError(f"{case['id']}: anchor {b['at']!r} not found")
        end = start
        if b.get("end"):
            end = next((i + 1 for i, l in enumerate(lines) if i + 1 >= start and b["end"] in l), None)
            if end is None:
                raise ValueError(f"{case['id']}: end anchor {b['end']!r} not found")
        out.append({**b, "start": start, "end_line": end})
    return out


def touches(f: dict, bug: dict, tol: int = TOL, semantic: bool = True) -> bool:
    """Line overlap (±tol) and, when the bug has a keyword pattern, a matching description."""
    if not (f["line_start"] - tol <= bug["end_line"] and f["line_end"] + tol >= bug["start"]):
        return False
    if semantic and bug.get("kw"):
        text = f"{f.get('title', '')} {f.get('description', '')} {f.get('rule', '')}"
        return re.search(bug["kw"], text, re.I) is not None
    return True


def filter_sev(findings: list[dict], floor: str | None) -> list[dict]:
    if floor is None:
        return findings
    return [f for f in findings if SEV_RANK.get(f.get("severity"), 9) <= SEV_RANK[floor]]


def score_case(case: dict, findings: list[dict], adjudicated: set[str] | None = None, semantic: bool = True) -> dict:
    """Match findings to bugs for one case. `adjudicated` = keys of false positives judged valid by a human."""
    bugs = locate(case)
    adjudicated = adjudicated or set()
    tp, fp, valid_extra = [], [], []
    hit = [False] * len(bugs)
    cat_ok = cat_n = 0
    for f in findings:
        matched = [i for i, b in enumerate(bugs) if touches(f, b, semantic=semantic)]
        if matched:
            tp.append(f)
            for i in matched:
                hit[i] = True
            cat_n += 1
            cat_ok += any(f.get("category") == bugs[i]["cat"] for i in matched)
        elif f"{case['id']}::{f.get('title', '')}" in adjudicated:
            valid_extra.append(f)  # a real issue the labels did not include
        else:
            fp.append(f)
    return {"id": case["id"], "lang": case["lang"], "n_bugs": len(bugs), "tp": tp, "fp": fp, "valid_extra": valid_extra,
            "found": [b for b, h in zip(bugs, hit, strict=True) if h], "missed": [b for b, h in zip(bugs, hit, strict=True) if not h],
            "cat_ok": cat_ok, "cat_n": cat_n, "n_findings": len(findings), "clean": not bugs}


def _prf(tp: int, n_find: int, found: int, n_bugs: int) -> dict:
    p = tp / n_find if n_find else None
    r = found / n_bugs if n_bugs else None
    f1 = 2 * p * r / (p + r) if p and r else (0.0 if p is not None and r is not None else None)
    return {"tp": tp, "findings": n_find, "found": found, "bugs": n_bugs, "precision": p, "recall": r, "f1": f1,
            "precision_ci": wilson(tp, n_find), "recall_ci": wilson(found, n_bugs)}


def aggregate(scored: list[dict], count_valid_extra: bool = False) -> dict:
    """Micro-average over cases. With count_valid_extra, human-validated extra findings count as correct."""
    tp = sum(len(s["tp"]) + (len(s["valid_extra"]) if count_valid_extra else 0) for s in scored)
    n_find = sum(s["n_findings"] for s in scored)
    found = sum(len(s["found"]) for s in scored)
    n_bugs = sum(s["n_bugs"] for s in scored)
    out = _prf(tp, n_find, found, n_bugs)
    clean = [s for s in scored if s["clean"]]
    buggy = [s for s in scored if not s["clean"]]
    flagged_buggy = sum(1 for s in buggy if s["n_findings"] > 0)
    flagged_clean = sum(1 for s in clean if s["n_findings"] > 0)
    out["files"] = {
        "buggy": len(buggy), "clean": len(clean),
        "tp": flagged_buggy, "fn": len(buggy) - flagged_buggy, "fp": flagged_clean, "tn": len(clean) - flagged_clean,
        "accuracy": (flagged_buggy + len(clean) - flagged_clean) / len(scored) if scored else None,
        "fpr": flagged_clean / len(clean) if clean else None,
        "tpr": flagged_buggy / len(buggy) if buggy else None,
    }
    out["category_agreement"] = (sum(s["cat_ok"] for s in scored) / sum(s["cat_n"] for s in scored)
                                 if sum(s["cat_n"] for s in scored) else None)
    return out


def breakdown(scored: list[dict], key, count_valid_extra: bool = False) -> dict:
    groups = defaultdict(list)
    for s in scored:
        groups[key(s)].append(s)
    return {k: aggregate(v, count_valid_extra) for k, v in sorted(groups.items())}


def recall_by_bug_category(scored: list[dict]) -> dict:
    tot, got = defaultdict(int), defaultdict(int)
    for s in scored:
        for b in s["found"]:
            tot[b["cat"]] += 1
            got[b["cat"]] += 1
        for b in s["missed"]:
            tot[b["cat"]] += 1
    return {c: {"found": got[c], "bugs": tot[c], "recall": got[c] / tot[c], "ci": wilson(got[c], tot[c])} for c in sorted(tot)}
