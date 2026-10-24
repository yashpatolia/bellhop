"""Deterministic triage safety net: keyword floor + apply_floor + TriageGuard."""

from __future__ import annotations

import pytest

from bellhop.domain.models import Urgency
from bellhop.labelled.cases import CASES
from bellhop.services.triage_guard import (
    Decision,
    FloorResult,
    TriageGuard,
    apply_floor,
    keyword_floor,
)


def _r(text: str) -> list[tuple[str, str]]:
    return [("resident", text)]


# ---- keyword floor: labelled set regression --------------------------------


def test_never_under_escalates_labelled_emergencies() -> None:
    emergencies = [c for c in CASES if c.expected_urgency == 4]
    assert len(emergencies) >= 7
    for case in emergencies:
        floor = keyword_floor(case.transcript)
        assert floor.urgency == Urgency.EMERGENCY, (case.id, floor)
        assert floor.matched


def test_urgent_labelled_cases_floored_to_at_least_three() -> None:
    urgent = [c for c in CASES if c.expected_urgency == 3]
    hits = [c.id for c in urgent if (keyword_floor(c.transcript).urgency or 0) >= 3]
    assert hits == [c.id for c in urgent]  # all 3s floored


def test_labelled_low_urgency_cases_do_not_trigger_floor() -> None:
    for case in CASES:
        if case.expected_urgency <= 2:
            assert keyword_floor(case.transcript).urgency is None, case.id


# ---- keyword floor: parametrised behaviour ---------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "I have fallen and I can't get up",
        "I fell in the bathroom",
        "I have chest pain",
        "My chest feels tight",
        "I can't breathe",
        "I am choking",
        "There is blood, I am bleeding badly",
        "She is unresponsive",
        "My face is drooping and my words are slurred",
        "Probably nothing but my chest feels tight",
        "Sorry to bother you, but I think I might have fallen",
        "I'm not sure if I fell, I can't stand up",
        "Help! Help! Help me please!",
    ],
)
def test_emergency_phrases(text: str) -> None:
    assert keyword_floor(_r(text)).urgency == Urgency.EMERGENCY


@pytest.mark.parametrize(
    "text",
    [
        "I feel dizzy",
        "I forgot if I took my pills",
        "My knee hurts",
        "I have a headache",
        "Something doesn't feel right",
        "I feel lightheaded",
    ],
)
def test_urgent_phrases(text: str) -> None:
    assert keyword_floor(_r(text)).urgency == Urgency.NURSE_SOON


@pytest.mark.parametrize(
    "text",
    [
        "I did not fall",
        "I didn't fall, I sat down",
        "I have no pain at all",
        "I am not in pain",
        "No chest pain, I'm fine",
        "I'm not dizzy",
        "I am not bleeding",
        "Where am I? Where am I?",
        "Has my husband come yet? Has my husband come yet?",
        "I am not sure what day it is",
        "Could I have some tea please",
        "I need help getting to the bathroom",
        "My blood pressure pills are on the table, thank you",
    ],
)
def test_negation_and_dementia_do_not_trigger(text: str) -> None:
    assert keyword_floor(_r(text)).urgency is None


def test_ignores_non_resident_turns() -> None:
    transcript = [
        ("robot", "Have you fallen? Do you have chest pain? Are you bleeding?"),
        ("nurse", "I cannot breathe in this heat"),
        ("resident", "No, I am fine, just a bit bored."),
    ]
    assert keyword_floor(transcript) == FloorResult(None, [])


def test_empty_transcript() -> None:
    assert keyword_floor([]) == FloorResult(None, [])


def test_help_repeated_across_turns() -> None:
    t = [("resident", "Help!"), ("robot", "ok"), ("resident", "Help me!"), ("resident", "Help")]
    assert keyword_floor(t).urgency == Urgency.EMERGENCY


def test_emergency_beats_urgent_and_lists_matches() -> None:
    f = keyword_floor(_r("I feel dizzy and I have fallen"))
    assert f.urgency == Urgency.EMERGENCY
    assert len(f.matched) >= 2


