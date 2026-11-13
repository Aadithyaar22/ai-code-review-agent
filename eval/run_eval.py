"""Run the labeled benchmark through the real pipeline and report precision / recall / F1.

  python eval/run_eval.py                 # all cases (resumable: results are saved after every case)
  python eval/run_eval.py --ids py_sqli_concat,js_eval
  python eval/run_eval.py --report-only   # recompute metrics + EVALUATION.md from saved results
"""

import argparse
import asyncio
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from eval.cases import CASES  # noqa: E402
from eval.metrics import (aggregate, breakdown, filter_sev, locate,  # noqa: E402
                          recall_by_bug_category, score_case)
from reviewer.config import Config  # noqa: E402
from reviewer.engine import review_source  # noqa: E402
from reviewer.llm import LLMError  # noqa: E402

RESULTS = ROOT / "eval" / "results.json"
ADJ = ROOT / "eval" / "adjudications.json"
REPORT = ROOT / "EVALUATION.md"


def raw_to_findings(raw: list[dict]) -> list[dict]:
    """The model's output with NO verification: its own line numbers, any confidence (style excluded,
    since the product hides style by default)."""
    out = []
    for r in raw:
        try:
            out.append({"line_start": int(r["line_start"]), "line_end": int(r["line_end"]), "severity": r["severity"],
                        "category": r["category"], "title": str(r.get("title", "")),
                        "description": str(r.get("description", "")), "source": "raw"})
        except (KeyError, ValueError, TypeError):
            continue
    return [f for f in out if f["category"] != "style"]


async def run_cases(cases: list[dict], model: str | None, use_cache: bool) -> dict:
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    cfg = Config(model=model, use_cache=use_cache)
    for i, c in enumerate(cases, 1):
        if c["id"] in results and results[c["id"]].get("model") == (model or "default"):
            continue
        raw: list = []
        t0 = time.time()
        print(f"[{i}/{len(cases)}] {c['id']} …", flush=True)
        try:
            rep = await review_source(c["file"], c["code"], c["lang"], config=cfg, raw_sink=raw)
        except LLMError as e:
            print(f"   LLM error: {e}", flush=True)
            continue
        results[c["id"]] = {
            "model": model or "default", "seconds": round(time.time() - t0, 1),
            "findings": [f.model_dump() for f in rep.findings], "raw": raw, "stats": rep.stats}
        RESULTS.write_text(json.dumps(results, indent=1))
        print(f"   {len(rep.findings)} finding(s), {results[c['id']]['seconds']}s", flush=True)
    return results


def pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"


def ci(t):
    return f"[{t[0] * 100:.0f}–{t[1] * 100:.0f}]"


def row(name, a):
    return (f"| {name} | {a['findings']} | {a['tp']} | {pct(a['precision'])} {ci(a['precision_ci'])} | "
            f"{a['found']}/{a['bugs']} | {pct(a['recall'])} {ci(a['recall_ci'])} | {pct(a['f1'])} |")


def evaluate(cases: list[dict], results: dict) -> dict:
    adjudicated = set(json.loads(ADJ.read_text()).get("valid_findings", {})) if ADJ.exists() else set()
    done = [c for c in cases if c["id"] in results]

    def scored(getter, floor=None, adj=False, semantic=True):
        return [score_case(c, filter_sev(getter(results[c["id"]]), floor), adjudicated if adj else None, semantic)
                for c in done]

    full = lambda r: r["findings"]
    llm_only = lambda r: [f for f in r["findings"] if f["source"] == "llm"]
    static_only = lambda r: [f for f in r["findings"] if f["source"] != "llm"]
    raw = lambda r: raw_to_findings(r["raw"])
    variants = {
        "Full pipeline (≥ low)": scored(full),
        "Full pipeline (≥ medium)": scored(full, "medium"),
        "Full pipeline (≥ high)": scored(full, "high"),
        "AI findings only, verified (≥ low)": scored(llm_only),
        "Static analysis only (ruff)": scored(static_only),
        "Raw model output, no verification": scored(raw),
        "(lenient) Full pipeline ≥ medium, line overlap only": scored(full, "medium", False, False),
    }
    return {"done": done, "adjudicated": adjudicated, "variants": variants,
            "agg": {k: aggregate(v) for k, v in variants.items()},
            "agg_adj": {k: aggregate(v, True) for k, v in
                        {"Full pipeline (≥ low)": scored(full, None, True),
                         "Full pipeline (≥ medium)": scored(full, "medium", True)}.items()}}


