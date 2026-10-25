import pytest

from rover import config
from rover.drive.car import FakeCar
from rover.drive.navigator import HeadScanner, MarkerNavigator
from rover.drive.vision import VisionReceiver


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Car(FakeCar):
    """FakeCar with a settable ultrasonic and IR line reading."""

    def __init__(self, distance=300.0, line=2):
        super().__init__()
        self.distance, self.line_bits = distance, line

    def distance_cm(self):
        return self.distance

    def line(self):
        return self.line_bits


def receiver(clock, markers):
    stream = VisionReceiver(clock=clock)
    assert stream.ingest({"markers": markers})
    return stream


def test_target_marker_wins_over_a_closer_distractor():
    clock = Clock()
    stream = receiver(
        clock,
        [
            {"id": 208, "distance_m": 0.2, "x": 0.0},
            {"id": 210, "distance_m": 2.0, "x": 0.3},
        ],
    )
    nav = MarkerNavigator(stream, scanner=HeadScanner(clock), clock=clock)
    car = FakeCar()
    nav.start("210")

    assert not nav.step(car)  # head turns to the approach pose first
    assert car._last["drive"] == (0, 0)
    clock.now = config.HEAD_SETTLE_S
    assert not nav.step(car)
    assert car._last["drive"][0] > 0
    assert car._last["drive"] != (0, 0)


def test_approach_stops_for_an_obstacle_and_resumes_when_clear():
    clock = Clock()
    stream = receiver(clock, [{"id": 210, "distance_m": 2.0, "x": 0.0}])
    nav = MarkerNavigator(stream, scanner=HeadScanner(clock), clock=clock)
    car = Car(distance=config.STOP_DISTANCE_CM - 1)
    nav.start("210")
    nav.step(car)
    clock.now = config.HEAD_SETTLE_S

    assert not nav.step(car)
    assert car._last["drive"] == (0, 0)
    car.distance = 300.0
    assert not nav.step(car)
    assert car._last["drive"] == (config.FORWARD_DUTY, config.FORWARD_DUTY)


def test_missing_or_stale_target_stops_wheels_and_sweeps_head():
    clock = Clock()
    stream = receiver(clock, [{"id": 208, "distance_m": 2.0, "x": 0.0}])
    nav = MarkerNavigator(
        stream,
        scanner=HeadScanner(clock, pans=(70, 110), tilts=(80, 100), dwell_s=0.5),
    )
    car = FakeCar()
    nav.start("210")

    assert not nav.step(car)
    assert car._last["drive"] == (0, 0)
    assert car._last["head"] == (70, 80)
    clock.now = 0.5
    assert not nav.step(car)
    assert car._last["drive"] == (0, 0)
    assert car._last["head"] == (110, 80)
    clock.now = 1.0
    assert not nav.step(car)
    assert car._last["drive"] == (0, 0)


def test_target_arrival_stops_at_the_configured_distance_even_when_blocked():
    clock = Clock()
    stream = receiver(clock, [{"id": 210, "distance_m": 0.5, "x": 0.0}])
    nav = MarkerNavigator(stream)
    car = Car(distance=1.0)
    nav.start("210")

    assert nav.step(car)
    assert car._last["drive"] == (0, 0)


def test_malformed_vision_never_causes_motion():
    clock = Clock()
    stream = receiver(clock, [{"id": 210, "distance_m": "not-a-number", "x": 0.0}])
    nav = MarkerNavigator(stream)
    car = FakeCar()
    nav.start("210")

    assert not nav.step(car)
    assert car._last["drive"] == (0, 0)


def test_scanner_dwells_on_the_last_pose_before_the_sweep_is_done():
    clock = Clock()
    car = FakeCar()
    scanner = HeadScanner(clock, pans=(30, 150), tilts=(120,), dwell_s=0.5)

    assert not scanner.step(car)
    assert car._last["head"] == (30, 120)
    clock.now = 0.5
    assert not scanner.step(car)
    assert car._last["head"] == (150, 120)
    clock.now = 0.9
    assert not scanner.step(car)  # the right-hand view still gets its full dwell
    clock.now = 1.0
    assert scanner.step(car)


