"""Robot state and safety rules, with no HTTP or threads so tests can drive it with a fake clock."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from rover import config, obslog, power
from rover.drive import DRIVE_TIMEOUT_S, HOME_ROOM, LED_STATES, ROOMS, WATCHDOG_S
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
        led_hold_s: float = config.LED_HOLD_S,
        power_reader: Callable[[], dict | None] = power.read_power,
    ) -> None:
        self._car, self._nav, self._clock, self._watchdog_s = car, navigator, clock, watchdog_s
        self._drive_timeout_s = max(drive_timeout_s, watchdog_s)
        self._lock = threading.RLock()
        self._room = HOME_ROOM
        self._target: str | None = None
        self._mode = "idle"  # idle, going, following, facing
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

    def go_to(self, room: str) -> None:
        if room not in ROOMS:
            raise UnknownRoom(room)
        with self._lock:
            self._fresh()
            self._target, self._mode = room, "going"
            self._nav.start(room)
        obslog.event("drive.go_to", room=room)

    def stop(self) -> None:
        with self._lock:
            self._fresh()
            self._halt()
        obslog.event("drive.stop")

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
            limit = self._drive_timeout_s if self._mode == "going" else self._watchdog_s
            if self._clock() - (self._last_command or 0.0) > limit:
                print(f"drive: no fresh command for {limit:.0f}s, stopping")
                obslog.event("drive.watchdog_stop", mode=self._mode, target=self._target)
                self._halt()
                self._led = "idle"
                self._car.led("idle")
                return
            if self._mode == "going" and self._target is not None:
                if self._nav.step(self._car):
                    self._room = self._target
                    obslog.event("drive.arrived", room=self._room)
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
                "moving": self._mode == "going",
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
