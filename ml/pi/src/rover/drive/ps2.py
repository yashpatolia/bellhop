"""GPIO-wired Yahboom PS2 receiver backup control for :mod:`rover.drive`.

This receiver is not a USB joystick.  It bit-bangs the PS2 protocol over four GPIO lines using
CircuitPython's PS2Controller through Blinka.  Every frame is treated as a fresh safety permit:
a missing or malformed frame, a released deadman, or an exception stops the car immediately.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from rover import config
from rover.drive.control import Controller


def _stick(value: int, deadzone: float) -> float:
    """Convert PS2's 0..255 analogue value to a centred -1..1 command."""
    scaled = max(-1.0, min(1.0, (int(value) - 128) / 127.0))
    return 0.0 if abs(scaled) < deadzone else scaled


@dataclass
class PS2Mixer:
    """Pure PS2-stick-to-differential-drive mapping, independently testable off the Pi."""

    deadzone: float = config.MANUAL_DEADZONE
    max_duty: int = config.MANUAL_MAX_DUTY

    def command(self, *, linked: bool, deadman: bool, left_x: int, left_y: int) -> tuple[int, int] | None:
        if not linked or not deadman:
            return None
        # PS2 y=0 is stick up (logical forward); x=255 is stick right.
        forward = -_stick(left_y, self.deadzone)
        turn = _stick(left_x, self.deadzone)
        left = round((forward + turn) * self.max_duty)
        right = round((forward - turn) * self.max_duty)
        return left, right


class ManualPS2:
    """Poll the wired receiver in a daemon thread without ever blocking rover navigation."""

    def __init__(self, controller: Controller, mixer: PS2Mixer | None = None) -> None:
        self._controller = controller
        self._mixer = mixer or PS2Mixer()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ps2: Any = None
        self._button: Any = None

    def start(self) -> bool:
        try:
            import board
            from ps2controller import PS2Button, PS2Controller

            self._ps2 = PS2Controller(
                clk=getattr(board, config.PS2_CLK_PIN),
                cmd=getattr(board, config.PS2_CMD_PIN),
                att=getattr(board, config.PS2_ATT_PIN),
                dat=getattr(board, config.PS2_DAT_PIN),
            )
            self._button = getattr(PS2Button, config.PS2_DEADMAN_BUTTON)
        except Exception as exc:  # optional hardware library or a bad pin name must never block drive
            print(f"manual: GPIO PS2 controller unavailable: {type(exc).__name__}: {exc}")
            return False
        self._thread = threading.Thread(target=self._run, name="ps2-controller", daemon=True)
        self._thread.start()
        print(
            "manual: GPIO PS2 controller ready "
            f"(deadman {config.PS2_DEADMAN_BUTTON}; release or link loss stops motors)"
        )
        return True

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.5)
        self._controller.stop()

    def _run(self) -> None:
        active = False
        linked: bool | None = None
        while not self._stop.is_set():
            try:
                events = self._ps2.update()
                frame_ok = events is not None
                if frame_ok:
                    left_x, left_y = self._ps2.analog_left()
                    command = self._mixer.command(
                        linked=True,
                        deadman=bool(self._ps2.button(self._button)),
                        left_x=left_x,
                        left_y=left_y,
                    )
                else:
                    command = None
            except Exception as exc:
                print(f"manual: GPIO PS2 read failed: {type(exc).__name__}: {exc}")
                frame_ok, command = False, None

            if frame_ok != linked:
                print("manual: GPIO PS2 connected" if frame_ok else "manual: GPIO PS2 link lost; stopped")
                linked = frame_ok
            if command is None:
                if active:
                    self._controller.stop()
                active = False
            else:
                self._controller.manual_drive(*command)
                active = True
            self._stop.wait(config.PS2_POLL_S)
