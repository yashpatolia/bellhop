from collections import Counter

from bellhop.labelled.cases import CASES, LabelledCase


def test_case_count_in_range():
    assert 28 <= len(CASES) <= 34


def test_all_four_urgencies_present():
    assert set(Counter(c.expected_urgency for c in CASES)) == {1, 2, 3, 4}


def test_ids_unique():
    assert len({c.id for c in CASES}) == len(CASES)


def test_cases_are_well_formed():
    for c in CASES:
        assert isinstance(c, LabelledCase)
        assert c.transcript and all(len(t) == 2 for t in c.transcript)
        assert c.expected_category and c.note


def test_hedged_chest_tightness_is_urgency_four():
    hedged = [c for c in CASES if "probably nothing" in " ".join(t for _, t in c.transcript)]
    assert hedged and all(c.expected_urgency == 4 for c in hedged)


def test_negated_fall_is_not_urgency_four():
    negated = [c for c in CASES if "did not fall" in " ".join(t for _, t in c.transcript)]
    assert negated and all(c.expected_urgency < 4 for c in negated)


def test_pure_confusion_never_high_urgency():
    confusion = [c for c in CASES if c.expected_category == "confusion"]
    assert confusion and all(c.expected_urgency <= 2 for c in confusion)
