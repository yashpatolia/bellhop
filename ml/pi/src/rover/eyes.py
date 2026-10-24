"""OLED eyes in the style of Astro Bot: round when listening, upside-down crescents when happy.

The voice process sets `base` (idle, listening, thinking) and calls feel(tone) as each sentence is
spoken, so the face follows Claude's tone tag. A thread draws ~10 frames a second and sends only
the 8-row pages that changed, because the I2C bus is shared with the motor board.
"""

from __future__ import annotations

import atexit
import math
import random
import threading
import time

import numpy as np

from rover import config

W, H = 128, 64
EYE_GAP = 24  # each eye's centre this far from the middle of the screen
# happy: an oval below the centre is carved out, leaving a thick dome with short legs
HAPPY_CUT_Y, HAPPY_CUT_W, HAPPY_CUT_H = 0.75, 0.85, 0.7  # its centre, width, height (x the eye)
SOFT_LID, SOFT_TILT = 0.35, 0.3  # gentle: lid height above the centre, droop toward the outside
BOUNCE_PX, BOUNCE_HZ = 3, 2.5  # excited
# name: (half width, half height, look x, look y, shape)
EXPRESSIONS = {
    "idle": (14, 16, 0, 0, "round"),
    "listening": (16, 18, 0, 0, "round"),  # a little wider: it is paying attention
    "thinking": (12, 14, 8, -10, "round"),  # looks up and aside
    "cheerful": (17, 16, 0, -2, "happy"),
    "excited": (19, 18, 0, -2, "happy"),  # + bounce
    "calm": (14, 14, 0, 2, "round"),  # + slow blinks
    "gentle": (15, 15, 0, 8, "soft"),  # looks down, lids lowered
}
_Y, _X = np.mgrid[0:H, 0:W]


def _oval(cx: float, cy: float, rx: float, ry: float) -> np.ndarray:
    return ((_X - cx) / rx) ** 2 + ((_Y - cy) / ry) ** 2 < 1  # "<": no 1-px spikes at the tips


def draw(expression: str, blink: float = 0.0, look: tuple[int, int] = (0, 0), bob: int = 0):
    """A (64, 128) bool frame. blink 0..1 squashes the eyes shut; bob moves them up."""
    rx, ry, dx, dy, shape = EXPRESSIONS.get(expression, EXPRESSIONS["idle"])
    ry = max(ry * (1 - blink), 1)
    frame = np.zeros((H, W), bool)
    for side in (-1, 1):
        cx = (W - 1) / 2 + side * EYE_GAP + dx + look[0]  # (W - 1) / 2: the true middle
        cy = (H - 1) / 2 + dy + look[1] - bob
        eye = _oval(cx, cy, rx, ry)
        if shape == "happy":
            eye &= ~_oval(cx, cy + ry * HAPPY_CUT_Y, rx * HAPPY_CUT_W, ry * HAPPY_CUT_H)
        elif shape == "soft":
            eye &= _Y >= cy - ry * SOFT_LID + SOFT_TILT * side * (_X - cx)
        frame |= eye
    return frame[::-1, ::-1] if config.OLED_FLIP else frame


