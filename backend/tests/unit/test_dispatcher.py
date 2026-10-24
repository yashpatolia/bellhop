import pytest

from bellhop.adapters.event_bus import InMemoryEventBus
from bellhop.adapters.memory_store import InMemoryStore
from bellhop.domain import CallStatus, Nurse, Resident, Robot, RobotStatus
from bellhop.domain.events import CallAssigned, RobotUnreachable
from bellhop.services.call_service import CallService
from bellhop.services.dispatcher import Decision, DefaultPolicy, Dispatcher


class RecordingGateway:
    def __init__(self) -> None:
        self.moves: list[tuple[str, str]] = []
        self.stops: list[str] = []
        self.fail = False
        self.fail_stop = False

    def go_to(self, robot_id: str, room: str) -> None:
        if self.fail:
            raise TimeoutError("pi down")
        self.moves.append((robot_id, room))

    def stop(self, robot_id: str) -> None:
        if self.fail_stop:
            raise TimeoutError("pi down")
        self.stops.append(robot_id)

    def set_led(self, robot_id: str, state: str) -> None:
        pass


@pytest.fixture
def env(clock, ids):
    store, bus, assigned, gateway = InMemoryStore(), InMemoryEventBus(), [], RecordingGateway()
    bus.subscribe(CallAssigned, assigned.append)
    Dispatcher(
        store.calls,
        store.residents,
        store.robots,
        store.nurses,
        gateway,
        DefaultPolicy(),
        bus,
        clock,
    )
    svc = CallService(store.calls, store.residents, bus, clock, ids)
    return svc, store, assigned, gateway


def test_idle_robot_is_assigned_and_sent(env):
    svc, store, assigned, gateway = env
    store.robots.save(Robot(id="b1"))
    call = svc.raise_call("12")
    saved = store.calls.get(call.id)
    assert saved.status is CallStatus.ROBOT_EN_ROUTE
    assert saved.assigned_at is not None
    assert saved.assigned_to == ["b1"]
    assert saved.robot_id == "b1"
    assert gateway.moves == [("b1", "12")]
    assert store.robots.get("b1").status is RobotStatus.BUSY
    assert assigned == [CallAssigned(call_id=call.id, robot_id="b1", nurse_id=None)]


def test_low_battery_robot_is_skipped(env):
    svc, store, _, gateway = env
    store.robots.save(Robot(id="low", battery=0.1))
    store.robots.save(Robot(id="ok", battery=0.5))
    svc.raise_call("12")
    assert gateway.moves == [("ok", "12")]


def test_busy_and_charging_robots_are_skipped(env):
    svc, store, _, gateway = env
    store.robots.save(Robot(id="busy", status=RobotStatus.BUSY))
    store.robots.save(Robot(id="chg", status=RobotStatus.CHARGING))
    store.nurses.save(Nurse(id="n1", name="A"))
    svc.raise_call("12")
    assert gateway.moves == []


def test_robot_in_same_room_is_preferred(env):
    svc, store, _, gateway = env
    store.robots.save(Robot(id="far", room="3"))
    store.robots.save(Robot(id="near", room="12"))
    svc.raise_call("12")
    assert gateway.moves == [("near", "12")]


def test_risk_flag_resident_also_gets_a_nurse(env):
    svc, store, assigned, _ = env
    store.residents.save(Resident(id="r1", name="Ada", room="12", risk_flags={"falls"}))
    store.robots.save(Robot(id="b1"))
    store.nurses.save(Nurse(id="n1", name="A"))
    call = svc.raise_call("12")
    assert assigned[0].robot_id == "b1" and assigned[0].nurse_id == "n1"
    assert store.calls.get(call.id).assigned_to == ["b1", "n1"]


def test_no_risk_flags_means_robot_only(env):
    svc, store, assigned, _ = env
    store.residents.save(Resident(id="r1", name="Ada", room="12"))
    store.robots.save(Robot(id="b1"))
    store.nurses.save(Nurse(id="n1", name="A"))
    svc.raise_call("12")
    assert assigned[0].nurse_id is None


def test_nurse_alone_when_no_robot_is_free(env):
    svc, store, assigned, gateway = env
    store.nurses.save(Nurse(id="n1", name="A"))
    call = svc.raise_call("12")
    assert store.calls.get(call.id).status is CallStatus.ASSIGNED
    assert assigned == [CallAssigned(call_id=call.id, robot_id=None, nurse_id="n1")]
    assert gateway.moves == []


