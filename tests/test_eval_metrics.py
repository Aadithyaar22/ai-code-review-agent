"""The benchmark's scoring code must itself be correct, or every number it prints is meaningless."""

import pytest

from eval.cases import CASES
from eval.metrics import aggregate, filter_sev, locate, recall_by_bug_category, score_case, wilson

CASE = {"id": "c1", "lang": "python", "file": "a.py", "code": "a = 1\nb = eval(x)\nc = 3\nd = 4\ne = 5\n",
        "bugs": [{"at": "eval(", "end": None, "cat": "security", "what": "eval"}]}
CLEAN = {"id": "c2", "lang": "python", "file": "b.py", "code": "x = 1\n", "bugs": []}


def F(s, e=None, sev="high", cat="security", title="t", source="llm"):
    return {"line_start": s, "line_end": e or s, "severity": sev, "category": cat, "title": title, "source": source}


def test_every_benchmark_label_resolves_and_ids_are_unique():
    assert len({c["id"] for c in CASES}) == len(CASES)
    for c in CASES:
        spans = locate(c)
        assert all(1 <= b["start"] <= b["end_line"] <= len(c["code"].splitlines()) for b in spans)
    assert any(not c["bugs"] for c in CASES) and any(c["bugs"] for c in CASES)


def test_locate_and_tolerance():
    assert locate(CASE)[0]["start"] == 2
    assert score_case(CASE, [F(2)])["found"]            # exact
    assert score_case(CASE, [F(1)])["found"]            # ±1 tolerance
    assert score_case(CASE, [F(3)])["found"]
    assert not score_case(CASE, [F(4)])["found"]        # too far
    assert score_case(CASE, [F(5, 5)])["fp"]


def test_a_wide_finding_span_that_contains_the_bug_matches():
    assert score_case(CASE, [F(1, 5)])["found"]


def test_precision_recall_counts():
    s = score_case(CASE, [F(2), F(2, title="dup"), F(5, title="noise")])
    assert (len(s["tp"]), len(s["fp"]), len(s["found"]), len(s["missed"])) == (2, 1, 1, 0)
    a = aggregate([s])
    assert a["precision"] == pytest.approx(2 / 3) and a["recall"] == 1.0
    assert a["f1"] == pytest.approx(2 * (2 / 3) * 1 / (2 / 3 + 1))


def test_missed_bug_and_no_findings():
    a = aggregate([score_case(CASE, [])])
    assert a["recall"] == 0.0 and a["precision"] is None and a["files"]["fn"] == 1


def test_clean_file_false_alarm_is_counted():
    scored = [score_case(CLEAN, [F(1)]), score_case(CASE, [F(2)])]
    a = aggregate(scored)
    assert a["files"] == {**a["files"], "buggy": 1, "clean": 1, "tp": 1, "fn": 0, "fp": 1, "tn": 0}
    assert a["files"]["fpr"] == 1.0 and a["files"]["accuracy"] == 0.5


def test_severity_filter():
    fs = [F(2, sev="low"), F(2, sev="critical")]
    assert len(filter_sev(fs, "medium")) == 1 and len(filter_sev(fs, None)) == 2 and filter_sev(fs, "low") == fs


def test_category_agreement():
    s = score_case(CASE, [F(2, cat="bug"), F(2, cat="security")])
    assert aggregate([s])["category_agreement"] == 0.5


def test_adjudicated_false_positive_counts_as_correct_only_when_asked():
    s = score_case(CLEAN, [F(1, title="real issue")], adjudicated={"c2::real issue"})
    assert not s["fp"] and len(s["valid_extra"]) == 1
    assert aggregate([s])["precision"] == 0.0
    assert aggregate([s], count_valid_extra=True)["precision"] == 1.0


def test_wilson_interval_properties():
    lo, hi = wilson(8, 10)
    assert lo < 0.8 < hi and 0 <= lo and hi <= 1
    assert wilson(0, 0) == (0.0, 0.0)
    assert wilson(10, 10)[1] == 1.0 and wilson(10, 10)[0] < 1.0
    assert wilson(50, 100)[1] - wilson(50, 100)[0] < wilson(5, 10)[1] - wilson(5, 10)[0]  # more data -> tighter


def test_recall_by_category():
    s = score_case(CASE, [F(2)])
    assert recall_by_bug_category([s]) == {"security": {"found": 1, "bugs": 1, "recall": 1.0, "ci": wilson(1, 1)}}