class Oled:
    """SSD1306 (or SH1106 with a column offset) over I2C, with smbus like the battery reader."""

    INIT = [
        0xAE, 0xD5, 0x80, 0xA8, H - 1, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x02,
        0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF,
    ]  # fmt: skip
    CHUNK = 32  # smbus block writes carry at most 32 bytes

    def __init__(self, bus=None, address: int = config.OLED_ADDRESS) -> None:
        if bus is None:
            import smbus  # apt python3-smbus on the Pi

            bus = smbus.SMBus(1)
        self._bus, self._address = bus, address
        self._pages: list[bytes | None] = [None] * (H // 8)
        self._command(*self.INIT)

    def _command(self, *codes: int) -> None:
        self._bus.write_i2c_block_data(self._address, 0x00, list(codes))

    def show(self, frame: np.ndarray) -> None:
        # each byte is a column of 8 rows, top row in the lowest bit
        pages = np.packbits(frame.reshape(H // 8, 8, W), axis=1, bitorder="little")[:, 0, :]
        column = config.OLED_COLUMN_OFFSET
        for page, row in enumerate(pages):
            data = row.tobytes()
            if data == self._pages[page]:
                continue
            self._pages[page] = None  # a failed write below must be resent next frame
            self._command(0xB0 | page, column & 0x0F, 0x10 | column >> 4)
            for i in range(0, W, self.CHUNK):
                self._bus.write_i2c_block_data(self._address, 0x40, list(data[i : i + self.CHUNK]))
            self._pages[page] = data

    def off(self) -> None:
        self.show(np.zeros((H, W), bool))
        self._command(0xAE)


class Eyes:
    def __init__(self, oled: Oled | None = None) -> None:
        self.oled = oled
        self.base = "idle"
        self._mood, self._mood_until = "", 0.0
        self._blink_at = self._glance_at = 0.0  # the first frame blinks: it wakes up
        self._blink_from, self._blink_s = -math.inf, config.EYES_BLINK_S
        self._look, self._look_until = (0, 0), 0.0
        self._failing = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def feel(self, tone: str) -> None:
        """Show this tone (a reply's tag) until EYES_MOOD_HOLD_S after the last call."""
        self._mood, self._mood_until = tone, time.monotonic() + config.EYES_MOOD_HOLD_S

    def expression(self, now: float) -> str:
        return self._mood if now < self._mood_until else self.base

    def frame(self, now: float) -> np.ndarray:
        expression = self.expression(now)
        if now >= self._blink_at:
            self._blink_from = now
            slow = expression == "calm"
            self._blink_s = config.EYES_SLOW_BLINK_S if slow else config.EYES_BLINK_S
            self._blink_at = now + self._blink_s + random.uniform(*config.EYES_BLINK_EVERY_S)
        phase = (now - self._blink_from) / self._blink_s
        blink = min(1.0, 2 * (1 - abs(2 * phase - 1))) if phase <= 1 else 0.0  # shut mid-blink
        look, bob = (0, 0), 0
        if expression in ("idle", "listening"):
            if now >= self._glance_at:
                px = config.EYES_GLANCE_PX
                self._look = (random.choice((-px, px)), random.choice((-px // 2, 0)))
                self._look_until = now + config.EYES_GLANCE_S
                self._glance_at = now + random.uniform(*config.EYES_GLANCE_EVERY_S)
            if now < self._look_until:
                look = self._look
        elif expression == "excited":
            bob = round(BOUNCE_PX * abs(math.sin(math.pi * BOUNCE_HZ * now)))
        return draw(expression, blink, look, bob)

    def tick(self) -> None:
        try:
            self.oled.show(self.frame(time.monotonic()))
            self._failing = False
        except Exception as exc:  # noqa: BLE001 - a loose wire must not stop the visit
            if not self._failing:
                print(f"fallback: OLED write failed ({exc!r}); retrying every frame")
            self._failing = True

    def _run(self) -> None:
        while not self._stop.wait(1 / config.EYES_FPS):
            self.tick()

    def start(self) -> Eyes:
        """Open the OLED and animate it; without one (a Mac, no wire) the face is just skipped."""
        if self.oled is None:
            try:
                self.oled = Oled()
            except Exception as exc:  # noqa: BLE001 - ImportError on a Mac, OSError with no screen
                print(f"fallback: no OLED face ({type(exc).__name__}: {exc})")
                return self
        atexit.register(self.stop)  # a dead program must not leave the eyes frozen open
        self._thread = threading.Thread(target=self._run, daemon=True, name="eyes")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1)  # a frame half-sent after off() would light the eyes again
        if self.oled is not None:
            try:
                self.oled.off()
            except Exception as exc:  # noqa: BLE001
                print(f"eyes: could not switch the OLED off: {exc!r}")
