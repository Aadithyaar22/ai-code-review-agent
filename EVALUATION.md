# {TITLE}

Benchmark: **58 labeled snippets** (37 with known defects, 21 clean/decoy), **38 labeled bugs**, 6 languages. Model: `phi4`. Reproduce: `python eval/run_eval.py`.

## Before / after the false-alarm fixes

| Set | Pipeline | Precision (≥ medium) | Recall | F1 | False alarms on clean files | Findings |
|---|---|---|---|---|---|---|
| Dev (58 cases, tuned on) | before | 62% [49–74] | 87% (33/38) | 73% | 62% (13/21) | 53 |
| Dev (58 cases, tuned on) | after | 83% [69–91] | 89% (34/38) | 86% | 24% (5/21) | 41 |
| Held-out (25 cases, never tuned on) | before | 50% [29–71] | 75% (9/12) | 60% | 54% (7/13) | 18 |
| Held-out (25 cases, never tuned on) | after | 59% [36–78] | 83% (10/12) | 69% | 46% (6/13) | 17 |

- The **dev** gain is large but flattering: the new prompt lists safe patterns taken from failures on this very set, so part of it is memorisation.
- The **held-out** set was written before the fixes and run only once afterwards. The gain there is real in direction (precision 50→59%, recall 75→83%, false alarms 54→46%) but **small, and the 95% intervals overlap heavily** - with 17 findings it is not statistically significant. Expect real-world precision somewhere between the two rows.
- What each part contributed: the tighter prompt + required failing input did most of the work. The skeptical second pass dropped 4 findings across both sets - all genuine false alarms, none real - for about +10 s per file. The no-trigger filter dropped nothing (the model always supplies a trigger).
- Still weak: performance issues (N+1, O(n²)) and a few confident false alarms on safe code (e.g. a bounded `snprintf`, an allow-listed redirect).
- One held-out 'miss' (`h_go_nil_map`) is a correct diagnosis reported 2 lines from the label; see `eval/adjudications.json`.

## Headline

| Metric (full pipeline, findings ≥ medium) | Value | 95% CI |
|---|---|---|
| **Precision** (findings that are real) | **82.9%** (34/41) | [69–91] |
| **Recall** (labeled bugs found) | **89.5%** (34/38) | [76–96] |
| **F1** | **86.1%** | |
| File-level accuracy (buggy vs clean) | 86.2% | |
| False-positive rate on clean files | 23.8% (5/21) | |
| Category agreement on matched findings | 97.1% | |

## All variants

| Variant | Findings | True pos. | Precision [95% CI] | Bugs found | Recall [95% CI] | F1 |
|---|---|---|---|---|---|---|
| Full pipeline (≥ low) | 45 | 35 | 77.8% [64–87] | 35/38 | 92.1% [79–97] | 84.3% |
| Full pipeline (≥ medium) | 41 | 34 | 82.9% [69–91] | 34/38 | 89.5% [76–96] | 86.1% |
| Full pipeline (≥ high) | 27 | 25 | 92.6% [77–98] | 25/38 | 65.8% [50–79] | 76.9% |
| AI findings only, verified (≥ low) | 31 | 24 | 77.4% [60–89] | 24/38 | 63.2% [47–77] | 69.6% |
| Static analysis only (ruff) | 14 | 11 | 78.6% [52–92] | 11/38 | 28.9% [17–45] | 42.3% |
| Raw model output, no verification | 45 | 36 | 80.0% [66–89] | 36/38 | 94.7% [83–99] | 86.7% |
| (lenient) Full pipeline ≥ medium, line overlap only | 41 | 36 | 87.8% [74–95] | 35/38 | 92.1% [79–97] | 89.9% |

**After manual adjudication** (1 'false positives' were real issues the labels missed — see below):

| Variant | Findings | Correct | Precision [95% CI] | Bugs found | Recall [95% CI] | F1 |
|---|---|---|---|---|---|---|
| Full pipeline (≥ low) | 45 | 35 | 77.8% [64–87] | 35/38 | 92.1% [79–97] | 84.3% |
| Full pipeline (≥ medium) | 41 | 34 | 82.9% [69–91] | 34/38 | 89.5% [76–96] | 86.1% |

## What the verification layer buys you

'Raw model output' is what the LLM said before the pipeline checks the quoted evidence, corrects line numbers, drops low-confidence/noise findings and merges with static analysis.

- Precision: raw **80.0%** → pipeline **77.8%**
- Recall: raw **94.7%** → pipeline **92.1%**
- Findings dropped by the evidence check across the benchmark: {'dropped_hallucinated': 1, 'dropped_challenged': 2}

