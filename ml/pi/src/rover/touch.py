"""The touch panel as raw Linux input events: no library, and no CPU between touches.

Touch.open() finds the panel (the input device with absolute X and Y and a touch button;
keyboards and mice have no absolute axes, gamepads and a panel's mouse node no touch button), then
run() blocks on it and calls on_touch(kind, x, y) with kind "down", "move" or "up" and x, y in
screen pixels, turned with the face when EYES_FLIP is set. A panel that drops off USB (a brownout,
a replug) is looked for again every TOUCH_RETRY_S.
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import struct
import time
from collections.abc import Callable
from pathlib import Path

from rover import config

# struct input_event on 64-bit Linux: seconds, microseconds, type, code, value
EVENT = struct.Struct("llHHi")
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, BTN_TOUCH, ABS_X, ABS_Y = 0, 0x14A, 0, 1
EVIOCGABS = 0x80184540  # + axis: _IOR('E', 0x40 + axis, struct input_absinfo), 6 ints
EVIOCGBIT_KEY = 0x80604521  # _IOR('E', 0x20 + EV_KEY, 96): the key codes a device can send

OnTouch = Callable[[str, int, int], None]


def _abs_range(fd: int, axis: int) -> tuple[int, int]:
    _, low, high, *_ = struct.unpack("6i", fcntl.ioctl(fd, EVIOCGABS + axis, bytes(24)))
    return low, high


def _has_key(bits: bytes, code: int) -> bool:
    return bool(bits[code // 8] >> code % 8 & 1)


class Touch:
    def __init__(
        self,
        ranges: list[tuple[int, int]],
        size: tuple[int, int],
        on_touch: OnTouch,
        fd: int | None = None,
    ) -> None:
        self._ranges, self._size, self._on_touch, self._fd = ranges, size, on_touch, fd
        self._raw = [(low + high) / 2 for low, high in ranges]
        self._down = False
        self._pressed: bool | None = None  # BTN_TOUCH in the report being read
        self._moved = False

    @classmethod
    def open(cls, size: tuple[int, int], on_touch: OnTouch) -> Touch:
        for path in sorted(Path("/dev/input").glob("event*")):
            try:
                fd = os.open(path, os.O_RDONLY)
            except OSError:
                continue
            try:
                ranges = [_abs_range(fd, axis) for axis in (ABS_X, ABS_Y)]
                touches = _has_key(fcntl.ioctl(fd, EVIOCGBIT_KEY, bytes(96)), BTN_TOUCH)
            except OSError:  # no absolute axes: a keyboard, a mouse, the power button
                ranges, touches = [], False
            if touches and ranges and all(high > low for low, high in ranges):
                print(f"touch: {path}, x {ranges[0]}, y {ranges[1]}")
                return cls(ranges, size, on_touch, fd)
            os.close(fd)
        raise FileNotFoundError("no touch panel (absolute X and Y, BTN_TOUCH) in /dev/input")

    def position(self) -> tuple[int, int]:
        x, y = (
            round((raw - low) / (high - low) * (side - 1))
            for raw, (low, high), side in zip(self._raw, self._ranges, self._size, strict=True)
        )
        if config.EYES_FLIP:  # the panel turned over with the screen
            x, y = self._size[0] - 1 - x, self._size[1] - 1 - y
        return x, y

    def feed(self, data: bytes) -> None:
        for *_, kind, code, value in EVENT.iter_unpack(data):
            if kind == EV_ABS and code in (ABS_X, ABS_Y):
                self._raw[code] = value
                self._moved = True
            elif kind == EV_KEY and code == BTN_TOUCH:
                self._pressed = bool(value)
            elif kind == EV_SYN and code == SYN_REPORT:
                self._report()

    def _report(self) -> None:
        pressed = self._down if self._pressed is None else self._pressed
        if pressed != self._down:
            self._down = pressed
            self._on_touch("down" if pressed else "up", *self.position())
        elif pressed and self._moved:
            self._on_touch("move", *self.position())
        self._pressed, self._moved = None, False

    def run(self) -> None:
        while True:
            try:
                data = os.read(self._fd, EVENT.size * 64)  # blocks until the panel is touched
            except OSError as exc:  # ENODEV: the panel left USB
                print(f"fallback: touch panel lost ({exc}); looking for it again")
                self._reopen()
                continue
            self.feed(data)

    def _reopen(self) -> None:
        with contextlib.suppress(OSError):
            os.close(self._fd)
        if self._down:  # its "up" is lost with the panel: a start screen would think it is held
            self._down = False
            self._on_touch("up", *self.position())
        while True:
            time.sleep(config.TOUCH_RETRY_S)
            try:
                panel = Touch.open(self._size, self._on_touch)  # prints the node it found
            except OSError:
                continue
            self._fd, self._ranges, self._raw = panel._fd, panel._ranges, panel._raw
            return
