"""Optional Linux joystick backup controller for rover.drive.

The adapter uses the standard ``/dev/input/js*`` ABI, so a PS2 USB or Bluetooth adapter needs no
Python package. Holding the configured deadman button is required for every movement command;
releasing it, unplugging the device, or a missed refresh stops the rover.
"""

from __future__ import annotations

import os
import struct
import threading
import time
from dataclasses import dataclass

from rover import config
from rover.drive.control import Controller

_EVENT = struct.Struct("IhBB")
_BUTTON, _AXIS, _INIT = 0x01, 0x02, 0x80


def _axis(value: int, deadzone: float) -> float:
    scaled = max(-1.0, min(1.0, value / 32767.0))
    return 0.0 if abs(scaled) < deadzone else scaled


@dataclass
class ManualMixer:
    """Map normalized joystick events to differential wheel duties without touching hardware."""

    deadman_button: int = config.MANUAL_DEADMAN_BUTTON
    forward_axis: int = config.MANUAL_FORWARD_AXIS
    turn_axis: int = config.MANUAL_TURN_AXIS
    deadzone: float = config.MANUAL_DEADZONE
    max_duty: int = config.MANUAL_MAX_DUTY
    deadman: bool = False
    forward: float = 0.0
    turn: float = 0.0

    def event(self, value: int, kind: int, number: int) -> tuple[int, int] | None:
        kind &= ~_INIT
        if kind == _BUTTON and number == self.deadman_button:
            self.deadman = bool(value)
        elif kind == _AXIS and number == self.forward_axis:
            self.forward = -_axis(value, self.deadzone)
        elif kind == _AXIS and number == self.turn_axis:
            self.turn = _axis(value, self.deadzone)
        else:
            return None
        return self.command()

    def command(self) -> tuple[int, int] | None:
        if not self.deadman:
            return None
        left = round((self.forward + self.turn) * self.max_duty)
        right = round((self.forward - self.turn) * self.max_duty)
        return left, right


class ManualJoystick:
    """Non-blocking reader; no device or driver means manual mode simply stays unavailable."""

    def __init__(
        self,
        controller: Controller,
        device: str = config.MANUAL_DEVICE,
        mixer: ManualMixer | None = None,
    ) -> None:
        self._controller, self._device = controller, device
        self._mixer = mixer or ManualMixer()
        self._stop = threading.Event()
        self._fd: int | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            self._fd = os.open(self._device, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            print(f"manual: controller unavailable at {self._device}: {type(exc).__name__}: {exc}")
            return False
        self._thread = threading.Thread(target=self._run, name="manual-controller", daemon=True)
        self._thread.start()
        print(f"manual: controller ready at {self._device}; hold deadman button to move")
        return True

    def close(self) -> None:
        self._stop.set()
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        self._controller.stop()

    def _apply(self, command: tuple[int, int] | None) -> None:
        if command is None:
            self._controller.stop()
        else:
            self._controller.manual_drive(*command)

    def _run(self) -> None:
        assert self._fd is not None
        pending = b""
        next_refresh = 0.0
        while not self._stop.is_set():
            try:
                pending += os.read(self._fd, 1024)
            except BlockingIOError:
                pass
            except OSError:
                self._controller.stop()
                return
            while len(pending) >= _EVENT.size:
                _, value, kind, number = _EVENT.unpack(pending[: _EVENT.size])
                pending = pending[_EVENT.size :]
                command = self._mixer.event(value, kind, number)
                if command is not None or (kind & ~_INIT) == _BUTTON:
                    self._apply(command)
            now = time.monotonic()
            command = self._mixer.command()
            if command is not None and now >= next_refresh:
                self._controller.manual_drive(*command)
                next_refresh = now + config.MANUAL_REFRESH_S
            self._stop.wait(0.02)