def test_least_loaded_on_shift_nurse_is_chosen(env):
    svc, store, assigned, _ = env
    store.nurses.save(Nurse(id="busy", name="A", open_tasks=3))
    store.nurses.save(Nurse(id="free", name="B", open_tasks=1))
    store.nurses.save(Nurse(id="off", name="C", on_shift=False, open_tasks=0))
    svc.raise_call("12")
    assert assigned[0].nurse_id == "free"


def test_nothing_available_escalates_the_call(env):
    svc, store, assigned, gateway = env
    call = svc.raise_call("12")
    assert store.calls.get(call.id).status is CallStatus.ESCALATED
    assert assigned == [] and gateway.moves == []


def test_default_policy_returns_empty_decision_with_no_resources(clock):
    from bellhop.domain import Call

    call = Call(id="c", room="1", created_at=clock.now())
    assert DefaultPolicy().decide(call, None, [], []) == Decision(None, None)


def test_failed_go_to_assigns_a_nurse_even_without_risk_flags(env):
    svc, store, assigned, gateway = env
    store.residents.save(Resident(id="r1", name="Ada", room="12"))
    store.robots.save(Robot(id="b1"))
    store.nurses.save(Nurse(id="n1", name="A"))
    gateway.fail = True
    call = svc.raise_call("12")
    saved = store.calls.get(call.id)
    assert saved.assigned_to == ["n1"] and saved.robot_id is None
    assert saved.status is CallStatus.ASSIGNED
    assert saved.nurse_tasks == {"n1"}
    assert assigned == [CallAssigned(call_id=call.id, robot_id=None, nurse_id="n1")]
    assert store.robots.get("b1").status is RobotStatus.IDLE


def test_failed_go_to_picks_the_least_loaded_on_shift_nurse(env):
    svc, store, assigned, gateway = env
    store.robots.save(Robot(id="b1"))
    store.nurses.save(Nurse(id="busy", name="A", open_tasks=3))
    store.nurses.save(Nurse(id="free", name="B", open_tasks=1))
    store.nurses.save(Nurse(id="off", name="C", on_shift=False))
    gateway.fail = True
    svc.raise_call("12")
    assert assigned[0].nurse_id == "free"


def test_failed_go_to_with_a_risk_flag_nurse_keeps_that_nurse_once(env):
    svc, store, assigned, gateway = env
    store.residents.save(Resident(id="r1", name="Ada", room="12", risk_flags={"falls"}))
    store.robots.save(Robot(id="b1"))
    store.nurses.save(Nurse(id="n1", name="A"))
    gateway.fail = True
    call = svc.raise_call("12")
    assert store.calls.get(call.id).assigned_to == ["n1"]
    assert store.nurses.get("n1").open_tasks == 1


def test_failed_go_to_tells_the_robot_to_stop(env):
    svc, store, _, gateway = env
    store.robots.save(Robot(id="b1"))
    store.nurses.save(Nurse(id="n1", name="A"))
    gateway.fail = True
    svc.raise_call("12")
    assert gateway.stops == ["b1"]


def test_failing_stop_is_ignored(env):
    svc, store, assigned, gateway = env
    store.robots.save(Robot(id="b1"))
    store.nurses.save(Nurse(id="n1", name="A"))
    gateway.fail = gateway.fail_stop = True
    svc.raise_call("12")
    assert assigned[0].nurse_id == "n1"


def test_failed_go_to_publishes_robot_unreachable(env):
    svc, store, _, gateway = env
    unreachable = []
    svc_bus = svc._bus
    svc_bus.subscribe(RobotUnreachable, unreachable.append)
    store.robots.save(Robot(id="b1"))
    gateway.fail = True
    call = svc.raise_call("12")  # no nurse on shift either: still announced
    assert unreachable == [RobotUnreachable(call_id=call.id, robot_id="b1")]
    assert store.calls.get(call.id).status is CallStatus.ESCALATED


def test_successful_go_to_does_not_publish_robot_unreachable(env):
    svc, store, _, _ = env
    unreachable = []
    svc._bus.subscribe(RobotUnreachable, unreachable.append)
    store.robots.save(Robot(id="b1"))
    svc.raise_call("12")
    assert unreachable == []
