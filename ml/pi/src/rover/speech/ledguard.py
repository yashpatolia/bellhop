"""Keep the robot's LED honest from the Pi side when the backend cannot.

Only the backend sends "idle", and only when a call ends. If it dies mid-visit the LED would stay
on "listening" or "emergency" for good, so this process (which owns the visit) does three things:
re-sends a lit LED while the visit is live (the drive server drops a lit LED nobody refreshes for
LED_HOLD_S), sets it idle when the visit ends, and on an abnormal end (crash, SIGTERM) also stops
the wheels. A normal end must not POST /stop: the visit has just sent the robot home.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable, Iterator
from typing import Any

from rover import config, obslog
from rover.drive import LED_STATES

Post = Callable[[str, dict], "str | None"]
Fetch = Callable[[], "dict[str, Any] | None"]


def _post(path: str, body: dict) -> str | None:
    from rover.agent.tools import post_pi  # looked up late: tests and Macs without a drive server

    return post_pi(path, body)


def _fetch() -> dict[str, Any] | None:
    from rover.status import fetch_snapshot

    return fetch_snapshot()


def release_led(post: Post | None = None) -> None:
    try:
        (post or _post)("/led", {"state": "idle"})
    except Exception as exc:  # noqa: BLE001 - releasing must never block a shutdown
        print(f"ledguard: could not set the LED idle: {exc!r}")


def release_robot(post: Post | None = None) -> None:
    """Abnormal end: LED idle and wheels stopped."""
    obslog.event("visit.release", stop=True)
    release_led(post)
    try:
        (post or _post)("/stop", {})
    except Exception as exc:  # noqa: BLE001
        print(f"ledguard: could not stop the robot: {exc!r}")


class LedKeepalive:
    """While a visit is live, re-send the LED the robot already shows (never light an idle one)."""

    def __init__(
        self,
        post: Post | None = None,
        fetch: Fetch | None = None,
        period_s: float = config.LED_KEEPALIVE_S,
    ) -> None:
        self._post, self._fetch, self.period_s = post or _post, fetch or _fetch, period_s
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def tick(self) -> None:
        try:
            snapshot = self._fetch()
            led = snapshot.get("led") if isinstance(snapshot, dict) else None
            if led in LED_STATES and led != "idle":
                self._post("/led", {"state": led})
        except Exception as exc:  # noqa: BLE001 - a keepalive is best effort
            print(f"ledguard: keepalive failed: {exc!r}")

    def _run(self) -> None:
        while not self._stop.wait(self.period_s):
            self.tick()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="led-keepalive")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(5)


@contextlib.contextmanager
def visit_guard(
    on_abnormal: Callable[[], object],
    post: Post | None = None,
    fetch: Fetch | None = None,
    period_s: float = config.LED_KEEPALIVE_S,
) -> Iterator[None]:
    keepalive = LedKeepalive(post, fetch, period_s)
    keepalive.start()
    try:
        yield
    except BaseException:  # includes SystemExit from the SIGTERM handler
        keepalive.stop()
        on_abnormal()
        raise
    else:
        keepalive.stop()
        release_led(post)
