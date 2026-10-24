from datetime import UTC, datetime, timedelta

import pytest

from bellhop.domain import (
    Call,
    CallStatus,
    InvalidTransition,
    Urgency,
)

T0 = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)


def make_call(**kw) -> Call:
    return Call(id="c1", room="12", resident_id="r1", created_at=T0, **kw)


def test_new_call_is_ringing_and_unscored():
    call = make_call()
    assert call.status is CallStatus.RINGING
    assert call.urgency is None
    assert call.needs_nurse is False


def test_happy_path_robot_resolves_call():
    call = make_call()
    call.transition(CallStatus.ASSIGNED, T0 + timedelta(seconds=2))
    call.transition(CallStatus.ROBOT_EN_ROUTE, T0 + timedelta(seconds=3))
    call.transition(CallStatus.IN_VISIT, T0 + timedelta(seconds=40))
    call.transition(CallStatus.RESOLVED, T0 + timedelta(minutes=3))
    assert call.status is CallStatus.RESOLVED
    assert call.first_response_at == T0 + timedelta(seconds=40)
    assert call.resolved_at == T0 + timedelta(minutes=3)


def test_invalid_transition_raises_and_leaves_state_untouched():
    call = make_call()
    with pytest.raises(InvalidTransition):
        call.transition(CallStatus.RESOLVED, T0)
    assert call.status is CallStatus.RINGING


def test_closed_is_terminal():
    call = make_call()
    call.transition(CallStatus.ASSIGNED, T0)
    call.transition(CallStatus.RESOLVED, T0)
    call.transition(CallStatus.CLOSED, T0)
    with pytest.raises(InvalidTransition):
        call.transition(CallStatus.ASSIGNED, T0)


def test_escalation_is_allowed_from_any_open_state():
    for path in ([], [CallStatus.ASSIGNED], [CallStatus.ASSIGNED, CallStatus.IN_VISIT]):
        call = make_call()
        for step in path:
            call.transition(step, T0)
        call.transition(CallStatus.ESCALATED, T0)
        assert call.status is CallStatus.ESCALATED


def test_score_sets_urgency_category_and_needs_nurse():
    call = make_call()
    call.score(Urgency.NURSE_SOON, "pain")
    assert call.urgency is Urgency.NURSE_SOON
    assert call.category == "pain"
    assert call.needs_nurse is True


def test_score_never_lowers_urgency_once_raised():
    call = make_call()
    call.score(Urgency.EMERGENCY, "fall")
    call.score(Urgency.CHAT, "chat")
    assert call.urgency is Urgency.EMERGENCY
    assert call.category == "fall"


def test_add_turn_appends_to_transcript_in_order():
    call = make_call()
    call.add_turn("resident", "My hip aches", T0)
    call.add_turn("robot", "Where does it hurt?", T0)
    assert [t.speaker for t in call.transcript] == ["resident", "robot"]


def test_response_seconds_none_until_visit_starts():
    call = make_call()
    assert call.response_seconds is None
    call.transition(CallStatus.ASSIGNED, T0)
    call.transition(CallStatus.IN_VISIT, T0 + timedelta(seconds=90))
    assert call.response_seconds == 90
