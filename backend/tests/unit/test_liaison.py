import pytest

from bellhop.adapters.notifiers import RecordingNotifier
from bellhop.domain import Call, Nurse, Urgency
from bellhop.domain.events import AlertRaised, CallScored
from bellhop.services.liaison import Liaison
from tests.unit.wpc_fakes import AlertRepo, DictRepo, SyncBus


@pytest.fixture
def world(clock, ids):
    calls, nurses, alerts = DictRepo(), DictRepo(), AlertRepo()
    notifier, bus = RecordingNotifier(), SyncBus()
    Liaison(calls, nurses, alerts, notifier, bus, clock, ids)
    calls.save(Call(id="c1", room="12", created_at=clock.now()))
    nurses.save(Nurse(id="n1", name="Ann", open_tasks=2))
    nurses.save(Nurse(id="n2", name="Bo", open_tasks=0))

    class W:
        pass

    w = W()
    w.calls, w.nurses, w.alerts, w.notifier, w.bus, w.clock = (
        calls,
        nurses,
        alerts,
        notifier,
        bus,
        clock,
    )

    def score(level: Urgency) -> None:
        call = calls.get("c1")
        call.score(level, "pain")
        calls.save(call)
        bus.publish(CallScored("c1", level, "pain"))

    w.score = score
    return w


def test_urgency_three_alerts_least_loaded_nurse_and_bumps_load(world):
    world.score(Urgency.NURSE_SOON)
    [alert] = world.notifier.sent
    assert alert.nurse_id == "n2"
    assert world.nurses.get("n2").open_tasks == 1
    assert world.alerts.for_call("c1") == [alert]


def test_urgency_three_publishes_alert_raised(world):
    world.score(Urgency.NURSE_SOON)
    raised = [e for e in world.bus.published if isinstance(e, AlertRaised)]
    assert [(e.call_id, e.level) for e in raised] == [("c1", Urgency.NURSE_SOON)]


def test_urgency_four_broadcasts_immediately(world):
    world.score(Urgency.EMERGENCY)
    [alert] = world.notifier.sent
    assert alert.nurse_id is None
    assert alert.level == Urgency.EMERGENCY


@pytest.mark.parametrize("level", [Urgency.CHAT, Urgency.ROUTINE])
def test_low_urgency_sends_nothing(world, level):
    world.score(level)
    assert world.notifier.sent == []


def test_same_level_rescore_does_not_duplicate(world):
    world.score(Urgency.NURSE_SOON)
    world.score(Urgency.NURSE_SOON)
    assert len(world.notifier.sent) == 1


def test_three_then_four_sends_new_broadcast(world):
    world.score(Urgency.NURSE_SOON)
    world.score(Urgency.EMERGENCY)
    assert [a.level for a in world.notifier.sent] == [Urgency.NURSE_SOON, Urgency.EMERGENCY]
    assert world.notifier.sent[1].nurse_id is None


def test_no_nurse_on_shift_at_three_broadcasts(world):
    for n in world.nurses.list_all():
        n.on_shift = False
        world.nurses.save(n)
    world.score(Urgency.NURSE_SOON)
    assert world.notifier.sent[0].nurse_id is None


def test_message_uses_call_summary_when_present(world):
    call = world.calls.get("c1")
    call.summary = "Resident reports sore hip since morning"
    world.calls.save(call)
    world.score(Urgency.NURSE_SOON)
    assert "sore hip" in world.notifier.sent[0].message


def test_message_falls_back_to_last_resident_turns(world):
    call = world.calls.get("c1")
    now = world.clock.now()
    call.add_turn("resident", "good morning", now)
    call.add_turn("robot", "hello", now)
    call.add_turn("resident", "my hip hurts", now)
    call.add_turn("resident", "it is getting worse", now)
    world.calls.save(call)
    world.score(Urgency.NURSE_SOON)
    msg = world.notifier.sent[0].message
    assert "my hip hurts" in msg and "getting worse" in msg
    assert "hello" not in msg and "good morning" not in msg


def test_unknown_call_is_ignored(world):
    world.bus.publish(CallScored("nope", Urgency.EMERGENCY, "x"))
    assert world.notifier.sent == []
