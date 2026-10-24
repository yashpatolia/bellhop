"""Motors-off guarantees: stop on SIGTERM/SIGINT/SIGHUP and on any exit path."""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import sys
import threading
from collections.abc import Callable, Iterator

log = logging.getLogger("rover.safety")
DEFAULT_SIGNALS = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)


def _once(stop_fn: Callable[[], object]) -> Callable[[], None]:
    lock = threading.Lock()
    done = False

    def run() -> None:
        nonlocal done
        with lock:
            if done:
                return
            done = True
        try:
            stop_fn()
        except Exception:  # noqa: BLE001 - keep shutting down even if the stop fails
            log.exception("motors-off failed")

    return run


def install_motors_off(
    stop_fn: Callable[[], object],
    signals: tuple[int, ...] = DEFAULT_SIGNALS,
    registrar: Callable[..., object] = signal.signal,
    hard_exit_after_s: float | None = None,
) -> Callable[[], None]:
    """Run stop_fn once on any of `signals`, then exit 0. Returns the idempotent stop.

    With hard_exit_after_s, a daemon timer calls os._exit(0) that long after the stop: a worker
    thread stuck in a download or a socket cannot keep the interpreter alive past its atexit
    join (ThreadPoolExecutor threads are joined there), so SIGTERM always ends the process."""
    stop = _once(stop_fn)

    def handler(signum: int, frame: object) -> None:
        stop()
        if hard_exit_after_s is not None:
            timer = threading.Timer(hard_exit_after_s, os._exit, args=(0,))
            timer.daemon = True
            timer.name = "hard-exit"
            timer.start()
        sys.exit(0)

    for sig in signals:
        registrar(sig, handler)
    return stop


@contextlib.contextmanager
def motors_off_on_exit(stop_fn: Callable[[], object]) -> Iterator[None]:
    stop = _once(stop_fn)
    try:
        yield
    finally:
        stop()


def exit_cleanly_on_signals(
    signals: tuple[int, ...] = DEFAULT_SIGNALS,
    registrar: Callable[..., object] = signal.signal,
) -> None:
    """For processes with nothing to stop but hardware to release (camera, mic): turn SIGTERM,
    SIGINT and SIGHUP into SystemExit(0) so `finally` blocks run. Python's default SIGTERM action
    kills the process without unwinding."""

    def handler(signum: int, frame: object) -> None:
        sys.exit(0)

    for sig in signals:
        registrar(sig, handler)
