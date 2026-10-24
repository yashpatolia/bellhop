"""How the robot gets to a room. The controller only knows this small interface."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from rover import config
from rover.drive.car import FakeCar, RealCar


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
