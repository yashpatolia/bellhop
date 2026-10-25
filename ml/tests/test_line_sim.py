"""2D kinematic sim of hallway mode on a tape map, run against the real MarkerNavigator.

The rover follows the hallway tape, stops at every room branch to look both ways, crosses it,
and turns toward the target's door. Speeds and sizes below are guesses, so this proves the
navigator's logic and the tape geometry, not traction on cardboard or real sensor readings.
"""

import math

import pytest

from rover import config
from rover.drive.car import FakeCar
from rover.drive.navigator import HeadScanner, MarkerNavigator
from rover.drive.vision import VisionReceiver

TICK_S = 1 / config.DRIVE_LOOP_HZ
# Guesses, not measurements: update them from the real car.
SPEED_PER_DUTY = 0.25 / 1000  # m/s per unit of motor duty
TRACK_M = 0.14  # left to right wheel distance
SENSOR_AHEAD_M = 0.09  # IR sensors ahead of the body centre
SENSOR_GAP_M = 0.015  # between neighbouring IR sensors: measure yours
TAPE_M = 0.019  # hallway tape: at least SENSOR_GAP_M, below 2 * SENSOR_GAP_M
BRANCH_M = 0.05  # branch tape where it crosses the hallway line
PAST_FAR_SIDE_M = 0.04  # how far each branch runs past the far side of the hallway line
DOOR_M = 1.2  # door frames this far either side of the line
MARKER_ABOVE_CAMERA_M = 1.3
HALF_FOV = math.radians(34)
MIN_DECODE_PX = 20  # marker width on screen, foreshortening included, below which ArUco fails


def branch(x, side):
    """Tape from the door (side +1 left, -1 right) across the hallway line, as x0, x1, y0, y1."""
    near, far = side * DOOR_M, -side * (TAPE_M / 2 + PAST_FAR_SIDE_M)
    return (x - BRANCH_M / 2, x + BRANCH_M / 2, min(near, far), max(near, far))


HALLWAY = (-0.5, 4.0, -TAPE_M / 2, TAPE_M / 2)
BRANCHES = {201: (1.0, 1), 202: (2.0, -1), 203: (3.0, 1)}  # marker id: (x, side)


class SimCar(FakeCar):
    """FakeCar on a pose (x along the hallway, y to the left, heading counter-clockwise)."""

    def __init__(self, tape, x=0.0, y=0.0, heading_deg=0.0):
        super().__init__()
        self.tape, self.x, self.y = tape, x, y
        self.heading = math.radians(heading_deg)
        self.duties = (0, 0)
        self.bits_read = []

    def _log(self, what, value):  # quiet: the sim runs thousands of ticks
        self._last[what] = value
        if what == "drive":
            self.duties = value

    def move(self, dt):
        left, right = (SPEED_PER_DUTY * duty for duty in self.duties)
        speed, turn = (left + right) / 2, (right - left) / TRACK_M
        self.heading += turn * dt
        self.x += speed * math.cos(self.heading) * dt
        self.y += speed * math.sin(self.heading) * dt

    def _on_tape(self, px, py):
        return any(x0 <= px <= x1 and y0 <= py <= y1 for x0, x1, y0, y1 in self.tape)

    def line(self):
        cos, sin = math.cos(self.heading), math.sin(self.heading)
        bits = 0
        for side in (1, 0, -1):  # left, middle, right
            px = self.x + SENSOR_AHEAD_M * cos - side * SENSOR_GAP_M * sin
            py = self.y + SENSOR_AHEAD_M * sin + side * SENSOR_GAP_M * cos
            bits = bits << 1 | self._on_tape(px, py)
        self.bits_read.append(bits)
        return bits

    def head_yaw(self):
        pan = self._last.get("head", (config.PAN_CENTER, 0))[0]
        return math.radians(config.PAN_CENTER - pan) * config.HEAD_PAN_RIGHT_SIGN

    def frame(self):
        """What the camera decodes from this pose: door markers face across the hallway."""
        rows = []
        camera = self.heading + self.head_yaw()
        for marker_id, (mx, side) in BRANCHES.items():
            my = side * DOOR_M
            dx, dy = mx - self.x, my - self.y
            floor, bearing = math.hypot(dx, dy), math.atan2(dy, dx) - camera
            off_axis = math.atan2(math.sin(bearing), math.cos(bearing))
            facing = side * dy / floor  # cosine of the view angle off the marker's face
            distance = math.hypot(floor, MARKER_ABOVE_CAMERA_M)
            width_px = config.MARKER_FOCAL_PX * config.MARKER_SIZE_M / distance * facing
            if abs(off_axis) < HALF_FOV and facing > 0 and width_px >= MIN_DECODE_PX:
                rows.append({"id": marker_id, "distance_m": distance, "x": -off_axis / HALF_FOV})
        return {"markers": rows}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def run(car, room, seconds, monkeypatch):
    """Tick the navigator at the drive loop rate; returns (arrived, look positions)."""
    monkeypatch.setattr(config, "ARRIVE_DISTANCE_M", 1.6)  # hallway profile value
    clock = Clock()
    vision = VisionReceiver(clock=clock)
    nav = MarkerNavigator(
        vision,
        marker_for_room=int,
        scanner=HeadScanner(clock, pans=(30, 150), tilts=(125,), dwell_s=0.5),
        clock=clock,
        search_turns_per_lap=0,
        search_advance_s=5.0,
        search_max_s=seconds,
        line_follow=True,
    )
    nav.start(room)
    looks = []
    while clock.now < seconds:
        vision.ingest(car.frame())
        if nav.step(car):
            return True, looks
        if car.duties == (0, 0) and car.head_yaw():
            looks.append(car.x)
        car.move(TICK_S)
        clock.now += TICK_S
    return False, looks


def test_hallway_run_checks_each_branch_and_parks_at_the_target_door(monkeypatch):
    car = SimCar([HALLWAY] + [branch(x, side) for x, side in BRANCHES.values()])

    arrived, looks = run(car, "203", 150, monkeypatch)

    assert arrived
    assert any(abs(look + SENSOR_AHEAD_M - BRANCHES[201][0]) < 0.1 for look in looks)
    assert 0 not in car.bits_read and 5 not in car.bits_read  # never lost the hallway tape
    door_x, side = BRANCHES[203]
    assert math.hypot(door_x - car.x, side * DOOR_M - car.y) < 1.0  # parked by door 203


@pytest.mark.parametrize("y, heading_deg", [(0.005, 5.0), (-0.005, -5.0)])
def test_tape_following_recentres_without_losing_the_tape(y, heading_deg, monkeypatch):
    car = SimCar([HALLWAY], y=y, heading_deg=heading_deg)

    run(car, "250", 8, monkeypatch)  # no such marker: just follow the tape

    assert car.x > 0.5
    assert 0 not in car.bits_read
    assert abs(car.y) < TAPE_M / 2


def test_tape_wider_than_the_sensors_stops_instead_of_driving_blind(monkeypatch):
    car = SimCar([(-0.5, 4.0, -0.024, 0.024)])  # 48 mm gaffer: all three sensors always on it

    run(car, "250", 8, monkeypatch)

    blind_m = SPEED_PER_DUTY * config.LINE_DUTY * config.LINE_JUNCTION_MAX_S
    assert car.x < blind_m + 0.05
