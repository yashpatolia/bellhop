import pytest

from bellhop.adapters.event_bus import InMemoryEventBus
from bellhop.adapters.memory_store import InMemoryStore
from bellhop.domain import CallStatus, InvalidTransition, Resident, Urgency
from bellhop.domain.events import CallRaised, CallResolved, CallScored, CallUpdated
from bellhop.services.call_service import CallNotFound, CallService


@pytest.fixture
def env(clock, ids):
    store, bus, events = InMemoryStore(), InMemoryEventBus(), []
    for t in (CallRaised, CallScored, CallResolved, CallUpdated):
        bus.subscribe(t, events.append)
    svc = CallService(store.calls, store.residents, bus, clock, ids)
    return svc, store, events


def test_raise_call_creates_ringing_call_and_publishes(env, clock):
    svc, store, events = env
    call = svc.raise_call("12")
    assert call.status is CallStatus.RINGING
    assert call.created_at == clock.now()
    assert store.calls.get(call.id) is not None
    assert events == [CallRaised(call_id=call.id, room="12")]


def test_raise_call_attaches_resident_by_room(env):
    svc, store, _ = env
    store.residents.save(Resident(id="r1", name="Ada", room="12"))
    assert svc.raise_call("12").resident_id == "r1"
    assert svc.raise_call("99").resident_id is None


def test_add_turn_appends_to_transcript_and_publishes_a_live_update(env):
    svc, store, events = env
    call = svc.raise_call("12")
    svc.add_turn(call.id, "resident", "I'd like tea")
    turns = store.calls.get(call.id).transcript
    assert [(t.speaker, t.text) for t in turns] == [("resident", "I'd like tea")]
    assert events[-1] == CallUpdated(call_id=call.id)


def test_score_records_summary_and_publishes(env):
    svc, store, events = env
    call = svc.raise_call("12")
    svc.score(call.id, Urgency.NURSE_SOON, "pain", summary="hip pain")
    saved = store.calls.get(call.id)
    assert (saved.urgency, saved.category, saved.summary) == (
        Urgency.NURSE_SOON,
        "pain",
        "hip pain",
    )
    assert events[-1] == CallScored(call_id=call.id, urgency=Urgency.NURSE_SOON, category="pain")


def test_lower_rescore_keeps_urgency_and_publishes_effective_level(env):
    svc, store, events = env
    call = svc.raise_call("12")
    svc.score(call.id, Urgency.EMERGENCY, "fall")
    svc.score(call.id, Urgency.CHAT, "chat")
    assert store.calls.get(call.id).urgency is Urgency.EMERGENCY
    assert events[-1].urgency is Urgency.EMERGENCY
    assert events[-1].category == "fall"


def test_mark_in_visit_sets_first_response_and_publishes_a_live_update(env, clock):
    svc, store, events = env
    call = svc.raise_call("12")
    store.calls.save(_assigned(store, call.id, clock))
    svc.mark_in_visit(call.id)
    saved = store.calls.get(call.id)
    assert saved.status is CallStatus.IN_VISIT
    assert saved.first_response_at == clock.now()
    assert events[-1] == CallUpdated(call_id=call.id)


def _assigned(store, call_id, clock):
    call = store.calls.get(call_id)
    call.transition(CallStatus.ASSIGNED, clock.now())
    return call


def test_resolve_publishes_and_stamps_time(env, clock):
    svc, store, events = env
    call = svc.raise_call("12")
    store.calls.save(_assigned(store, call.id, clock))
    svc.resolve(call.id, by_robot=False)
    saved = store.calls.get(call.id)
    assert saved.status is CallStatus.RESOLVED
    assert saved.resolved_at == clock.now()
    assert events[-1] == CallResolved(call_id=call.id, by_robot=False)


def test_resolving_a_ringing_call_is_invalid_and_publishes_nothing(env):
    svc, _, events = env
    call = svc.raise_call("12")
    with pytest.raises(InvalidTransition):
        svc.resolve(call.id)
    assert len(events) == 1


def test_ack_by_nurse_marks_acked_and_records_nurse(env, clock):
    svc, store, _ = env
    call = svc.raise_call("12")
    escalated = store.calls.get(call.id)
    escalated.transition(CallStatus.ESCALATED, clock.now())
    store.calls.save(escalated)
    svc.ack_by_nurse(call.id, "n1")
    saved = store.calls.get(call.id)
    assert saved.status is CallStatus.NURSE_ACKED
    assert "n1" in saved.assigned_to


@pytest.mark.parametrize(
    "op",
    [
        lambda s: s.add_turn("nope", "robot", "hi"),
        lambda s: s.score("nope", Urgency.CHAT, "chat"),
        lambda s: s.mark_in_visit("nope"),
        lambda s: s.resolve("nope"),
        lambda s: s.ack_by_nurse("nope", "n1"),
    ],
)
def test_unknown_call_id_raises_call_not_found(env, op):
    svc, _, _ = env
    with pytest.raises(CallNotFound):
        op(svc)


def test_mark_in_visit_after_escalation_keeps_escalated_and_sets_first_response(env, clock):
    svc, store, _ = env
    call = svc.raise_call("12")
    store.calls.save(_assigned(store, call.id, clock))
    svc.score(call.id, Urgency.NURSE_SOON, "pain")
    clock.advance(seconds=20)
    svc.mark_in_visit(call.id)
    saved = store.calls.get(call.id)
    assert saved.status is CallStatus.ESCALATED
    assert saved.first_response_at == clock.now()
