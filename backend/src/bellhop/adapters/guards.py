"""Reliability guards: bound external calls so a hang never stalls a bell press.

Stdlib only. A hung call keeps its worker thread until it returns (threads cannot
be killed), so the shared pool is small and callers should pair guards with a
breaker where calls repeat.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any

from bellhop.domain import Alert, MemoryFact
from bellhop.ports import EventBus, Handler, MemoryIndex, Notifier, RobotGateway

log = logging.getLogger(__name__)

_MISSING: Any = object()
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="bellhop-guard")


class GuardTimeout(TimeoutError):
    """An external call did not finish within its deadline."""


def call_with_timeout(
    fn: Callable[..., Any], seconds: float, *args: Any, default: Any = _MISSING, **kwargs: Any
) -> Any:
    """Run fn in the shared pool; raise GuardTimeout (or return default) past the deadline."""
    future: Future[Any] = _POOL.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=seconds)
    except FutureTimeout:
        future.cancel()
        if default is not _MISSING:
            return default
        name = getattr(fn, "__name__", repr(fn))
        raise GuardTimeout(f"{name} exceeded {seconds}s") from None


class CircuitBreaker:
    """Opens after N consecutive failures; lets one probe through after reset_seconds."""

    def __init__(
        self,
        failures: int = 3,
        reset_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = failures
        self._reset = reset_seconds
        self._clock = clock
        self._count = 0
        self._opened_at: float | None = None
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return True
            if self._clock() - self._opened_at >= self._reset:
                self._opened_at = self._clock()  # half-open: one probe per window
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._count = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._count += 1
            if self._count >= self._limit:
                self._opened_at = self._clock()


class GuardedNotifier:
    """Never raises and never blocks past timeout; failed alerts are kept for retry."""

    def __init__(self, inner: Notifier, timeout: float = 2.0) -> None:
        self._inner = inner
        self._timeout = timeout
        self.failed_alerts: list[Alert] = []

    def send(self, alert: Alert) -> None:
        try:
            call_with_timeout(self._inner.send, self._timeout, alert)
        except Exception:
            log.exception("notifier failed or timed out for alert %s", alert.id)
            self.failed_alerts.append(alert)

    def retry_failed(self) -> int:
        """Resend failed alerts once; return how many succeeded."""
        pending, self.failed_alerts = self.failed_alerts, []
        for alert in pending:
            self.send(alert)
        return len(pending) - len(self.failed_alerts)


class GuardedRobotGateway:
    """Raises GuardTimeout on a hang so the Dispatcher falls back to a nurse.

    A go_to that times out may still reach the robot later (a ghost drive). Once the call has
    fallen back to a nurse, one more stop is sent `restop_after` seconds later (default: one
    more guard window) unless the robot got a newer go_to meanwhile. This is a heuristic; the
    robot rejecting stale go_to requests is the real fix. `stop` is fire and forget: it never
    blocks the bell request, never raises, and logs failures.
    """

    def __init__(
        self, inner: RobotGateway, timeout: float = 2.0, restop_after: float | None = None
    ) -> None:
        self._inner = inner
        self._timeout = timeout
        self._restop_after = timeout if restop_after is None else restop_after
        self._sent: dict[str, int] = {}
        self._lock = threading.Lock()

    def go_to(self, robot_id: str, room: str) -> None:
        with self._lock:
            self._sent[robot_id] = generation = self._sent.get(robot_id, 0) + 1
        try:
            call_with_timeout(self._inner.go_to, self._timeout, robot_id, room)
        except GuardTimeout:
            timer = threading.Timer(self._restop_after, self._restop, (robot_id, generation))
            timer.daemon = True
            timer.start()
            raise

    def set_led(self, robot_id: str, state: str) -> None:
        call_with_timeout(self._inner.set_led, self._timeout, robot_id, state)

    def stop(self, robot_id: str) -> None:
        future: Future[Any] = _POOL.submit(self._inner.stop, robot_id)
        future.add_done_callback(lambda done: self._log_stop(done, robot_id))

    def _restop(self, robot_id: str, generation: int) -> None:
        with self._lock:
            if self._sent.get(robot_id) != generation:
                return  # a newer go_to owns the robot now
        self.stop(robot_id)

    @staticmethod
    def _log_stop(done: Future[Any], robot_id: str) -> None:
        if not done.cancelled() and done.exception() is not None:
            log.warning("stop failed for %s: %s", robot_id, done.exception())


class GuardedMemoryIndex:
    """Recall within budget_ms or answer from the fallback; a breaker skips a slow index."""

    def __init__(
        self,
        inner: MemoryIndex,
        fallback: MemoryIndex,
        budget_ms: float = 50,
        breaker: CircuitBreaker | None = None,
    ) -> None:
        self._inner = inner
        self._fallback = fallback
        self._budget = budget_ms / 1000
        self._breaker = breaker or CircuitBreaker()

    def add(self, fact: MemoryFact) -> None:
        self._inner.add(fact)

    def recall(self, resident_id: str, utterance: str, k: int = 3) -> list[MemoryFact]:
        if not self._breaker.allow():
            return self._fallback.recall(resident_id, utterance, k)
        try:
            out = call_with_timeout(self._inner.recall, self._budget, resident_id, utterance, k)
        except Exception:
            log.warning("memory recall over budget or failed; using fallback")
            self._breaker.record_failure()
            return self._fallback.recall(resident_id, utterance, k)
        self._breaker.record_success()
        return out


class SerializedSubscriptions:
    """Bus view whose subscribed handlers run one at a time.

    Guarded gateway calls hop threads, which widens the check-then-act window in the
    Dispatcher (two bells could both pick the same idle robot). Serializing its handler
    restores the atomicity the synchronous call had; the lock is held at most one timeout.
    """

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._lock = threading.RLock()

    def publish(self, event: Any) -> None:
        self._bus.publish(event)

    def subscribe(self, event_type: type, handler: Handler) -> None:
        def locked(event: Any) -> None:
            with self._lock:
                handler(event)

        self._bus.subscribe(event_type, locked)
