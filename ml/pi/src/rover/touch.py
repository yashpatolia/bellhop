"""The touch panel as raw Linux input events: no library, and no CPU between touches.

Touch.open() finds the panel (the input device with absolute X and Y; keyboards and mice have
none), then run() blocks on it and calls on_touch(kind, x, y) with kind "down", "move" or "up"
and x, y in screen pixels, turned with the face when EYES_FLIP is set.
"""

from __future__ import annotations

import fcntl
import os
import struct
from collections.abc import Callable
from pathlib import Path

from rover import config

# struct input_event on 64-bit Linux: seconds, microseconds, type, code, value
EVENT = struct.Struct("llHHi")
EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
SYN_REPORT, BTN_TOUCH, ABS_X, ABS_Y = 0, 0x14A, 0, 1
EVIOCGABS = 0x80184540  # + axis: _IOR('E', 0x40 + axis, struct input_absinfo), 6 ints

OnTouch = Callable[[str, int, int], None]


def _abs_range(fd: int, axis: int) -> tuple[int, int]:
    _, low, high, *_ = struct.unpack("6i", fcntl.ioctl(fd, EVIOCGABS + axis, bytes(24)))
    return low, high


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
            except OSError:  # no absolute axes: a keyboard, a mouse, the power button
                ranges = []
            if ranges and all(high > low for low, high in ranges):
                print(f"touch: {path}, x {ranges[0]}, y {ranges[1]}")
                return cls(ranges, size, on_touch, fd)
            os.close(fd)
        raise FileNotFoundError("no touch panel (absolute X and Y) in /dev/input")

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
            self.feed(os.read(self._fd, EVENT.size * 64))  # blocks until the panel is touched
