"""Before/after table: python eval/compare.py  (reads the saved result files, no model calls)."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.cases import CASES as DEV  # noqa: E402
from eval.heldout import CASES as HELD  # noqa: E402
from eval.metrics import aggregate, filter_sev, score_case  # noqa: E402

RUNS = [  # (label, cases, results file)
    ("Dev (58 cases, tuned on)", "before", DEV, "results_dev_baseline.json"),
    ("Dev (58 cases, tuned on)", "after", DEV, "results.json"),
    ("Held-out (25 cases, never tuned on)", "before", HELD, "results_heldout_baseline.json"),
    ("Held-out (25 cases, never tuned on)", "after", HELD, "results_heldout.json"),
]


def pct(x):
    return "—" if x is None else f"{x * 100:.0f}%"


def main() -> str:
    out = ["| Set | Pipeline | Precision (≥ medium) | Recall | F1 | False alarms on clean files | Findings |", "|---|---|---|---|---|---|---|"]
    for label, when, cases, fn in RUNS:
        res = json.loads((ROOT / "eval" / fn).read_text())
        sc = [score_case(c, filter_sev(res[c["id"]]["findings"], "medium")) for c in cases if c["id"] in res]
        a = aggregate(sc)
        f = a["files"]
        out.append(f"| {label} | {when} | {pct(a['precision'])} [{a['precision_ci'][0] * 100:.0f}–{a['precision_ci'][1] * 100:.0f}] | "
                   f"{pct(a['recall'])} ({a['found']}/{a['bugs']}) | {pct(a['f1'])} | {pct(f['fpr'])} ({f['fp']}/{f['clean']}) | {a['findings']} |")
    text = "\n".join(out)
    print(text)
    return text


if __name__ == "__main__":
    main()