def write_report(cases, results, ev, model_name) -> str:
    done, agg, variants = ev["done"], ev["agg"], ev["variants"]
    main_key = "Full pipeline (≥ medium)"
    main = agg[main_key]
    secs = [results[c["id"]]["seconds"] for c in done]
    verif = {}
    for c in done:
        for k, v in results[c["id"]]["stats"].items():
            if k.startswith("dropped_"):
                verif[k] = verif.get(k, 0) + v
    L = ["# Evaluation — how accurate are the findings?\n",
         f"Benchmark: **{len(done)} labeled snippets** ({sum(1 for c in done if c['bugs'])} with known defects, "
         f"{sum(1 for c in done if not c['bugs'])} clean/decoy), **{sum(len(c['bugs']) for c in done)} labeled bugs**, "
         f"6 languages. Model: `{model_name}`. Reproduce: `python eval/run_eval.py`.\n",
         "## Headline\n",
         "| Metric (full pipeline, findings ≥ medium) | Value | 95% CI |", "|---|---|---|",
         f"| **Precision** (findings that are real) | **{pct(agg[main_key]['precision'])}** ({agg[main_key]['tp']}/{agg[main_key]['findings']}) | {ci(agg[main_key]['precision_ci'])} |",
         f"| **Recall** (labeled bugs found) | **{pct(agg[main_key]['recall'])}** ({agg[main_key]['found']}/{agg[main_key]['bugs']}) | {ci(agg[main_key]['recall_ci'])} |",
         f"| **F1** | **{pct(agg[main_key]['f1'])}** | |",
         f"| File-level accuracy (buggy vs clean) | {pct(agg[main_key]['files']['accuracy'])} | |",
         f"| False-positive rate on clean files | {pct(agg[main_key]['files']['fpr'])} ({agg[main_key]['files']['fp']}/{agg[main_key]['files']['clean']}) | |",
         f"| Category agreement on matched findings | {pct(agg[main_key]['category_agreement'])} | |\n",
         "## All variants\n",
         "| Variant | Findings | True pos. | Precision [95% CI] | Bugs found | Recall [95% CI] | F1 |", "|---|---|---|---|---|---|---|"]
    L += [row(k, a) for k, a in agg.items()]
    if ev["agg_adj"] and ev["adjudicated"]:
        L += ["", f"**After manual adjudication** ({len(ev['adjudicated'])} 'false positives' were real issues the labels missed — see below):", "",
              "| Variant | Findings | Correct | Precision [95% CI] | Bugs found | Recall [95% CI] | F1 |", "|---|---|---|---|---|---|---|"]
        L += [row(k, a) for k, a in ev["agg_adj"].items()]
    L += ["", "## What the verification layer buys you\n",
          "'Raw model output' is what the LLM said before the pipeline checks the quoted evidence, corrects line numbers, "
          "drops low-confidence/noise findings and merges with static analysis.\n"]
    r, f = agg["Raw model output, no verification"], agg["Full pipeline (≥ low)"]
    L.append(f"- Precision: raw **{pct(r['precision'])}** → pipeline **{pct(f['precision'])}**")
    L.append(f"- Recall: raw **{pct(r['recall'])}** → pipeline **{pct(f['recall'])}**")
    L.append(f"- Findings dropped by the evidence check across the benchmark: {verif or 'none'}")
    if not verif:
        L.append("- **The evidence check dropped nothing here.** On short snippets the model quotes code accurately, so this benchmark "
                 "does not exercise that feature. Its value (catching invented quotes in large files) is **not measured** by these numbers.")
    L += ["", "## File-level confusion (full pipeline, ≥ medium)\n", "| | Flagged | Not flagged |", "|---|---|---|",
          f"| **Buggy files** ({main['files']['buggy']}) | {main['files']['tp']} (caught) | {main['files']['fn']} (missed) |",
          f"| **Clean files** ({main['files']['clean']}) | {main['files']['fp']} (false alarm) | {main['files']['tn']} (correct) |",
          "", "## By language (full pipeline, ≥ medium)\n", "| Language | Cases | Findings | Precision | Recall | F1 |", "|---|---|---|---|---|---|"]
    for k, a in breakdown(main_scored := variants[main_key], lambda s: s["lang"]).items():
        L.append(f"| {k} | {a['files']['buggy'] + a['files']['clean']} | {a['findings']} | {pct(a['precision'])} | {pct(a['recall'])} | {pct(a['f1'])} |")
    L += ["", "## Recall by defect type (full pipeline, ≥ low)\n", "| Type | Found | Recall [95% CI] |", "|---|---|---|"]
    for k, a in recall_by_bug_category(variants["Full pipeline (≥ low)"]).items():
        L.append(f"| {k} | {a['found']}/{a['bugs']} | {pct(a['recall'])} {ci(a['ci'])} |")
    L += ["", "## Precision by severity (full pipeline)\n", "| Severity | Findings | Correct | Precision [95% CI] |", "|---|---|---|---|"]
    for sev in ("critical", "high", "medium", "low"):
        sc = [score_case(c, [f for f in results[c["id"]]["findings"] if f["severity"] == sev], ev["adjudicated"] or None) for c in done]
        a = aggregate(sc)
        L.append(f"| {sev} | {a['findings']} | {a['tp']} | {pct(a['precision'])} {ci(a['precision_ci'])} |")
    L += ["", "## Does the model's own confidence help? (full pipeline, AI findings filtered by confidence)\n",
          "Static-analysis findings are always kept. Tuning a threshold on the same data it is measured on overstates the gain; "
          "this table shows the trend, it is not a validated setting.\n",
          "| Min AI confidence | Findings | Precision | Recall | F1 |", "|---|---|---|---|---|"]
    for t in (0.0, 0.7, 0.8, 0.9, 0.95, 1.0):
        sc = [score_case(c, [f for f in results[c["id"]]["findings"] if f["source"] != "llm" or f.get("confidence", 1) >= t]) for c in done]
        a = aggregate(sc)
        L.append(f"| ≥ {t:.2f} | {a['findings']} | {pct(a['precision'])} | {pct(a['recall'])} | {pct(a['f1'])} |")
    L += ["", "## Missed bugs (false negatives, ≥ low)\n"]
    miss = [(s["id"], b) for s in variants["Full pipeline (≥ low)"] for b in s["missed"]]
    L += [f"- `{i}` line {b['start']}: {b['what']}" for i, b in miss] or ["_None._"]
    L += ["", "## False positives (full pipeline, ≥ medium)\n"]
    fps = [(s["id"], f) for s in main_scored for f in s["fp"]]
    for i, f in fps:
        tag = "adjudicated: valid" if f"{i}::{f['title']}" in ev["adjudicated"] else ""
        L.append(f"- `{i}` line {f['line_start']} [{f['severity']}/{f['category']}, {f['source']}] {f['title']} {tag}")
    if not fps:
        L.append("_None._")
    L += ["", "## Speed\n", f"Median {statistics.median(secs):.0f}s per file, total {sum(secs) / 60:.1f} min on a local model "
          f"(cached results report ~0s). Results are cached, so unchanged code is instant on re-run.", "",
          "## How to read this — and its limits\n",
          "- The benchmark is **small and synthetic**, written by the project author: short single-purpose snippets with 1–2 obvious defects. "
          "Real repositories are larger and messier, so expect lower recall and more false positives there. Treat the numbers as a "
          "regression baseline and a relative comparison between variants, not as a promise about production accuracy.",
          "- **Matching is strict:** a finding must touch the labeled line (±1) **and** describe the right kind of defect (keyword check in "
          "`eval/cases.py`). A first version used line overlap only; it wrongly credited findings like \"Potential KeyError\" for an N+1 bug "
          "and overstated recall (see the *lenient* row).",
          "- The keyword patterns and labels were written by the same person who built the tool, which can bias results in its favour.",
          "- 95% intervals are Wilson score intervals; with this sample size they are wide. Differences of a few points are noise.",
          "- Category is scored separately (category agreement).",
          "- Labels come from the author. The harness lists every false positive so each can be judged by hand; "
          "judgements are recorded in `eval/adjudications.json` and reported separately from the strict numbers.",
          "- Ruff (static) findings are included in 'full pipeline', which is how users experience the tool."]
    text = "\n".join(L) + "\n"
    REPORT.write_text(text)
    return text


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids")
    ap.add_argument("--model")
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    for c in CASES:
        locate(c)  # fail fast on a broken label
    cases = [c for c in CASES if not a.ids or c["id"] in a.ids.split(",")]
    results = json.loads(RESULTS.read_text()) if RESULTS.exists() else {}
    if not a.report_only:
        results = await run_cases(cases, a.model, not a.no_cache)
    ev = evaluate(cases, results)
    from reviewer.llm import DEFAULT_MODEL
    text = write_report(cases, results, ev, a.model or DEFAULT_MODEL)
    print("\n" + text)


if __name__ == "__main__":
    asyncio.run(main())
