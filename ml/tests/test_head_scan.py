from rover.drive.__main__ import head_test
from rover.drive.car import FakeCar, head_slew_positions
from rover.drive.navigator import HeadScanner


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_scanner_never_drives_wheels_and_cycles_configured_positions():
    clock, car = Clock(), FakeCar()
    scan = HeadScanner(clock, pans=(60, 90, 120), tilts=(80, 100), dwell_s=0.5)
    scan.step(car)
    assert car._last["head"] == (60, 80)
    assert "drive" not in car._last
    clock.now = 0.5
    scan.step(car)
    assert car._last["head"] == (90, 80)
    assert "drive" not in car._last
    clock.now = 1.0
    scan.step(car)
    assert car._last["head"] == (120, 80)
    clock.now = 1.5
    scan.step(car)
    # The second row reverses direction, keeping the pan at 120 while tilt changes.
    assert car._last["head"] == (120, 100)
    assert "drive" not in car._last


def test_head_test_only_stops_wheels_and_moves_head():
    car = FakeCar()
    head_test(car, sleep=lambda _: None)
    assert car._last["drive"] == (0, 0)
    assert car._last["head"] == (90, 90)


def test_head_slew_limits_each_axis_delta_and_reaches_the_target():
    positions = head_slew_positions((90, 90), (45, 95), maximum_step_degrees=5)
    assert positions[-1] == (45, 95)
    previous = (90, 90)
    for position in positions:
        assert abs(position[0] - previous[0]) <= 5
        assert abs(position[1] - previous[1]) <= 5
        previous = position
