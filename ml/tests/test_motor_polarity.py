from rover import config
from rover.drive.car import motor_duties


def test_default_motor_polarity_preserves_logical_directions(monkeypatch):
    monkeypatch.setattr(config, "MOTOR_FORWARD_SIGN", 1)
    assert motor_duties(1200, 800) == (1200, 800)


def test_reverse_motor_polarity_reverses_both_sides_and_preserves_steering(monkeypatch):
    monkeypatch.setattr(config, "MOTOR_FORWARD_SIGN", -1)
    assert motor_duties(1200, 800) == (-1200, -800)
