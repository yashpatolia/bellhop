import pytest

from bellhop.domain import Call, Urgency
from bellhop.domain.events import CallResolved
from bellhop.services.feedback import FeedbackService
from tests.unit.wpc_fakes import DictRepo, SyncBus, VisitRepo


@pytest.fixture
def svc(clock, ids):
    calls, visits, bus = DictRepo(), VisitRepo(), SyncBus()
    calls.save(
        Call(
            id="c1",
            room="12",
            resident_id="r1",
            assigned_to=["nurse_1", "unit_7"],
            robot_id="robot_1",
            created_at=clock.now(),
        )
    )
    s = FeedbackService(visits, calls, bus, ids)
    s.visits, s.bus = visits, bus
    return s


def test_call_resolved_creates_visit_from_event(svc):
    svc.bus.publish(CallResolved("c1", by_robot=True))
    v = svc.visits.for_call("c1")
    assert (v.resident_id, v.robot_id, v.resolved_by_robot) == ("r1", "robot_1", True)


def test_resolved_by_nurse_is_recorded(svc):
    svc.bus.publish(CallResolved("c1", by_robot=False))
    assert svc.visits.for_call("c1").resolved_by_robot is False


def test_duplicate_resolution_creates_one_visit(svc):
    svc.record_resolution("c1", "robot_1")
    svc.record_resolution("c1", "robot_1")
    assert len(svc.visits.list_all()) == 1


def test_unknown_call_creates_no_visit(svc):
    svc.bus.publish(CallResolved("nope", by_robot=True))
    assert svc.visits.list_all() == []


def test_rate_stores_rating_and_mood(svc):
    svc.record_resolution("c1", "robot_1")
    svc.rate("c1", 5, mood="happy")
    v = svc.visits.for_call("c1")
    assert (v.rating, v.mood) == (5, "happy")


@pytest.mark.parametrize("bad", [0, 6, -1])
def test_rate_rejects_out_of_range(svc, bad):
    svc.record_resolution("c1", "robot_1")
    with pytest.raises(ValueError):
        svc.rate("c1", bad)


def test_rate_without_visit_raises(svc):
    with pytest.raises(LookupError):
        svc.rate("c1", 3)


def test_nurse_override_is_stored(svc):
    svc.record_resolution("c1", "robot_1")
    svc.nurse_override("c1", Urgency.EMERGENCY)
    assert svc.visits.for_call("c1").nurse_urgency_override == Urgency.EMERGENCY