## File-level confusion (full pipeline, ≥ medium)

| | Flagged | Not flagged |
|---|---|---|
| **Buggy files** (37) | 34 (caught) | 3 (missed) |
| **Clean files** (21) | 5 (false alarm) | 16 (correct) |

## By language (full pipeline, ≥ medium)

| Language | Cases | Findings | Precision | Recall | F1 |
|---|---|---|---|---|---|
| bash | 2 | 2 | 50.0% | 100.0% | 66.7% |
| c | 4 | 4 | 75.0% | 100.0% | 85.7% |
| go | 5 | 3 | 100.0% | 100.0% | 100.0% |
| java | 3 | 2 | 100.0% | 100.0% | 100.0% |
| javascript | 11 | 8 | 87.5% | 100.0% | 93.3% |
| python | 33 | 22 | 81.8% | 81.8% | 81.8% |

## Recall by defect type (full pipeline, ≥ low)

| Type | Found | Recall [95% CI] |
|---|---|---|
| bug | 16/17 | 94.1% [73–99] |
| performance | 0/2 | 0.0% [0–66] |
| security | 19/19 | 100.0% [83–100] |

## Precision by severity (full pipeline)

| Severity | Findings | Correct | Precision [95% CI] |
|---|---|---|---|
| critical | 13 | 13 | 100.0% [77–100] |
| high | 14 | 12 | 85.7% [60–96] |
| medium | 14 | 9 | 64.3% [39–84] |
| low | 4 | 1 | 25.0% [5–70] |

## Does the model's own confidence help? (full pipeline, AI findings filtered by confidence)

Static-analysis findings are always kept. Tuning a threshold on the same data it is measured on overstates the gain; this table shows the trend, it is not a validated setting.

| Min AI confidence | Findings | Precision | Recall | F1 |
|---|---|---|---|---|
| ≥ 0.00 | 45 | 77.8% | 92.1% | 84.3% |
| ≥ 0.70 | 45 | 77.8% | 92.1% | 84.3% |
| ≥ 0.80 | 45 | 77.8% | 92.1% | 84.3% |
| ≥ 0.90 | 45 | 77.8% | 92.1% | 84.3% |
| ≥ 0.95 | 39 | 82.1% | 84.2% | 83.1% |
| ≥ 1.00 | 17 | 82.4% | 36.8% | 50.9% |

## Missed bugs (false negatives, ≥ low)

- `py_resource_leak` line 2: file handle never closed
- `py_n_plus_one` line 4: N+1 queries inside a loop
- `py_quadratic_dedupe` line 4: O(n^2) membership test on a list

## False positives (full pipeline, ≥ medium)

- `py_resource_leak` line 2 [medium/bug, llm] File not found error 
- `js_missing_await` line 2 [medium/bug, llm] Unhandled fetch errors 
- `clean_py_subprocess_list` line 5 [medium/bug, llm] Uncaught exceptions from subprocess 
- `clean_py_with_open` line 6 [medium/bug, llm] Uncaught JSONDecodeError 
- `clean_py_none_default` line 2 [medium/bug, llm] Mutable default argument 
- `clean_c_snprintf` line 5 [high/bug, llm] Buffer Overflow 
- `clean_sh_quoted_rm` line 4 [high/security, llm] Potential unintended deletion due to symbolic links 

## Speed

Median 44s per file, total 43.4 min on a local model (cached results report ~0s). Results are cached, so unchanged code is instant on re-run.

## How to read this — and its limits

- The benchmark is **small and synthetic**, written by the project author: short single-purpose snippets with 1–2 obvious defects. Real repositories are larger and messier, so expect lower recall and more false positives there. Treat the numbers as a regression baseline and a relative comparison between variants, not as a promise about production accuracy.
- **Matching is strict:** a finding must touch the labeled line (±1) **and** describe the right kind of defect (keyword check in `eval/cases.py`). A first version used line overlap only; it wrongly credited findings like "Potential KeyError" for an N+1 bug and overstated recall (see the *lenient* row).
- The keyword patterns and labels were written by the same person who built the tool, which can bias results in its favour.
- 95% intervals are Wilson score intervals; with this sample size they are wide. Differences of a few points are noise.
- Category is scored separately (category agreement).
- Labels come from the author. The harness lists every false positive so each can be judged by hand; judgements are recorded in `eval/adjudications.json` and reported separately from the strict numbers.
- Ruff (static) findings are included in 'full pipeline', which is how users experience the tool.
