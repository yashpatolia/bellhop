"""Wheels, head, ultrasonic, battery and LEDs through Freenove's drivers, or a FakeCar.

Freenove's modules are imported from config.FREENOVE_DIR at runtime (their licence: CC BY-NC-SA
3.0), never copied here. Their adc.py prompts on stdin without a params.json, so the battery is
read directly with the same ADS7830 formula.
"""

from __future__ import annotations

import importlib
import math
import sys
from collections.abc import Callable
from typing import Any

from rover import config

MAX_DUTY = 4095  # Freenove motor duty range is -4095..4095
FAKE_DISTANCE_CM = 300.0  # FakeCar: nothing in the way, so the loop can be tried on the Mac
ADC_ADDRESS = 0x48  # ADS7830 on the Freenove board
ADC_BATTERY_CHANNEL = 2
ADC_READ_TRIES = 5  # two equal reads in a row count as stable
LED_COUNT = 8
LED_BRIGHTNESS = 255
# Freenove's Servo client maps selector 0/1 to PCA9685 channels 8/9 (pan/tilt).
PAN, TILT = "0", "1"


def clamp_duty(duty: float) -> int:
    return int(max(-MAX_DUTY, min(MAX_DUTY, duty)))


def battery_share(volts: float | None) -> float | None:
    if volts is None or not math.isfinite(volts):
        return None
    share = (volts - config.BATTERY_EMPTY_V) / (config.BATTERY_FULL_V - config.BATTERY_EMPTY_V)
    return min(1.0, max(0.0, share))


class FakeCar:
    """Logs each command when it changes; reports a clear road and a full battery."""

    def __init__(self, motors_failed: bool = False) -> None:
        self.motors_failed = motors_failed
        self._last: dict[str, Any] = {}

    def _log(self, what: str, value: Any) -> None:
        if self._last.get(what) != value:
            self._last[what] = value
            print(f"fake car: {what} {value}")

    def drive(self, left: int, right: int) -> None:
        self._log("drive", (clamp_duty(left), clamp_duty(right)))

    def stop(self) -> None:
        self.drive(0, 0)

    def look_at(self, pan: int, tilt: int) -> None:
        # Do not let any future caller reach the client UI's mechanically unsafe pan extremes,
        # or tilt down into the chassis. Configuration is checked at startup too.
        pan = min(config.HEAD_PAN_MAX, max(config.HEAD_PAN_MIN, pan))
        tilt = min(config.HEAD_TILT_MAX, max(config.HEAD_TILT_MIN, tilt))
        self._log("head", (pan, tilt))

    def look_ahead(self) -> None:
        self.look_at(config.PAN_CENTER, config.TILT_DRIVE)

    def distance_cm(self) -> float | None:
        return FAKE_DISTANCE_CM

    def battery_volts(self) -> float | None:
        return config.BATTERY_FULL_V

    def battery(self) -> float | None:
        return battery_share(self.battery_volts())

    def led(self, state: str) -> None:
        self._log("led", state)

    def close(self) -> None:
        self.stop()


def _freenove(module: str) -> Any:
    path = str(config.FREENOVE_DIR)
    if path not in sys.path:
        sys.path.insert(0, path)
    return importlib.import_module(module)


def _try(what: str, action: Callable[[], Any]) -> Any:
    try:
        return action()
    except Exception as exc:  # hardware fails in many ways (ImportError, OSError, ...)
        print(f"car: {what} failed: {type(exc).__name__}: {exc}")
        return None


class _BatteryAdc:
    def __init__(self) -> None:
        import smbus  # apt python3-smbus on the Pi

        self._bus = smbus.SMBus(1)
        pcb_v1 = config.FREENOVE_PCB_VERSION == 1
        # Formula from Freenove's adc.py: ADC reference and the board's voltage divider.
        self._scale = (3.3 if pcb_v1 else 5.2) * (3 if pcb_v1 else 2) / 255

    def volts(self) -> float | None:
        ch = ADC_BATTERY_CHANNEL
        self._bus.write_byte(ADC_ADDRESS, 0x84 | ((((ch << 2) | (ch >> 1)) & 0x07) << 4))
        for _ in range(ADC_READ_TRIES):
            first, second = self._bus.read_byte(ADC_ADDRESS), self._bus.read_byte(ADC_ADDRESS)
            if first == second:
                return round(first * self._scale, 2)
        return None

    def close(self) -> None:
        self._bus.close()


def _open_leds() -> Any:
    leds = _freenove("spi_ledpixel").Freenove_SPI_LedPixel(LED_COUNT, LED_BRIGHTNESS, "GRB")
    if leds.check_spi_state() == 0:
        raise OSError("SPI not enabled (raspi-config > Interface Options > SPI)")
    return leds


class RealCar:
    motors_failed = False

    def __init__(self, motors: Any) -> None:
        self._motors = motors
        self._servos = _try("opening servos", lambda: _freenove("servo").Servo())
        self._sonar = _try("opening ultrasonic", lambda: _freenove("ultrasonic").Ultrasonic())
        self._adc = _try("opening battery adc", _BatteryAdc)
        self._leds = _try("opening leds", _open_leds)

    def drive(self, left: int, right: int) -> None:
        left, right = clamp_duty(left), clamp_duty(right)
        self._motors.set_motor_model(left, left, right, right)

    def stop(self) -> None:
        self._motors.set_motor_model(0, 0, 0, 0)

    def look_at(self, pan: int, tilt: int) -> None:
        pan = min(config.HEAD_PAN_MAX, max(config.HEAD_PAN_MIN, pan))
        tilt = min(config.HEAD_TILT_MAX, max(config.HEAD_TILT_MIN, tilt))
        if self._servos is not None:
            self._servos.set_servo_pwm(PAN, pan)
            self._servos.set_servo_pwm(TILT, tilt)

    def look_ahead(self) -> None:
        self.look_at(config.PAN_CENTER, config.TILT_DRIVE)

    def distance_cm(self) -> float | None:
        if self._sonar is None:
            return None
        try:
            return self._sonar.get_distance()
        except Exception as exc:
            print(f"car: ultrasonic read failed: {type(exc).__name__}: {exc}")
            return None

    def battery_volts(self) -> float | None:
        if self._adc is None:
            return None
        try:
            return self._adc.volts()
        except OSError as exc:
            print(f"car: battery read failed: {exc}")
            return None

    def battery(self) -> float | None:
        return battery_share(self.battery_volts())

    def led(self, state: str) -> None:
        if self._leds is not None:
            _try(f"led {state}", lambda: self._leds.set_all_led_color(*config.LED_COLORS[state]))

    def close(self) -> None:
        try:
            self._motors.close()  # Freenove's close() sets all four duties to 0 first
        finally:
            for name, close in (
                ("ultrasonic", self._sonar and self._sonar.close),
                ("battery adc", self._adc and self._adc.close),
                ("leds", self._leds and self._leds.led_close),
            ):
                if close:
                    _try(f"closing {name}", close)


def open_car(fake: bool) -> FakeCar | RealCar:
    if fake:
        return FakeCar()
    try:
        motors = _freenove("motor").Ordinary_Car()
    except Exception as exc:
        # Never drive half-initialised: without motors nothing else on the car is used.
        print(f"fallback: motors unavailable ({type(exc).__name__}: {exc}), using FakeCar")
        return FakeCar(motors_failed=True)
    return RealCar(motors)
