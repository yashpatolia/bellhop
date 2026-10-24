import time
from datetime import UTC, datetime

import pytest

from bellhop.adapters.event_bus import InMemoryEventBus
from bellhop.adapters.guards import (
    CircuitBreaker,
    GuardedMemoryIndex,
    GuardedNotifier,
    GuardedRobotGateway,
    GuardTimeout,
    call_with_timeout,
)
from bellhop.adapters.local_memory import LocalMemoryIndex
from bellhop.container import Settings, build_container
from bellhop.domain import Alert, MemoryFact, Urgency

TICK = 0.05
HANG = 0.25


def slow(seconds=HANG, value="ok"):
    def fn(*_a, **_k):
        time.sleep(seconds)
        return value

    return fn


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make_alert(alert_id="a1"):
    return Alert(
        id=alert_id,
        call_id="c1",
        nurse_id=None,
        level=Urgency.EMERGENCY,
        message="m",
        created_at=datetime(2026, 10, 24, tzinfo=UTC),
    )


def make_fact(fid="f1", text="loves jazz"):
    return MemoryFact(
        id=fid, resident_id="r1", text=text, created_at=datetime(2026, 10, 24, tzinfo=UTC)
    )


# call_with_timeout


def test_call_with_timeout_returns_value():
    assert call_with_timeout(lambda: 7, 1.0) == 7


def test_call_with_timeout_raises_guard_timeout():
    start = time.monotonic()
    with pytest.raises(GuardTimeout):
        call_with_timeout(slow(), TICK)
    assert time.monotonic() - start < HANG


def test_call_with_timeout_default_instead_of_raise():
    assert call_with_timeout(slow(), TICK, default="d") == "d"


def test_call_with_timeout_propagates_errors():
    def boom():
        raise ValueError("x")

    with pytest.raises(ValueError):
        call_with_timeout(boom, 1.0)


def test_guard_timeout_is_a_timeout_error():
    assert issubclass(GuardTimeout, TimeoutError)


# CircuitBreaker


def test_breaker_opens_after_failures_and_resets_after_window():
    clock = FakeClock()
    b = CircuitBreaker(failures=3, reset_seconds=30, clock=clock)
    for _ in range(2):
        b.record_failure()
    assert b.allow()
    b.record_failure()
    assert not b.allow()
    clock.t = 29
    assert not b.allow()
    clock.t = 31
    assert b.allow()  # half-open probe


def test_breaker_success_resets_count():
    b = CircuitBreaker(failures=2, reset_seconds=30, clock=FakeClock())
    b.record_failure()
    b.record_success()
    b.record_failure()
    assert b.allow()


def test_breaker_reopens_on_failed_probe():
    clock = FakeClock()
    b = CircuitBreaker(failures=1, reset_seconds=10, clock=clock)
    b.record_failure()
    clock.t = 11
    assert b.allow()
    b.record_failure()
    assert not b.allow()


# GuardedNotifier


class Inner:
    def __init__(self, fn=None):
        self.calls = []
        self.fn = fn

    def send(self, alert):
        if self.fn:
            self.fn()
        self.calls.append(alert)


def test_guarded_notifier_passes_through():
    inner = Inner()
    g = GuardedNotifier(inner, timeout=1.0)
    g.send(make_alert())
    assert len(inner.calls) == 1
    assert g.failed_alerts == []


def test_guarded_notifier_hang_does_not_raise_and_records():
    g = GuardedNotifier(Inner(lambda: time.sleep(HANG)), timeout=TICK)
    start = time.monotonic()
    g.send(make_alert("a9"))
    assert time.monotonic() - start < HANG
    assert [a.id for a in g.failed_alerts] == ["a9"]


def test_guarded_notifier_error_does_not_raise_and_records():
    def boom():
        raise RuntimeError("down")

    g = GuardedNotifier(Inner(boom), timeout=1.0)
    g.send(make_alert())
    assert len(g.failed_alerts) == 1