def test_missing_target_searches_with_stationary_scan_then_turns_and_advances():
    clock = Clock()
    stream = receiver(clock, [{"id": 208, "distance_m": 2.0, "x": 0.0}])
    nav = MarkerNavigator(
        stream,
        scanner=HeadScanner(clock, pans=(90,), tilts=(90,), dwell_s=0.1),
        clock=clock,
        search_turn_duty=500,
        search_turn_s=0.2,
        search_turns_per_lap=1,
        search_advance_s=0.2,
        line_follow=False,
    )
    car = FakeCar()
    nav.start("210")

    assert not nav.step(car)  # head to the only scan pose
    assert car._last["drive"] == (0, 0)
    clock.now = 0.1
    assert not nav.step(car)  # its dwell is over: the turn starts on the following tick
    clock.now = 0.15
    assert not nav.step(car)
    assert car._last["drive"] == (-500, 500)
    clock.now = 0.35
    assert not nav.step(car)  # turn ends; scan begins again
    clock.now = 0.4
    assert not nav.step(car)
    clock.now = 0.5
    assert not nav.step(car)  # scan completes -> start frontier step next tick
    clock.now = 0.55
    assert not nav.step(car)
    assert car._last["drive"] == (config.FORWARD_DUTY, config.FORWARD_DUTY)


@pytest.mark.parametrize("pan, turn", [(30, (-500, 500)), (150, (500, -500))])
def test_sideways_sighting_turns_the_body_toward_it_never_forward(pan, turn):
    clock = Clock()
    stream = receiver(clock, [])
    nav = MarkerNavigator(
        stream,
        scanner=HeadScanner(clock, pans=(pan,), tilts=(120,), dwell_s=0.5),
        clock=clock,
        search_turn_duty=500,
        search_turns_per_lap=0,
    )
    car = FakeCar()
    nav.start("210")
    assert not nav.step(car)
    assert car._last["head"] == (pan, 120)

    clock.now = 0.3
    assert stream.ingest({"markers": [{"id": 210, "distance_m": 1.8, "x": 0.0}]})
    assert not nav.step(car)
    assert car._last["head"] == (config.PAN_CENTER, config.TILT_APPROACH)
    assert car._last["drive"] == (0, 0)
    clock.now = 0.4
    assert stream.ingest({"markers": [{"id": 210, "distance_m": 1.8, "x": 0.0}]})
    assert not nav.step(car)  # a frame from before the head turned is not steered on
    assert car._last["drive"] == (0, 0)
    clock.now = 0.8
    assert stream.ingest({"markers": []})
    assert not nav.step(car)
    assert car._last["drive"] == turn


@pytest.mark.parametrize("bits", [2, 6, 4, 3, 1, 0, 7, None])
def test_hallway_step_follows_the_tape_and_stops_off_it(bits):
    clock = Clock()
    stream = receiver(clock, [])
    nav = MarkerNavigator(
        stream,
        scanner=HeadScanner(clock, pans=(90,), tilts=(90,), dwell_s=0.1),
        clock=clock,
        search_turns_per_lap=0,
        search_advance_s=1.0,
        line_follow=True,
    )
    car = Car(line=bits)
    nav.start("210")
    nav.step(car)
    clock.now = 0.1
    nav.step(car)  # scan done -> forward step with the head level
    clock.now = config.HEAD_SETTLE_S + 0.05
    assert stream.ingest({"markers": []})

    assert not nav.step(car)
    if bits in (0, 7, None):
        assert car._last["drive"] == (0, 0)
    else:
        correction = config.LINE_GAIN * config.LINE_ERROR[bits]
        assert car._last["drive"] == (
            int(config.LINE_DUTY + correction),
            int(config.LINE_DUTY - correction),
        )
