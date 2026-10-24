from rover.drive.car import FakeCar
from rover.drive.control import Controller
from rover.drive.manual import ManualMixer
from rover.drive.navigator import SimNavigator


class RecordingCar(FakeCar):
    def __init__(self) -> None:
        super().__init__()
        self.commands: list[tuple[int, int]] = []

    def drive(self, left: int, right: int) -> None:
        self.commands.append((left, right))


def test_deadman_is_required_for_a_drive_command():
    mixer = ManualMixer(deadman_button=4, forward_axis=1, turn_axis=0, max_duty=1000)
    assert mixer.event(-32767, 0x02, 1) is None
    assert mixer.event(1, 0x01, 4) == (1000, 1000)
    assert mixer.event(0, 0x01, 4) is None


def test_turn_mixes_wheels_and_deadzone_ignores_small_axis_noise():
    mixer = ManualMixer(deadman_button=4, forward_axis=1, turn_axis=0, deadzone=0.2, max_duty=1000)
    mixer.event(1, 0x01, 4)
    assert mixer.event(1000, 0x02, 0) == (0, 0)
    left, right = mixer.event(32767, 0x02, 0)
    assert left > 0 > right


def test_manual_drive_cancels_navigation_and_blocks_late_dispatch():
    car = RecordingCar()
    controller = Controller(car, SimNavigator())

    controller.manual_drive(400, 400)
    controller.go_to("12")

    assert controller.snapshot()["mode"] == "manual"
    assert controller.snapshot()["target"] is None
    assert car.commands[-1] == (400, 400)

    controller.stop()
    assert controller.snapshot()["mode"] == "idle"
    assert car.commands[-1] == (0, 0)
