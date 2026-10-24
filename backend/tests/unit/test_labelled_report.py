import pytest

from bellhop.labelled.cases import LabelledCase
from bellhop.labelled.report import suggest_escalation_threshold, threshold_report


def case(cid: str, urgency: int) -> LabelledCase:
    return LabelledCase(cid, [("resident", "x")], [], urgency, "cat", "n")


CASES = [case("a", 1), case("b", 1), case("c", 2), case("d", 4)]
# a ok, b over-escalated to 2, c under-escalated to 1, d ok
PRED = {"a": (1, 0.9), "b": (2, 0.8), "c": (1, 0.4), "d": (4, 0.95)}


def test_confusion_matrix():
    r = threshold_report(CASES, PRED)
    assert r.confusion[1][1] == 1
    assert r.confusion[1][2] == 1
    assert r.confusion[2][1] == 1
    assert r.confusion[4][4] == 1
    assert r.confusion[3][3] == 0


def test_precision_and_recall():
    r = threshold_report(CASES, PRED)
    # urgency 1: predicted a,c (2), correct a -> p=0.5; expected a,b, found a -> r=0.5
    assert r.precision[1] == pytest.approx(0.5)
    assert r.recall[1] == pytest.approx(0.5)
    # urgency 2: predicted b only, wrong -> p=0; expected c, missed -> r=0
    assert r.precision[2] == 0.0
    assert r.recall[2] == 0.0
    assert r.precision[4] == 1.0 and r.recall[4] == 1.0
    # urgency 3: never predicted, never expected
    assert r.precision[3] == 0.0 and r.recall[3] == 0.0


def test_under_escalations_reported_separately():
    r = threshold_report(CASES, PRED)
    assert r.under_escalations == ["c"]
    assert r.under_escalation_count == 1
    assert "UNDER-ESCALATIONS: 1" in r.format()
    assert r.format().startswith("UNDER-ESCALATIONS")


def test_no_under_escalations():
    r = threshold_report(CASES, {"a": (1, 1.0), "b": (1, 1.0), "c": (3, 1.0), "d": (4, 1.0)})
    assert r.under_escalation_count == 0
    assert r.suggested_threshold == 0.0


def test_threshold_is_lowest_cutoff_that_fixes_all():
    # c (conf 0.4) must be bumped; lowest cutoff above 0.4 among confidences is 0.8
    assert suggest_escalation_threshold(CASES, PRED) == pytest.approx(0.8)
    assert threshold_report(CASES, PRED).suggested_threshold == pytest.approx(0.8)


def test_threshold_none_when_one_bump_is_not_enough():
    pred = {"a": (1, 0.9), "b": (1, 0.9), "c": (2, 0.9), "d": (2, 0.1)}
    assert suggest_escalation_threshold(CASES, pred) is None