def test_guarded_notifier_retry_resends_and_clears_successes():
    state = {"fail": True}

    def maybe():
        if state["fail"]:
            raise RuntimeError

    inner = Inner(maybe)
    g = GuardedNotifier(inner, timeout=1.0)
    g.send(make_alert())
    state["fail"] = False
    assert g.retry_failed() == 1
    assert g.failed_alerts == []
    assert len(inner.calls) == 1


# GuardedRobotGateway


class Gw:
    def __init__(self, delay=0.0):
        self.delay = delay
        self.cmds = []

    def go_to(self, robot_id, room):
        time.sleep(self.delay)
        self.cmds.append(("go_to", robot_id, room))

    def set_led(self, robot_id, state):
        time.sleep(self.delay)
        self.cmds.append(("set_led", robot_id, state))

    def stop(self, robot_id):
        time.sleep(self.delay)
        self.cmds.append(("stop", robot_id))


def test_guarded_gateway_passes_through():
    inner = Gw()
    g = GuardedRobotGateway(inner, timeout=1.0)
    g.go_to("r", "101")
    g.set_led("r", "green")
    assert len(inner.cmds) == 2


def test_guarded_gateway_raises_on_hang():
    g = GuardedRobotGateway(Gw(HANG), timeout=TICK)
    with pytest.raises(GuardTimeout):
        g.go_to("r", "101")
    with pytest.raises(GuardTimeout):
        g.set_led("r", "red")


def test_guarded_stop_passes_through_without_blocking():
    inner = Gw()
    g = GuardedRobotGateway(inner, timeout=1.0)
    g.stop("r")
    deadline = time.monotonic() + 1.0
    while not inner.cmds and time.monotonic() < deadline:
        time.sleep(0.005)
    assert inner.cmds == [("stop", "r")]


def test_guarded_stop_never_raises_or_blocks_on_hang():
    g = GuardedRobotGateway(Gw(HANG), timeout=TICK)
    started = time.monotonic()
    g.stop("r")
    assert time.monotonic() - started < TICK


def test_guarded_stop_swallows_inner_errors():
    class Boom(Gw):
        def stop(self, robot_id):
            raise RuntimeError("pi down")

    GuardedRobotGateway(Boom(), timeout=1.0).stop("r")  # must not raise


def _wait_for(pred, seconds=2.0):
    deadline = time.monotonic() + seconds
    while not pred() and time.monotonic() < deadline:
        time.sleep(0.005)


def test_go_to_that_lands_after_the_timeout_is_stopped_again():
    inner = Gw(0.15)
    g = GuardedRobotGateway(inner, timeout=TICK, restop_after=0.25)
    with pytest.raises(GuardTimeout):
        g.go_to("r", "101")
    _wait_for(lambda: ("stop", "r") in inner.cmds)
    assert inner.cmds == [("go_to", "r", "101"), ("stop", "r")]  # the stop came after the landing


def test_go_to_inside_the_timeout_schedules_no_stop():
    inner = Gw()
    GuardedRobotGateway(inner, timeout=1.0, restop_after=0.05).go_to("r", "101")
    time.sleep(0.15)
    assert inner.cmds == [("go_to", "r", "101")]


def test_late_stop_is_skipped_when_the_robot_got_a_newer_go_to():
    delays = iter([0.3, 0.0])

    class Seq(Gw):
        def go_to(self, robot_id, room):
            time.sleep(next(delays))
            self.cmds.append(("go_to", robot_id, room))

    inner = Seq()
    g = GuardedRobotGateway(inner, timeout=TICK, restop_after=0.1)
    with pytest.raises(GuardTimeout):
        g.go_to("r", "101")
    g.go_to("r", "102")  # the robot was freed and sent elsewhere
    time.sleep(0.3)
    assert ("stop", "r") not in inner.cmds


