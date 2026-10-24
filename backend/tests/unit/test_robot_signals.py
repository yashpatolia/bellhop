from bellhop.adapters.event_bus import InMemoryEventBus
from bellhop.adapters.memory_store import InMemoryStore
from bellhop.domain import Call, LedState, Urgency
from bellhop.domain.events import CallAssigned, CallResolved, CallScored
from bellhop.services.robot_signals import RobotSignals


class FakeGateway:
    def __init__(self, fail=False):
        self.leds = []
        self.fail = fail

    def go_to(self, robot_id, room): ...

    def set_led(self, robot_id, state):
        if self.fail:
            raise RuntimeError("pi down")
        self.leds.append((robot_id, state))


def env(clock, robot_id="r1", fail=False):
    store, bus, gw = InMemoryStore(), InMemoryEventBus(), FakeGateway(fail)
    store.calls.save(Call(id="c1", room="12", robot_id=robot_id, created_at=clock.now()))
    RobotSignals(store.calls, gw, bus)
    return bus, gw


def test_led_state_values():
    assert [s.value for s in LedState] == ["idle", "listening", "nurse_on_way", "emergency"]


def test_urgency_4_is_emergency(clock):
    bus, gw = env(clock)
    bus.publish(CallScored(call_id="c1", urgency=Urgency.EMERGENCY, category="fall"))
    assert gw.leds == [("r1", "emergency")]


def test_urgency_3_is_nurse_on_way(clock):
    bus, gw = env(clock)
    bus.publish(CallScored(call_id="c1", urgency=Urgency.NURSE_SOON, category="pain"))
    assert gw.leds == [("r1", "nurse_on_way")]


def test_low_urgency_sends_nothing(clock):
    bus, gw = env(clock)
    bus.publish(CallScored(call_id="c1", urgency=Urgency.CHAT, category="social"))
    assert gw.leds == []


def test_assigned_is_listening(clock):
    bus, gw = env(clock)
    bus.publish(CallAssigned(call_id="c1", robot_id="r1", nurse_id=None))
    assert gw.leds == [("r1", "listening")]


def test_resolved_is_idle(clock):
    bus, gw = env(clock)
    bus.publish(CallResolved(call_id="c1", by_robot=True))
    assert gw.leds == [("r1", "idle")]


def test_no_robot_no_signal(clock):
    bus, gw = env(clock, robot_id=None)
    bus.publish(CallAssigned(call_id="c1", robot_id=None, nurse_id="n1"))
    bus.publish(CallScored(call_id="c1", urgency=Urgency.EMERGENCY, category="fall"))
    bus.publish(CallResolved(call_id="c1", by_robot=False))
    assert gw.leds == []


def test_unknown_call_is_ignored(clock):
    bus, gw = env(clock)
    bus.publish(CallScored(call_id="nope", urgency=Urgency.EMERGENCY, category="fall"))
    assert gw.leds == []


def test_gateway_failure_never_propagates(clock):
    bus, gw = env(clock, fail=True)
    signals_ok = []
    bus.subscribe(CallScored, lambda e: signals_ok.append(e))
    bus.publish(CallScored(call_id="c1", urgency=Urgency.EMERGENCY, category="fall"))
    assert len(signals_ok) == 1
