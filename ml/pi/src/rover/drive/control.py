"""Robot state and safety rules, with no HTTP or threads so tests can drive it with a fake clock."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from rover import config, obslog, power
from rover.drive import DRIVE_TIMEOUT_S, HOME_ROOM, LED_STATES, WATCHDOG_S
from rover.drive.car import FakeCar, RealCar
from rover.drive.navigator import Navigator


class UnknownRoom(ValueError):
    pass


class Controller:
    """Holds the state the backend sees. Every command refreshes the watchdog; tick() runs the
    navigator and stops everything once no command has arrived for watchdog_s (follow/face) or,
    while driving to a room, for drive_timeout_s (the backend sends go_to only once)."""

    def __init__(
        self,
        car: FakeCar | RealCar,
        navigator: Navigator,
        clock: Callable[[], float] = time.monotonic,
        watchdog_s: float = WATCHDOG_S,
        drive_timeout_s: float = DRIVE_TIMEOUT_S,
        manual_timeout_s: float = config.MANUAL_TIMEOUT_S,
        led_hold_s: float = config.LED_HOLD_S,
        power_reader: Callable[[], dict | None] = power.read_power,
    ) -> None:
        self._car, self._nav, self._clock, self._watchdog_s = car, navigator, clock, watchdog_s
        self._drive_timeout_s = max(drive_timeout_s, watchdog_s)
        self._manual_timeout_s = max(0.05, manual_timeout_s)
        self._lock = threading.RLock()
        self._room = HOME_ROOM
        self._target: str | None = None
        self._mode = "idle"  # idle, going, manual, following, facing
        self._led = "idle"
        self._last_command: float | None = None
        self._led_hold_s = led_hold_s
        self._led_set_at: float | None = None
        self._power_reader = power_reader
        self._power: dict | None = None
        self._power_at: float | None = None
        car.stop()
        car.led("idle")

    def _fresh(self) -> None:
        self._last_command = self._clock()

    def _halt(self) -> None:
        self._nav.cancel()
        self._car.stop()
        self._target, self._mode = None, "idle"

    def _navigation_failed(self) -> bool:
        failed = getattr(self._nav, "failed", None)
        return bool(failed()) if callable(failed) else False

    def go_to(self, room: str) -> None:
        if config.marker_for_room(room) is None:
            raise UnknownRoom(room)
        with self._lock:
            # A person holding the deadman controller has deliberate, immediate control. Do not
            # let a delayed backend dispatch restart marker navigation underneath that input.
            # stop() remains unconditional and therefore wins over both modes.
            if self._mode == "manual":
                obslog.event("drive.go_to_ignored", room=room, reason="manual_active")
                return
            self._fresh()
            self._target, self._mode = room, "going"
            self._nav.start(room)
        obslog.event("drive.go_to", room=room)

    def follow_marker(self, room: str) -> None:
        """Track a moving ArUco marker while maintaining personal-space standoff."""
        if config.marker_for_room(room) is None:
            raise UnknownRoom(room)
        with self._lock:
            if self._mode == "manual":
                obslog.event("drive.follow_marker_ignored", room=room, reason="manual_active")
                return
            self._fresh()
            self._target, self._mode = room, "following_marker"
            self._nav.start_follow(room)
        obslog.event("drive.follow_marker", room=room)

    def stop(self) -> None:
        with self._lock:
            self._fresh()
            self._halt()
        obslog.event("drive.stop")

    def manual_drive(self, left: int, right: int) -> None:
        """Manual control wins over autonomous motion; it expires unless continuously refreshed."""
        with self._lock:
            self._nav.cancel()
            self._target, self._mode = None, "manual"
            self._fresh()
            self._car.drive(left, right)
        obslog.event("drive.manual", left=left, right=right)

    def set_led(self, state: str) -> None:
        if state not in LED_STATES:
            raise ValueError(state)
        with self._lock:
            self._led = state
            self._led_set_at = self._clock()
            self._car.led(state)
        obslog.event("drive.led", state=state)

    def follow(self) -> None:
        """Flag only: following needs the camera loop, so the wheels never move for it."""
        self._set_mode("following")

    def face(self) -> None:
        """Flag only: turning towards a person needs the camera loop."""
        self._set_mode("facing")

    def _set_mode(self, mode: str) -> None:
        with self._lock:
            self._fresh()
            self._halt()
            self._mode = mode

    def _expire_led(self) -> None:
        """Nothing refreshed a lit LED for led_hold_s: its call is over (or the backend is gone)."""
        if self._led == "idle" or self._led_set_at is None:
            return
        if self._clock() - self._led_set_at > self._led_hold_s:
            print(f"drive: led {self._led} not refreshed for {self._led_hold_s:.0f}s, idle")
            obslog.event("drive.led_expired", state=self._led, hold_s=self._led_hold_s)
            self._led = "idle"
            self._car.led("idle")

    def _read_power(self) -> dict | None:
        now = self._clock()
        if self._power_at is None or now - self._power_at >= config.POWER_CACHE_S:
            try:
                self._power = self._power_reader()
            except Exception:  # noqa: BLE001 - a health probe must not break /snapshot
                self._power = None
            self._power_at = now
        return self._power

    def tick(self) -> None:
        with self._lock:
            self._expire_led()
            if self._mode == "idle":
                return
            if self._mode == "going":
                limit = self._drive_timeout_s
            elif self._mode == "following_marker":
                limit = config.FOLLOW_MARKER_TIMEOUT_S
            elif self._mode == "manual":
                limit = self._manual_timeout_s
            else:
                limit = self._watchdog_s
            if self._clock() - (self._last_command or 0.0) > limit:
                print(f"drive: no fresh command for {limit:.0f}s, stopping")
                obslog.event("drive.watchdog_stop", mode=self._mode, target=self._target)
                self._halt()
                self._led = "idle"
                self._car.led("idle")
                return
            if self._mode in ("going", "following_marker") and self._target is not None:
                if self._nav.step(self._car):
                    self._room = self._target
                    obslog.event("drive.arrived", room=self._room)
                    self._halt()
                elif self._navigation_failed():
                    # Search exhausted its own bounded budget. Stop at the last confirmed room;
                    # never turn a failed exploration into a fake arrival at the target.
                    print("drive: navigation failed, stopped without arrival")
                    obslog.event("drive.navigation_failed", target=self._target)
                    self._halt()

    def snapshot(self) -> dict[str, Any]:
        battery = self._car.battery()
        with self._lock:
            reading = self._read_power()
            flags = (
                None
                if reading is None
                else {k: v for k, v in reading.items() if k != "wifi_rssi_dbm"}
            )
            age = None if self._last_command is None else self._clock() - self._last_command
            return {
                "room": self._room,
                "target": self._target,
                "mode": self._mode,
                "moving": self._mode in ("going", "manual"),
                "following": self._mode == "following_marker",
                "battery": battery,
                "led": self._led,
                "last_command_age_s": age,
                "motors_failed": self._car.motors_failed,
                "power": flags,
                "wifi_rssi_dbm": None if reading is None else reading.get("wifi_rssi_dbm"),
            }


def run_loop(ctl: Controller, stop: threading.Event) -> None:
    """Tick the controller at DRIVE_LOOP_HZ until stop is set."""
    while not stop.wait(1.0 / config.DRIVE_LOOP_HZ):
        ctl.tick()
