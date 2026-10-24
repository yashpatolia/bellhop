"""Property tests for the invariants the product depends on."""

from datetime import UTC, datetime

from hypothesis import given
from hypothesis import strategies as st

from bellhop.domain import Call, CallStatus, InvalidTransition, Urgency

T0 = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)
urgencies = st.sampled_from(list(Urgency))


def new_call() -> Call:
    return Call(id="c", room="12", created_at=T0)


@given(st.lists(urgencies, min_size=1, max_size=20))
def test_urgency_is_the_max_ever_scored(scores):
    call = new_call()
    for u in scores:
        call.score(u, "x")
    assert call.urgency == max(scores)


@given(st.lists(st.sampled_from(list(CallStatus)), max_size=30))
def test_random_transitions_never_corrupt_state_and_closed_is_terminal(steps):
    call = new_call()
    for to in steps:
        before = call.status
        try:
            call.transition(to, T0)
        except InvalidTransition:
            assert call.status is before
        if before is CallStatus.CLOSED:
            assert call.status is CallStatus.CLOSED