# ---- apply_floor -----------------------------------------------------------

NO_FLOOR = FloorResult(None, [])
FLOOR4 = FloorResult(Urgency.EMERGENCY, ["can't get up"])
FLOOR3 = FloorResult(Urgency.NURSE_SOON, ["dizzy"])


def test_model_failed_defaults_to_nurse_soon() -> None:
    d = apply_floor(None, None, NO_FLOOR)
    assert d.urgency == Urgency.NURSE_SOON
    assert d.reason == "model unavailable, defaulted to nurse soon"


def test_model_failed_but_floor_emergency() -> None:
    d = apply_floor(None, None, FLOOR4)
    assert d.urgency == Urgency.EMERGENCY
    assert d.reason == "keyword: can't get up"


def test_floor_raises_model() -> None:
    d = apply_floor(Urgency.CHAT, 0.95, FLOOR4)
    assert d == Decision(Urgency.EMERGENCY, "keyword: can't get up")


def test_floor_never_lowers_model() -> None:
    assert apply_floor(Urgency.EMERGENCY, 0.9, FLOOR3).urgency == Urgency.EMERGENCY


def test_low_confidence_bumps_one_level_and_caps() -> None:
    d = apply_floor(Urgency.ROUTINE, 0.4, NO_FLOOR)
    assert d.urgency == Urgency.NURSE_SOON
    assert "low" in d.reason and "confidence" in d.reason
    assert apply_floor(Urgency.EMERGENCY, 0.1, NO_FLOOR).urgency == Urgency.EMERGENCY


def test_confidence_at_threshold_not_bumped() -> None:
    assert apply_floor(Urgency.ROUTINE, 0.6, NO_FLOOR).urgency == Urgency.ROUTINE


def test_custom_low_confidence_threshold() -> None:
    assert apply_floor(Urgency.CHAT, 0.7, NO_FLOOR, low_confidence=0.8).urgency == Urgency.ROUTINE


def test_none_confidence_is_not_bumped() -> None:
    assert apply_floor(Urgency.CHAT, None, NO_FLOOR).urgency == Urgency.CHAT


def test_reason_is_short_string() -> None:
    d = apply_floor(Urgency.ROUTINE, 0.9, NO_FLOOR)
    assert d.urgency == Urgency.ROUTINE
    assert d.reason and len(d.reason) < 120


# ---- properties ------------------------------------------------------------

MODELS = [None, *Urgency]
CONFS = [None, 0.0, 0.3, 0.6, 0.99]
FLOORS = [NO_FLOOR, FLOOR3, FLOOR4]


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("conf", CONFS)
@pytest.mark.parametrize("floor", FLOORS)
def test_final_never_below_model_or_floor(
    model: Urgency | None, conf: float | None, floor: FloorResult
) -> None:
    d = apply_floor(model, conf, floor)
    assert isinstance(d.urgency, Urgency)
    if model is not None:
        assert d.urgency >= model
    if floor.urgency is not None:
        assert d.urgency >= floor.urgency
    assert d.urgency <= Urgency.EMERGENCY
    assert d.reason


# ---- TriageGuard -----------------------------------------------------------


def test_guard_decide_integrates() -> None:
    g = TriageGuard()
    d = g.decide(_r("I have fallen and I cannot get up"), Urgency.CHAT, 0.9)
    assert d.urgency == Urgency.EMERGENCY and d.reason.startswith("keyword:")
    assert g.decide(_r("Lovely day"), None, None).urgency == Urgency.NURSE_SOON
    assert g.decide(_r("Lovely day"), Urgency.CHAT, 0.9).urgency == Urgency.CHAT


def test_guard_labelled_set_never_under_escalates() -> None:
    g = TriageGuard()
    for case in CASES:
        # worst case: model says CHAT with full confidence
        d = g.decide(case.transcript, Urgency.CHAT, 1.0)
        if case.expected_urgency == 4:
            assert d.urgency == Urgency.EMERGENCY, case.id
        if case.expected_urgency == 3:
            assert d.urgency >= Urgency.NURSE_SOON, case.id
