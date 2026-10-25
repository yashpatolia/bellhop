"""How the robot gets to a room. The controller only knows this small interface."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from typing import Protocol

from rover import config
from rover.drive.car import FakeCar, RealCar
from rover.drive.vision import VisionReceiver


class Navigator(Protocol):
    def start(self, room: str) -> None:
        """Begin heading for room (a repeat call for the same room must not restart)."""

    def start_follow(self, room: str) -> None:
        """Begin maintaining standoff from a moving marker without declaring arrival."""

    def step(self, car: FakeCar | RealCar) -> bool:
        """Command the car for one loop tick; True once the room is reached."""

    def cancel(self) -> None:
        """Forget the goal."""

    def failed(self) -> bool:
        """True only when navigation stopped without reaching the requested room."""


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

    def start_follow(self, room: str) -> None:
        # Simulation has no marker stream; retaining normal travel behavior keeps its test
        # contract useful without claiming it models person-following.
        self.start(room)

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

    def failed(self) -> bool:
        return False


class HeadScanner:
    """Sweep the camera head while stationary, using only deployment-configured angles."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        pans: tuple[int, ...] = config.HEAD_SCAN_PANS,
        tilts: tuple[int, ...] = config.HEAD_SCAN_TILTS,
        dwell_s: float = config.HEAD_SCAN_DWELL_S,
    ) -> None:
        self._clock = clock
        self._positions = tuple((pan, tilt) for tilt in tilts for pan in pans)
        self._dwell_s = dwell_s
        self._next_at = 0.0
        self._index = 0
        # The process cannot know where a prior manual process left the head, so first marker
        # acquisition safely re-centres before its camera-relative x value steers the chassis.
        self._off_center = True

    def reset(self) -> None:
        self._next_at = 0.0
        self._index = 0

    def needs_centering(self) -> bool:
        return self._off_center

    def centered(self) -> None:
        self._off_center = False

    def step(self, car: FakeCar | RealCar) -> bool:
        """Move to one position, returning True only after a complete sweep."""
        now = self._clock()
        if now < self._next_at:
            return False
        pan, tilt = self._positions[self._index]
        car.look_at(pan, tilt)
        self._off_center = (pan, tilt) != (config.PAN_CENTER, config.TILT_DRIVE)
        self._index = (self._index + 1) % len(self._positions)
        self._next_at = now + self._dwell_s
        return self._index == 0


