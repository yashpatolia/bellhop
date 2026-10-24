from bellhop.adapters.memory_store import InMemoryStore
from bellhop.domain import Alert, Call, CallStatus, Nurse, Resident, Robot, Urgency, Visit


def _call(clock, id="c1", room="12") -> Call:
    return Call(id=id, room=room, created_at=clock.now())


def test_save_is_upsert_and_get_returns_saved_call(clock):
    calls = InMemoryStore().calls
    call = _call(clock)
    calls.save(call)
    call.room = "13"
    calls.save(call)
    assert calls.get("c1").room == "13"
    assert len(calls.list_all()) == 1


def test_get_unknown_returns_none():
    assert InMemoryStore().calls.get("nope") is None


def test_get_returns_copy_so_mutation_needs_save(clock):
    calls = InMemoryStore().calls
    calls.save(_call(clock))
    calls.get("c1").room = "99"
    assert calls.get("c1").room == "12"


def test_saving_stores_a_snapshot(clock):
    calls = InMemoryStore().calls
    call = _call(clock)
    calls.save(call)
    call.room = "99"
    assert calls.get("c1").room == "12"


def test_list_open_excludes_resolved_and_closed(clock):
    calls = InMemoryStore().calls
    for id, status in [
        ("a", CallStatus.RINGING),
        ("b", CallStatus.RESOLVED),
        ("c", CallStatus.CLOSED),
        ("d", CallStatus.ESCALATED),
    ]:
        call = _call(clock, id)
        call.status = status
        calls.save(call)
    assert sorted(c.id for c in calls.list_open()) == ["a", "d"]


def test_resident_by_room():
    residents = InMemoryStore().residents
    residents.save(Resident(id="r1", name="Ada", room="12"))
    assert residents.by_room("12").id == "r1"
    assert residents.by_room("13") is None
    assert residents.get("r1").name == "Ada"


def test_list_on_shift_nurses_only():
    nurses = InMemoryStore().nurses
    nurses.save(Nurse(id="n1", name="A"))
    nurses.save(Nurse(id="n2", name="B", on_shift=False))
    assert [n.id for n in nurses.list_on_shift()] == ["n1"]


def test_robot_save_get_list():
    robots = InMemoryStore().robots
    robots.save(Robot(id="b1"))
    assert robots.get("b1").battery == 1.0
    assert [r.id for r in robots.list_all()] == ["b1"]


def test_visit_for_call_and_list():
    visits = InMemoryStore().visits
    visits.save(Visit(id="v1", call_id="c1", resident_id=None, robot_id=None))
    assert visits.for_call("c1").id == "v1"
    assert visits.for_call("zzz") is None
    assert len(visits.list_all()) == 1


def test_alerts_for_call(clock):
    alerts = InMemoryStore().alerts
    for id, call_id in [("a1", "c1"), ("a2", "c1"), ("a3", "c2")]:
        alerts.save(
            Alert(
                id=id,
                call_id=call_id,
                nurse_id=None,
                level=Urgency.EMERGENCY,
                message="m",
                created_at=clock.now(),
            )
        )
    assert [a.id for a in alerts.for_call("c1")] == ["a1", "a2"]
    assert alerts.get("a3").call_id == "c2"
