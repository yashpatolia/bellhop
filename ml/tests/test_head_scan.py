from rover.drive.__main__ import head_test
from rover.drive.car import FakeCar
from rover.drive.navigator import HeadScanner


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_scanner_never_drives_wheels_and_cycles_configured_positions():
    clock, car = Clock(), FakeCar()
    scan = HeadScanner(clock, pans=(60, 90, 120), tilt=80, dwell_s=0.5)
    scan.step(car)
    assert car._last["head"] == (60, 80)
    assert "drive" not in car._last
    clock.now = 0.5
    scan.step(car)
    assert car._last["head"] == (90, 80)
    assert "drive" not in car._last


def test_head_test_only_stops_wheels_and_moves_head():
    car = FakeCar()
    head_test(car, sleep=lambda _: None)
    assert car._last["drive"] == (0, 0)
    assert car._last["head"] == (90, 90)