# GuardedMemoryIndex


class SlowIndex:
    def __init__(self, delay=0.0, fail=False):
        self.delay, self.fail, self.recalls = delay, fail, 0
        self.facts = []

    def add(self, fact):
        self.facts.append(fact)

    def recall(self, resident_id, utterance, k=3):
        self.recalls += 1
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("index down")
        return list(self.facts)[:k]


def fallback_with_fact():
    fb = LocalMemoryIndex()
    fb.add(make_fact("fb", "loves jazz music"))
    return fb


def test_memory_fast_inner_is_used():
    inner = SlowIndex()
    inner.add(make_fact("in"))
    g = GuardedMemoryIndex(inner, fallback_with_fact(), budget_ms=1000)
    assert [f.id for f in g.recall("r1", "jazz")] == ["in"]


def test_memory_over_budget_returns_fallback():
    g = GuardedMemoryIndex(SlowIndex(HANG), fallback_with_fact(), budget_ms=50)
    start = time.monotonic()
    out = g.recall("r1", "jazz music")
    assert time.monotonic() - start < HANG
    assert [f.id for f in out] == ["fb"]


def test_memory_error_returns_fallback():
    g = GuardedMemoryIndex(SlowIndex(fail=True), fallback_with_fact(), budget_ms=1000)
    assert [f.id for f in g.recall("r1", "jazz music")] == ["fb"]


def test_memory_breaker_skips_inner_while_open_then_recovers():
    inner = SlowIndex(fail=True)
    clock = FakeClock()
    breaker = CircuitBreaker(failures=2, reset_seconds=30, clock=clock)
    g = GuardedMemoryIndex(inner, fallback_with_fact(), budget_ms=1000, breaker=breaker)
    g.recall("r1", "jazz music")
    g.recall("r1", "jazz music")
    assert inner.recalls == 2
    g.recall("r1", "jazz music")
    assert inner.recalls == 2  # skipped
    clock.t = 31
    inner.fail = False
    g.recall("r1", "jazz music")
    assert inner.recalls == 3


def test_memory_add_goes_to_inner():
    inner = SlowIndex()
    g = GuardedMemoryIndex(inner, LocalMemoryIndex(), budget_ms=1000)
    g.add(make_fact("x"))
    assert [f.id for f in inner.facts] == ["x"]


# Event bus known limitation + container wiring


def test_event_bus_isolates_failing_handler_but_is_synchronous():
    bus = InMemoryEventBus()
    seen = []

    def bad(_e):
        raise RuntimeError

    bus.subscribe(str, bad)
    bus.subscribe(str, seen.append)
    bus.publish("e")
    assert seen == ["e"]


def test_container_guards_on_by_default_and_off_when_disabled():
    c = build_container(Settings())
    assert isinstance(c.guarded_notifier, GuardedNotifier)
    assert isinstance(c.guarded_gateway, GuardedRobotGateway)
    off = build_container(Settings(guard_timeouts=False))
    assert off.guarded_notifier is None
    assert off.guarded_gateway is None


def test_container_recorders_still_see_traffic_through_guards():
    c = build_container(Settings())
    c.guarded_notifier.send(make_alert())
    c.guarded_gateway.go_to("robot_1", "12")
    assert len(c.notifier.sent) == 1
    assert c.gateway.commands == [("go_to", "robot_1", "12")]


def test_container_wraps_memory_index_when_guarded():
    c = build_container(Settings(memory="moss"))
    assert isinstance(c.memory._index, GuardedMemoryIndex)
    off = build_container(Settings(memory="moss", guard_timeouts=False))
    assert not isinstance(off.memory._index, GuardedMemoryIndex)


def test_recording_gateway_records_stop():
    from bellhop.adapters.robot_gateway import RecordingRobotGateway

    g = RecordingRobotGateway()
    g.stop("robot_1")
    assert list(g.commands) == [("stop", "robot_1", "")]
