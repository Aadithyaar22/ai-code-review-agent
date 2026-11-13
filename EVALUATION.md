# Evaluation — how accurate are the findings?

Benchmark: **58 labeled snippets** (37 with known defects, 21 clean/decoy), **38 labeled bugs**, 6 languages. Model: `phi4`. Reproduce: `python eval/run_eval.py`.

## Headline

| Metric (full pipeline, findings ≥ medium) | Value | 95% CI |
|---|---|---|
| **Precision** (findings that are real) | **62.3%** (33/53) | [49–74] |
| **Recall** (labeled bugs found) | **86.8%** (33/38) | [73–94] |
| **F1** | **72.5%** | |
| File-level accuracy (buggy vs clean) | 75.9% | |
| False-positive rate on clean files | 61.9% (13/21) | |
| Category agreement on matched findings | 93.9% | |

## All variants

| Variant | Findings | True pos. | Precision [95% CI] | Bugs found | Recall [95% CI] | F1 |
|---|---|---|---|---|---|---|
| Full pipeline (≥ low) | 57 | 34 | 59.6% [47–71] | 34/38 | 89.5% [76–96] | 71.6% |
| Full pipeline (≥ medium) | 53 | 33 | 62.3% [49–74] | 33/38 | 86.8% [73–94] | 72.5% |
| Full pipeline (≥ high) | 32 | 27 | 84.4% [68–93] | 27/38 | 71.1% [55–83] | 77.1% |
| AI findings only, verified (≥ low) | 43 | 23 | 53.5% [39–67] | 23/38 | 60.5% [45–74] | 56.8% |
| Static analysis only (ruff) | 14 | 11 | 78.6% [52–92] | 11/38 | 28.9% [17–45] | 42.3% |
| Raw model output, no verification | 53 | 33 | 62.3% [49–74] | 33/38 | 86.8% [73–94] | 72.5% |
| (lenient) Full pipeline ≥ medium, line overlap only | 53 | 38 | 71.7% [58–82] | 37/38 | 97.4% [87–100] | 82.6% |

**After manual adjudication** (1 'false positives' were real issues the labels missed — see below):

| Variant | Findings | Correct | Precision [95% CI] | Bugs found | Recall [95% CI] | F1 |
|---|---|---|---|---|---|---|
| Full pipeline (≥ low) | 57 | 35 | 61.4% [48–73] | 34/38 | 89.5% [76–96] | 72.8% |
| Full pipeline (≥ medium) | 53 | 34 | 64.2% [51–76] | 33/38 | 86.8% [73–94] | 73.8% |

## What the verification layer buys you

'Raw model output' is what the LLM said before the pipeline checks the quoted evidence, corrects line numbers, drops low-confidence/noise findings and merges with static analysis.

- Precision: raw **62.3%** → pipeline **59.6%**
- Recall: raw **86.8%** → pipeline **89.5%**
- Findings dropped by the evidence check across the benchmark: none
- **The evidence check dropped nothing here.** On short snippets the model quotes code accurately, so this benchmark does not exercise that feature. Its value (catching invented quotes in large files) is **not measured** by these numbers.

## File-level confusion (full pipeline, ≥ medium)

| | Flagged | Not flagged |
|---|---|---|
| **Buggy files** (37) | 36 (caught) | 1 (missed) |
| **Clean files** (21) | 13 (false alarm) | 8 (correct) |

## By language (full pipeline, ≥ medium)

| Language | Cases | Findings | Precision | Recall | F1 |
|---|---|---|---|---|---|
| bash | 2 | 2 | 50.0% | 100.0% | 66.7% |
| c | 4 | 4 | 75.0% | 100.0% | 85.7% |
| go | 5 | 4 | 75.0% | 100.0% | 85.7% |
| java | 3 | 3 | 66.7% | 100.0% | 80.0% |
| javascript | 11 | 9 | 66.7% | 85.7% | 75.0% |
| python | 33 | 31 | 58.1% | 81.8% | 67.9% |

## Recall by defect type (full pipeline, ≥ low)

| Type | Found | Recall [95% CI] |
|---|---|---|
| bug | 14/17 | 82.4% [59–94] |
| performance | 1/2 | 50.0% [9–91] |
| security | 19/19 | 100.0% [83–100] |

## Precision by severity (full pipeline)

