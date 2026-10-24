from rover import config
from rover.drive.car import FakeCar
from rover.drive.navigator import HeadScanner, MarkerNavigator
from rover.drive.vision import VisionReceiver


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


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
    nav = MarkerNavigator(stream)
    car = FakeCar()
    nav.start("210")

    assert not nav.step(car)
    assert car._last["drive"][0] > 0
    assert car._last["drive"] != (0, 0)


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


def test_target_arrival_stops_at_the_configured_distance():
    clock = Clock()
    stream = receiver(clock, [{"id": 210, "distance_m": 0.5, "x": 0.0}])
    nav = MarkerNavigator(stream)
    car = FakeCar()
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
    )
    car = FakeCar()
    nav.start("210")

    assert not nav.step(car)  # full stationary scan -> start turn on the following tick
    assert car._last["drive"] == (0, 0)
    clock.now = 0.05
    assert not nav.step(car)
    assert car._last["drive"] == (-500, 500)
    clock.now = 0.3
    assert not nav.step(car)  # turn ends; scan begins again
    clock.now = 0.4
    assert not nav.step(car)  # scan completes -> start frontier step next tick
    clock.now = 0.45
    assert not nav.step(car)
    assert car._last["drive"] == (config.FORWARD_DUTY, config.FORWARD_DUTY)
