"""How the robot gets to a room. The controller only knows this small interface."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from rover import config
from rover.drive.car import FakeCar, RealCar
from rover.drive.vision import VisionReceiver


class Navigator(Protocol):
    def start(self, room: str) -> None:
        """Begin heading for room (a repeat call for the same room must not restart)."""

    def step(self, car: FakeCar | RealCar) -> bool:
        """Command the car for one loop tick; True once the room is reached."""

    def cancel(self) -> None:
        """Forget the goal."""


class SimNavigator:
    """Drives straight ahead for TRAVEL_S seconds and calls that arrival.

    A stand-in until marker navigation is wired in: it never looks at a marker, so it proves
    the server, watchdog and obstacle stop, not real wayfinding. Forward motion halts while the
    ultrasonic reads closer than config.STOP_DISTANCE_CM.
    """

    TRAVEL_S = 2.0

    def __init__(
        self, clock: Callable[[], float] = time.monotonic, travel_s: float = TRAVEL_S
    ) -> None:
        self._clock, self._travel_s = clock, travel_s
        self._room: str | None = None
        self._started = 0.0

    def start(self, room: str) -> None:
        if room != self._room:
            self._room, self._started = room, self._clock()

    def step(self, car: FakeCar | RealCar) -> bool:
        if self._room is None:
            return True
        if self._clock() - self._started >= self._travel_s:
            car.stop()
            return True
        distance = car.distance_cm()
        if distance is not None and distance < config.STOP_DISTANCE_CM:
            car.stop()
        else:
            car.drive(config.FORWARD_DUTY, config.FORWARD_DUTY)
        return False

    def cancel(self) -> None:
        self._room = None


class HeadScanner:
    """Sweep the camera head while stationary, using only deployment-configured angles."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        pans: tuple[int, ...] = config.HEAD_SCAN_PANS,
        tilt: int = config.HEAD_SCAN_TILT,
        dwell_s: float = config.HEAD_SCAN_DWELL_S,
    ) -> None:
        self._clock, self._pans, self._tilt = clock, pans, tilt
        self._dwell_s = dwell_s
        self._next_at = 0.0
        self._index = 0

    def reset(self) -> None:
        self._next_at = 0.0
        self._index = 0

    def step(self, car: FakeCar | RealCar) -> None:
        now = self._clock()
        if now < self._next_at:
            return
        pan = self._pans[self._index]
        car.look_at(pan, self._tilt)
        self._index = (self._index + 1) % len(self._pans)
        self._next_at = now + self._dwell_s


class MarkerNavigator:
    """Steer only from fresh camera observations of the requested ArUco marker.

    It never follows a closer non-target marker. Absent, stale or malformed vision stops the
    wheels and sweeps the camera head in safe configured positions; it never blindly drives.
    Room names are resolved through deployment configuration.
    """

    def __init__(
        self,
        vision: VisionReceiver,
        marker_for_room: Callable[[str], int | None] = config.marker_for_room,
        scanner: HeadScanner | None = None,
    ) -> None:
        self._vision, self._marker_for_room = vision, marker_for_room
        self._marker_id: int | None = None
        self._scanner = scanner or HeadScanner()

    def start(self, room: str) -> None:
        self._marker_id = self._marker_for_room(room)
        self._scanner.reset()

    def cancel(self) -> None:
        self._marker_id = None
        self._scanner.reset()

    def _search(self, car: FakeCar | RealCar) -> bool:
        car.stop()
        self._scanner.step(car)
        return False

    def step(self, car: FakeCar | RealCar) -> bool:
        marker_id = self._marker_id
        if marker_id is None:
            return self._search(car)
        markers = self._vision.markers()
        if markers is None:
            return self._search(car)
        target = next((row for row in markers if row.get("id") == marker_id), None)
        if target is None:
            return self._search(car)
        try:
            distance, x = float(target["distance_m"]), float(target["x"])
        except (KeyError, TypeError, ValueError):
            return self._search(car)
        if not (0.0 < distance < float("inf")) or not (-1.0 <= x <= 1.0):
            return self._search(car)
        if distance <= config.ARRIVE_DISTANCE_M:
            car.stop()
            return True
        correction = config.STEER_GAIN * x
        car.drive(config.FORWARD_DUTY + correction, config.FORWARD_DUTY - correction)
        return False
