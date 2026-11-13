# {TITLE}

Benchmark: **25 labeled snippets** (12 with known defects, 13 clean/decoy), **12 labeled bugs**, 6 languages. Model: `phi4`. Reproduce: `python eval/run_eval.py`.

## Headline

| Metric (full pipeline, findings ≥ medium) | Value | 95% CI |
|---|---|---|
| **Precision** (findings that are real) | **58.8%** (10/17) | [36–78] |
| **Recall** (labeled bugs found) | **83.3%** (10/12) | [55–95] |
| **F1** | **69.0%** | |
| File-level accuracy (buggy vs clean) | 72.0% | |
| False-positive rate on clean files | 46.2% (6/13) | |
| Category agreement on matched findings | 100.0% | |

## All variants

| Variant | Findings | True pos. | Precision [95% CI] | Bugs found | Recall [95% CI] | F1 |
|---|---|---|---|---|---|---|
| Full pipeline (≥ low) | 18 | 11 | 61.1% [39–80] | 10/12 | 83.3% [55–95] | 70.5% |
| Full pipeline (≥ medium) | 17 | 10 | 58.8% [36–78] | 10/12 | 83.3% [55–95] | 69.0% |
| Full pipeline (≥ high) | 11 | 7 | 63.6% [35–85] | 7/12 | 58.3% [32–81] | 60.9% |
| AI findings only, verified (≥ low) | 13 | 7 | 53.8% [29–77] | 7/12 | 58.3% [32–81] | 56.0% |
| Static analysis only (ruff) | 5 | 4 | 80.0% [38–96] | 4/12 | 33.3% [14–61] | 47.1% |
| Raw model output, no verification | 19 | 10 | 52.6% [32–73] | 10/12 | 83.3% [55–95] | 64.5% |
| (lenient) Full pipeline ≥ medium, line overlap only | 17 | 10 | 58.8% [36–78] | 10/12 | 83.3% [55–95] | 69.0% |

**After manual adjudication** (1 'false positives' were real issues the labels missed — see below):

| Variant | Findings | Correct | Precision [95% CI] | Bugs found | Recall [95% CI] | F1 |
|---|---|---|---|---|---|---|
| Full pipeline (≥ low) | 18 | 12 | 66.7% [44–84] | 10/12 | 83.3% [55–95] | 74.1% |
| Full pipeline (≥ medium) | 17 | 11 | 64.7% [41–83] | 10/12 | 83.3% [55–95] | 72.8% |

## What the verification layer buys you

'Raw model output' is what the LLM said before the pipeline checks the quoted evidence, corrects line numbers, drops low-confidence/noise findings and merges with static analysis.

- Precision: raw **52.6%** → pipeline **61.1%**
- Recall: raw **83.3%** → pipeline **83.3%**
- Findings dropped by the evidence check across the benchmark: {'dropped_hallucinated': 1, 'dropped_challenged': 2}

## File-level confusion (full pipeline, ≥ medium)

| | Flagged | Not flagged |
|---|---|---|
| **Buggy files** (12) | 11 (caught) | 1 (missed) |
| **Clean files** (13) | 6 (false alarm) | 7 (correct) |

## By language (full pipeline, ≥ medium)

| Language | Cases | Findings | Precision | Recall | F1 |
|---|---|---|---|---|---|
| c | 2 | 1 | 100.0% | 100.0% | 100.0% |
| go | 2 | 1 | 0.0% | 0.0% | 0.0% |
| java | 2 | 1 | 100.0% | 100.0% | 100.0% |
| javascript | 5 | 4 | 50.0% | 66.7% | 57.1% |
| python | 14 | 10 | 60.0% | 100.0% | 75.0% |

## Recall by defect type (full pipeline, ≥ low)

| Type | Found | Recall [95% CI] |
|---|---|---|
| bug | 5/6 | 83.3% [44–97] |
| security | 5/6 | 83.3% [44–97] |

## Precision by severity (full pipeline)

| Severity | Findings | Correct | Precision [95% CI] |
|---|---|---|---|
| critical | 7 | 5 | 71.4% [36–92] |
| high | 4 | 2 | 50.0% [15–85] |
| medium | 6 | 3 | 50.0% [19–81] |
| low | 1 | 1 | 100.0% [21–100] |

## Does the model's own confidence help? (full pipeline, AI findings filtered by confidence)

Static-analysis findings are always kept. Tuning a threshold on the same data it is measured on overstates the gain; this table shows the trend, it is not a validated setting.

| Min AI confidence | Findings | Precision | Recall | F1 |
|---|---|---|---|---|
| ≥ 0.00 | 18 | 61.1% | 83.3% | 70.5% |
| ≥ 0.70 | 18 | 61.1% | 83.3% | 70.5% |
| ≥ 0.80 | 18 | 61.1% | 83.3% | 70.5% |
| ≥ 0.90 | 17 | 64.7% | 83.3% | 72.8% |
| ≥ 0.95 | 16 | 68.8% | 83.3% | 75.3% |
| ≥ 1.00 | 8 | 75.0% | 50.0% | 60.0% |

## Missed bugs (false negatives, ≥ low)

- `h_js_proto_pollution` line 4: prototype pollution via __proto__ keys
- `h_go_nil_map` line 6: write to nil map panics

## False positives (full pipeline, ≥ medium)

- `h_go_nil_map` line 4 [critical/bug, llm] Uninitialized map adjudicated: valid
- `h_clean_py_in_clause` line 3 [high/security, ruff] S608: Possible SQL injection vector through string-based query construction 
- `h_clean_py_allowlist_redirect` line 11 [high/security, llm] Open Redirect Vulnerability 
- `h_clean_py_pbkdf2` line 8 [medium/security, llm] Insecure storage of salt and digest 
- `h_clean_py_stream_lines` line 2 [medium/bug, llm] Missing exception handling for file operations 
- `h_clean_js_exec_file` line 4 [critical/security, llm] Directory Traversal 
- `h_clean_js_let_closure` line 3 [medium/bug, llm] Closure captures the final value of `i` 

## Speed

Median 46s per file, total 17.1 min on a local model (cached results report ~0s). Results are cached, so unchanged code is instant on re-run.

## How to read this — and its limits

- The benchmark is **small and synthetic**, written by the project author: short single-purpose snippets with 1–2 obvious defects. Real repositories are larger and messier, so expect lower recall and more false positives there. Treat the numbers as a regression baseline and a relative comparison between variants, not as a promise about production accuracy.
- **Matching is strict:** a finding must touch the labeled line (±1) **and** describe the right kind of defect (keyword check in `eval/cases.py`). A first version used line overlap only; it wrongly credited findings like "Potential KeyError" for an N+1 bug and overstated recall (see the *lenient* row).
- The keyword patterns and labels were written by the same person who built the tool, which can bias results in its favour.
- 95% intervals are Wilson score intervals; with this sample size they are wide. Differences of a few points are noise.
- Category is scored separately (category agreement).
- Labels come from the author. The harness lists every false positive so each can be judged by hand; judgements are recorded in `eval/adjudications.json` and reported separately from the strict numbers.
- Ruff (static) findings are included in 'full pipeline', which is how users experience the tool.