| Severity | Findings | Correct | Precision [95% CI] |
|---|---|---|---|
| critical | 15 | 12 | 80.0% [55–93] |
| high | 17 | 15 | 88.2% [66–97] |
| medium | 21 | 6 | 28.6% [14–50] |
| low | 4 | 1 | 25.0% [5–70] |

## Does the model's own confidence help? (full pipeline, AI findings filtered by confidence)

Static-analysis findings are always kept. Tuning a threshold on the same data it is measured on overstates the gain; this table shows the trend, it is not a validated setting.

| Min AI confidence | Findings | Precision | Recall | F1 |
|---|---|---|---|---|
| ≥ 0.00 | 57 | 59.6% | 89.5% | 71.6% |
| ≥ 0.70 | 57 | 59.6% | 89.5% | 71.6% |
| ≥ 0.80 | 57 | 59.6% | 89.5% | 71.6% |
| ≥ 0.90 | 57 | 59.6% | 89.5% | 71.6% |
| ≥ 0.95 | 49 | 69.4% | 89.5% | 78.2% |
| ≥ 1.00 | 22 | 86.4% | 50.0% | 63.3% |

## Missed bugs (false negatives, ≥ low)

- `py_resource_leak` line 2: file handle never closed
- `py_n_plus_one` line 4: N+1 queries inside a loop
- `py_bare_except` line 8: bare except silently swallows every error
- `js_missing_await` line 2: missing await: res is a Promise

## False positives (full pipeline, ≥ medium)

- `py_resource_leak` line 2 [medium/bug, llm] File I/O exception handling missing 
- `py_n_plus_one` line 5 [medium/bug, llm] Potential KeyError if no rows are returned 
- `py_bare_except` line 6 [medium/bug, llm] Unhandled exceptions in file operations 
- `py_bare_except` line 7 [medium/bug, llm] Potential JSONDecodeError 
- `js_missing_await` line 2 [medium/bug, llm] Unhandled fetch errors 
- `js_missing_await` line 3 [medium/bug, llm] Potential JSON parsing error 
- `clean_py_subprocess_list` line 5 [medium/bug, llm] Unhandled exceptions 
- `clean_py_with_open` line 6 [medium/bug, llm] Unhandled JSONDecodeError 
- `clean_py_env_secret` line 7 [critical/bug, llm] Incorrect token verification 
- `clean_py_env_secret` line 6 [medium/bug, llm] Environment variable usage 
- `clean_py_average_guard` line 4 [medium/bug, llm] Potential runtime error with non-numeric inputs 
- `clean_py_safe_path` line 11 [critical/security, llm] Path traversal vulnerability 
- `clean_py_literal_eval` line 5 [medium/bug, llm] Potential crash on malformed input 
- `clean_py_none_default` line 2 [medium/maintainability, llm] Mutable default argument 
- `clean_py_retry` line 4 [medium/bug, llm] Limited exception handling 
- `clean_js_textcontent` line 2 [high/security, llm] Potential XSS vulnerability 
- `clean_go_error_handled` line 9 [medium/bug, llm] File existence and content check 
- `clean_java_prepared` line 10 [medium/bug, llm] Potential Resource Leak adjudicated: valid
- `clean_c_snprintf` line 5 [critical/bug, llm] Buffer Overflow Vulnerability 
- `clean_sh_quoted_rm` line 4 [high/bug, llm] Potential unintended deletion due to symbolic links 

## Speed

Median 34s per file, total 31.5 min on a local model (cached results report ~0s). Results are cached, so unchanged code is instant on re-run.

## How to read this — and its limits

- The benchmark is **small and synthetic**, written by the project author: short single-purpose snippets with 1–2 obvious defects. Real repositories are larger and messier, so expect lower recall and more false positives there. Treat the numbers as a regression baseline and a relative comparison between variants, not as a promise about production accuracy.
- **Matching is strict:** a finding must touch the labeled line (±1) **and** describe the right kind of defect (keyword check in `eval/cases.py`). A first version used line overlap only; it wrongly credited findings like "Potential KeyError" for an N+1 bug and overstated recall (see the *lenient* row).
- The keyword patterns and labels were written by the same person who built the tool, which can bias results in its favour.
- 95% intervals are Wilson score intervals; with this sample size they are wide. Differences of a few points are noise.
- Category is scored separately (category agreement).
- Labels come from the author. The harness lists every false positive so each can be judged by hand; judgements are recorded in `eval/adjudications.json` and reported separately from the strict numbers.
- Ruff (static) findings are included in 'full pipeline', which is how users experience the tool.