class MarkerNavigator:
    """Steer only from fresh camera observations of the requested ArUco marker.

    It never follows a closer non-target marker. Absent, stale or malformed vision first stops
    the wheels and sweeps the camera head. A bounded active search can then turn in place and
    make short ultrasonic-guarded frontier steps beyond the initial camera view. Room names are
    resolved through deployment configuration.
    """

    def __init__(
        self,
        vision: VisionReceiver,
        marker_for_room: Callable[[str], int | None] = config.marker_for_room,
        scanner: HeadScanner | None = None,
        clock: Callable[[], float] = time.monotonic,
        active_search: bool = config.ACTIVE_MARKER_SEARCH,
        search_turn_duty: int = config.SEARCH_TURN_DUTY,
        search_turn_s: float = config.SEARCH_TURN_S,
        search_turns_per_lap: int = config.SEARCH_TURNS_PER_LAP,
        search_advance_s: float = config.SEARCH_ADVANCE_S,
        search_max_s: float = config.SEARCH_MAX_S,
    ) -> None:
        self._vision, self._marker_for_room = vision, marker_for_room
        self._marker_id: int | None = None
        self._scanner = scanner or HeadScanner()
        self._clock, self._active_search = clock, active_search
        self._turn_duty, self._turn_s = search_turn_duty, search_turn_s
        self._turns_per_lap, self._advance_s, self._max_search_s = (
            search_turns_per_lap,
            search_advance_s,
            search_max_s,
        )
        self._search_phase = "scan"  # scan -> turn -> advance
        self._phase_started = 0.0
        self._search_started: float | None = None
        self._turns = 0
        self._search_expired = False
        self._recenter_until: float | None = None
        self._following = False
        self._holding_distance = False

    def start(self, room: str) -> None:
        self._begin(room, following=False)

    def start_follow(self, room: str) -> None:
        self._begin(room, following=True)

    def _begin(self, room: str, *, following: bool) -> None:
        # Never use a target frame captured before this command.  The physical marker might
        # have been moved since the user selected it, and a stale close distance would otherwise
        # turn a new drive into a false instant arrival.
        self._vision.clear()
        self._marker_id = self._marker_for_room(room)
        self._search_expired = False
        self._recenter_until = None
        self._following = following
        self._holding_distance = False
        self._reset_search()

    def cancel(self) -> None:
        self._marker_id = None
        self._recenter_until = None
        self._following = False
        self._holding_distance = False
        self._reset_search()

    def failed(self) -> bool:
        return self._search_expired

    def _reset_search(self) -> None:
        self._scanner.reset()
        self._search_phase, self._phase_started = "scan", 0.0
        self._search_started, self._turns = None, 0

    @staticmethod
    def _forward_clear(car: FakeCar | RealCar) -> bool:
        """Moving forward without a valid clear ultrasonic reading is never safe."""
        distance = car.distance_cm()
        return (
            isinstance(distance, int | float)
            and not isinstance(distance, bool)
            and math.isfinite(distance)
            and distance >= config.STOP_DISTANCE_CM
        )

    def _head_ready(self, car: FakeCar | RealCar) -> bool:
        """Make a marker's x coordinate body-relative before it can steer the wheels."""
        now = self._clock()
        if self._recenter_until is not None:
            car.stop()
            if now < self._recenter_until:
                return False
            self._recenter_until = None
        if self._scanner.needs_centering():
            car.stop()
            car.look_ahead()
            self._scanner.centered()
            self._recenter_until = now + config.HEAD_RECENTER_SETTLE_S
            return False
        return True

    def _search(self, car: FakeCar | RealCar) -> bool:
        now = self._clock()
        if self._search_started is None:
            self._search_started = now
        if now - self._search_started >= self._max_search_s:
            car.stop()
            if not self._search_expired:
                print(f"drive: marker search timed out after {self._max_search_s:g}s, stopped")
                self._search_expired = True
            return False
        if not self._active_search:
            car.stop()
            self._scanner.step(car)
            return False
        if self._search_phase == "scan":
            car.stop()
            if self._scanner.step(car):
                # Body turns must begin with the camera facing forward so a target acquired
                # during the turn has a body-relative x coordinate for steering.
                car.look_ahead()
                self._scanner.centered()
                self._search_phase, self._phase_started = (
                    ("advance", now) if self._turns >= self._turns_per_lap else ("turn", now)
                )
            return False
        if self._search_phase == "turn":
            if now - self._phase_started < self._turn_s:
                car.drive(-self._turn_duty, self._turn_duty)
                return False
            car.stop()
            self._turns += 1
            self._scanner.reset()
            self._search_phase = "scan"
            return False
        # One complete turn produced no target. Advance only a short bounded distance, and only
        # if ultrasonic says the way ahead is clear, then repeat the scan from a new frontier.
        if not self._forward_clear(car):
            car.stop()
            self._turns = 0
            self._scanner.reset()
            self._search_phase = "scan"
            return False
        if now - self._phase_started < self._advance_s:
            car.drive(config.FORWARD_DUTY, config.FORWARD_DUTY)
            return False
        car.stop()
        self._turns = 0
        self._scanner.reset()
        self._search_phase = "scan"
        return False

    def step(self, car: FakeCar | RealCar) -> bool:
        marker_id = self._marker_id
        if marker_id is None:
            return self._follow_search(car) if self._following else self._search(car)
        markers = self._vision.markers()
        if markers is None:
            return self._follow_search(car) if self._following else self._search(car)
        target = next((row for row in markers if row.get("id") == marker_id), None)
        if target is None:
            return self._follow_search(car) if self._following else self._search(car)
        # A current target always wins over a previous search phase. Its current camera x value
        # is used immediately; no landmark ID ordering or hardcoded room relation is assumed.
        try:
            distance, x = float(target["distance_m"]), float(target["x"])
        except (KeyError, TypeError, ValueError):
            return self._search(car)
        if not (0.0 < distance < float("inf")) or not (-1.0 <= x <= 1.0):
            return self._search(car)
        if not self._head_ready(car):
            return False
        if self._following:
            return self._follow_target(car, distance, x)
        if distance <= config.ARRIVE_DISTANCE_M:
            car.stop()
            return True
        self._reset_search()
        if not self._forward_clear(car):
            car.stop()
            return False
        correction = config.STEER_GAIN * x
        car.drive(config.FORWARD_DUTY + correction, config.FORWARD_DUTY - correction)
        return False

    def _follow_search(self, car: FakeCar | RealCar) -> bool:
        """A lost moving person causes a stationary head scan, never blind exploration."""
        car.stop()
        self._scanner.step(car)
        return False

    def _follow_target(self, car: FakeCar | RealCar, distance: float, x: float) -> bool:
        """Maintain configured personal space; following deliberately never signals arrival."""
        if distance <= config.FOLLOW_MARKER_STOP_DISTANCE_M or (
            self._holding_distance and distance <= config.FOLLOW_MARKER_RESUME_DISTANCE_M
        ):
            self._holding_distance = True
            car.stop()
            return False
        self._holding_distance = False
        if not self._forward_clear(car):
            car.stop()
            return False
        correction = config.STEER_GAIN * x
        car.drive(config.FORWARD_DUTY + correction, config.FORWARD_DUTY - correction)
        return False
