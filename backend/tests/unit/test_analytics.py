from datetime import timedelta

import pytest

from bellhop.domain import Call, Urgency, Visit
from bellhop.services.analytics import Analytics
from tests.unit.wpc_fakes import DictRepo, VisitRepo


@pytest.fixture
def env(clock):
    calls, visits = DictRepo(), VisitRepo()

    def add_call(cid, room="1", category=None, response=None, hours=0):
        c = Call(
            id=cid,
            room=room,
            category=category,
            created_at=clock.now() + timedelta(hours=hours),
        )
        if response is not None:
            c.first_response_at = c.created_at + timedelta(seconds=response)
        calls.save(c)

    def add_visit(cid, by_robot=True, override=None):
        visits.save(
            Visit(
                id=f"v_{cid}",
                call_id=cid,
                resident_id=None,
                robot_id=None,
                resolved_by_robot=by_robot,
                nurse_urgency_override=override,
            )
        )

    return calls, visits, add_call, add_visit


def test_resolved_without_nurse_counts_robot_resolutions(env):
    calls, visits, add_call, add_visit = env
    for cid, robot in [("a", True), ("b", True), ("c", False)]:
        add_call(cid)
        add_visit(cid, robot)
    assert Analytics(calls, visits).resolved_without_nurse() == 2


def test_minutes_saved_defaults_to_four_per_call(env):
    calls, visits, add_call, add_visit = env
    for cid in "ab":
        add_call(cid)
        add_visit(cid)
    a = Analytics(calls, visits)
    assert a.minutes_saved() == 8.0
    assert a.minutes_saved(minutes_per_call=5) == 10.0


def test_share_answered_within_counts_only_calls_with_response(env):
    calls, visits, add_call, _ = env
    add_call("fast", response=60)
    add_call("slow", response=1200)
    add_call("never")
    assert Analytics(calls, visits).share_answered_within(600) == 0.5


def test_share_answered_within_is_zero_without_responses(env):
    calls, visits, add_call, _ = env
    add_call("never")
    assert Analytics(calls, visits).share_answered_within() == 0.0


def test_calls_by_room_category_and_hour(env):
    calls, visits, add_call, _ = env
    add_call("a", room="1", category="tea", hours=0)
    add_call("b", room="1", category="pain", hours=1)
    add_call("c", room="2", category="tea", hours=1)
    an = Analytics(calls, visits)
    assert an.calls_by("room") == {"1": 2, "2": 1}
    assert an.calls_by("category") == {"tea": 2, "pain": 1}
    assert an.calls_by("hour") == {9: 1, 10: 2}


def test_calls_by_unknown_key_raises(env):
    calls, visits, *_ = env
    with pytest.raises(ValueError):
        Analytics(calls, visits).calls_by("colour")


def test_labelled_examples_only_where_nurse_overrode(env):
    calls, visits, add_call, add_visit = env
    add_call("a")
    add_call("b")
    c = calls.get("a")
    c.score(Urgency.ROUTINE, "pain")
    c.add_turn("resident", "my chest hurts", c.created_at)
    calls.save(c)
    add_visit("a", override=Urgency.EMERGENCY)
    add_visit("b")
    assert Analytics(calls, visits).labelled_examples() == [
        {
            "call_id": "a",
            "transcript": [{"speaker": "resident", "text": "my chest hurts"}],
            "robot_urgency": 2,
            "nurse_urgency": 4,
        }
    ]
