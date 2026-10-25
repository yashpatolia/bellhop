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
    """Sweep the camera head while stationary, using only deployment-configured angles.

    Every head move goes through look(), so a marker sighting can be credited to the pose the
    head was really in, and frames taken before a move can be told apart (settling()). The
    pose starts unknown: a prior manual process may have left the head anywhere, so the first
    look() always moves it and waits out the settle time before its x can steer the wheels.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        pans: tuple[int, ...] = config.HEAD_SCAN_PANS,
        tilts: tuple[int, ...] = config.HEAD_SCAN_TILTS,
        dwell_s: float = config.HEAD_SCAN_DWELL_S,
        settle_s: float = config.HEAD_RECENTER_SETTLE_S,
    ) -> None:
        self._clock = clock
        self._positions = tuple((pan, tilt) for tilt in tilts for pan in pans)
        self._dwell_s, self._settle_s = dwell_s, settle_s
        self._next_at = 0.0
        self._index = 0
        self._pose: tuple[int, int] | None = None
        self._moved_at = float("-inf")

    @property
    def pan(self) -> int | None:
        """Last commanded pan; None before the head has been moved."""
        return None if self._pose is None else self._pose[0]

    def look(self, car: FakeCar | RealCar, pan: int, tilt: int) -> None:
        if (pan, tilt) != self._pose:
            car.look_at(pan, tilt)
            self._pose, self._moved_at = (pan, tilt), self._clock()

    def settling(self) -> bool:
        """True just after a head move, while a vision frame may still show the old pose."""
        return self._clock() - self._moved_at < self._settle_s

    def reset(self) -> None:
        self._next_at = 0.0
        self._index = 0

    def step(self, car: FakeCar | RealCar) -> bool:
        """Move to the next position; True once the last one has had its dwell."""
        now = self._clock()
        if now < self._next_at:
            return False
        if self._index == len(self._positions):
            self._index = 0
            return True
        pan, tilt = self._positions[self._index]
        self.look(car, pan, tilt)
        self._index += 1
        self._next_at = now + self._dwell_s
        return False


class MarkerNavigator:
    """Steer only from fresh camera observations of the requested ArUco marker.

    It never follows a non-target marker, however close. Absent, stale or malformed vision first
    stops the wheels and sweeps the camera head. A bounded active search can then turn in place
    and make short ultrasonic-guarded forward steps (along a tape line in hallway mode). A target
    seen by a sideways-panned head turns the body toward it instead of steering on a sideways x.
    Room names are resolved through deployment configuration.
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
        search_face_max_s: float = config.SEARCH_FACE_MAX_S,
        line_follow: bool = config.LINE_FOLLOW,
    ) -> None:
        self._vision, self._marker_for_room = vision, marker_for_room
        self._marker_id: int | None = None
        self._scanner = scanner or HeadScanner(clock)
        self._clock, self._active_search = clock, active_search
        self._turn_duty, self._turn_s = search_turn_duty, search_turn_s
        self._turns_per_lap, self._advance_s, self._max_search_s = (
            search_turns_per_lap,
            search_advance_s,
            search_max_s,
        )
        self._face_max_s, self._line_follow = search_face_max_s, line_follow
        self._search_phase = "scan"  # scan -> turn -> advance
        self._phase_started = 0.0
        self._search_started: float | None = None
        self._turns = 0
        self._turn_sign, self._turn_limit_s = -1, search_turn_s  # -1 left, +1 right
        self._search_expired = False
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
        self._following = following
        self._holding_distance = False
        self._reset_search()

    def cancel(self) -> None:
        self._marker_id = None
        self._following = False
        self._holding_distance = False
        self._reset_search()

    def failed(self) -> bool:
        return self._search_expired

    def _reset_search(self) -> None:
        self._scan_again()
        self._search_started, self._turns = None, 0

    def _scan_again(self) -> None:
        self._scanner.reset()
        self._search_phase, self._phase_started = "scan", 0.0
        self._turn_sign, self._turn_limit_s = -1, self._turn_s

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
                # Body turns must begin with the camera facing forward (tilted up for face-height
                # markers) so a target acquired during the turn has a body-relative x for steering.
                # Forward steps need the head level, because the ultrasonic tilts with it.
                if self._turns >= self._turns_per_lap:
                    self._scanner.look(car, config.PAN_CENTER, config.TILT_DRIVE)
                    self._search_phase = "advance"
                else:
                    self._scanner.look(car, config.PAN_CENTER, config.TILT_APPROACH)
                    self._search_phase = "turn"
                self._phase_started = now
            return False
        if self._search_phase == "turn":
            if now - self._phase_started < self._turn_limit_s:
                duty = self._turn_sign * self._turn_duty
                car.drive(duty, -duty)
                return False
            car.stop()
            self._turns += 1
            self._scan_again()
            return False
        # One complete turn (or none, in a hallway) produced no target. Advance only a short
        # bounded distance, and only while ultrasonic says the way ahead is clear.
        if self._scanner.settling():
            car.stop()
            self._phase_started = now  # the step's time starts once the head is level
            return False
        if not self._forward_clear(car) or now - self._phase_started >= self._advance_s:
            car.stop()
            self._turns = 0
            self._scan_again()
            return False
        if not self._line_follow:
            car.drive(config.FORWARD_DUTY, config.FORWARD_DUTY)
            return False
        bits = car.line()
        error = config.LINE_ERROR.get(bits)
        if error is None:
            print(f"fallback: line sensors read {bits} (0 tape lost, 7 end strip), not advancing")
            car.stop()
            self._turns = 0
            self._scan_again()
            return False
        correction = config.LINE_GAIN * error
        car.drive(config.LINE_DUTY + correction, config.LINE_DUTY - correction)
        return False

    def _target(self, marker_id: int) -> tuple[float, float] | None:
        """(distance_m, x) of the target in the latest fresh frame; None if absent or malformed."""
        markers = self._vision.markers()
        if markers is None:
            return None
        row = next((row for row in markers if row.get("id") == marker_id), None)
        if row is None:
            return None
        try:
            distance, x = float(row["distance_m"]), float(row["x"])
        except (KeyError, TypeError, ValueError):
            return None
        if not (0.0 < distance < float("inf")) or not (-1.0 <= x <= 1.0):
            return None
        return distance, x

    def _face(self, car: FakeCar | RealCar, pan: int) -> bool:
        """A sideways-panned head saw the target: turn the body toward it, head forward."""
        self._reset_search()
        self._turn_sign = (1 if pan > config.PAN_CENTER else -1) * config.HEAD_PAN_RIGHT_SIGN
        self._turn_limit_s = self._face_max_s
        self._search_phase, self._phase_started = "turn", self._clock()
        self._scanner.look(car, config.PAN_CENTER, config.TILT_APPROACH)
        car.stop()
        return False

    def step(self, car: FakeCar | RealCar) -> bool:
        marker_id = self._marker_id
        target = None if marker_id is None else self._target(marker_id)
        if target is None:
            return self._follow_search(car) if self._following else self._search(car)
        if self._scanner.settling():
            car.stop()  # this frame may predate the last head move, so its pose is unknown
            return False
        pan = self._scanner.pan
        if pan is not None and pan != config.PAN_CENTER and not self._following:
            return self._face(car, pan)
        # A current target always wins over a previous search phase. Its current camera x value
        # is used once the head faces forward; no landmark ID ordering or room relation is assumed.
        # A followed person is re-centred on, never turned toward blindly.
        self._reset_search()
        tilt = config.TILT_DRIVE if self._following else config.TILT_APPROACH
        self._scanner.look(car, config.PAN_CENTER, tilt)
        distance, x = target
        if not self._following and distance <= config.ARRIVE_DISTANCE_M:
            car.stop()
            return True
        if self._scanner.settling():
            car.stop()
            return False
        if self._following:
            return self._follow_target(car, distance, x)
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
