"""Eyes in the style of Astro Bot on the HDMI screen: round when listening, upside-down crescents
when happy.

The voice process sets `base` (idle, listening, thinking) and calls feel(tone) as each sentence is
spoken, so the face follows Claude's tone tag. A thread draws EYES_FPS frames a second straight
into the Linux framebuffer, so the Pi must show the console on HDMI, not the desktop.
"""

from __future__ import annotations

import atexit
import math
import random
import threading
import time
from pathlib import Path

import numpy as np

from rover import config

W, H = 128, 64  # the face is designed in these "face pixels" and drawn `scale` times bigger
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


def _axis(n: int, scale: int) -> np.ndarray:
    return (np.arange(n * scale) + 0.5) / scale - 0.5  # pixel centres, in face pixels


def _oval(x, y, cx: float, cy: float, rx: float, ry: float) -> np.ndarray:
    return ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 < 1  # "<": no 1-px spikes at the tips


def draw(
    expression: str,
    blink: float = 0.0,
    look: tuple[int, int] = (0, 0),
    bob: float = 0,
    scale: int = 1,
):
    """A (64, 128) x scale bool frame. blink 0..1 squashes the eyes shut; bob moves them up."""
    rx, ry, dx, dy, shape = EXPRESSIONS.get(expression, EXPRESSIONS["idle"])
    ry = max(ry * (1 - blink), 1)
    y, x = _axis(H, scale)[:, None], _axis(W, scale)[None, :]  # broadcast: no full-size grids
    frame = np.zeros((H * scale, W * scale), bool)
    for side in (-1, 1):
        cx = (W - 1) / 2 + side * EYE_GAP + dx + look[0]  # (W - 1) / 2: the true middle
        cy = (H - 1) / 2 + dy + look[1] - bob
        eye = _oval(x, y, cx, cy, rx, ry)
        if shape == "happy":
            eye &= ~_oval(x, y, cx, cy + ry * HAPPY_CUT_Y, rx * HAPPY_CUT_W, ry * HAPPY_CUT_H)
        elif shape == "soft":
            eye &= y >= cy - ry * SOFT_LID + SOFT_TILT * side * (x - cx)
        frame |= eye
    return frame[::-1, ::-1] if config.EYES_FLIP else frame


class Screen:
    """The HDMI screen through the Linux framebuffer, sized from sysfs (16 or 32 bits a pixel)."""

    def __init__(self, device: str = config.EYES_FB, sysfs: Path | None = None) -> None:
        info = sysfs or Path("/sys/class/graphics") / Path(device).name
        width, height = (int(v) for v in (info / "virtual_size").read_text().split(","))
        self.bits = int((info / "bits_per_pixel").read_text())
        dtype = {16: np.uint16, 32: np.uint32}[self.bits]  # KeyError: an unsupported depth
        stride = int((info / "stride").read_text()) // np.dtype(dtype).itemsize
        self.size, self.scale = (width, height), min(width // W, height // H)
        r, g, b = config.EYES_RGB
        self._on = r >> 3 << 11 | g >> 2 << 5 | b >> 3 if self.bits == 16 else r << 16 | g << 8 | b
        self._fb = np.memmap(device, dtype, "r+", shape=(height, stride))
        self._image = np.zeros(self._fb.shape, dtype)
        top, left = (height - H * self.scale) // 2, (width - W * self.scale) // 2
        self._face = self._image[top : top + H * self.scale, left : left + W * self.scale]
        self.lock = threading.Lock()  # the eyes and a game take turns: held around each write

    def show(self, frame: np.ndarray) -> None:
        self._face[:] = frame
        self._face *= self._on
        self._fb[:] = self._image  # the whole screen: console text under the face is wiped too

    def show_image(self, bgr: np.ndarray) -> None:
        """A full-screen BGR picture (a game), resized when the screen is not its size."""
        import cv2  # only games draw pictures, so the face alone never loads OpenCV

        width, height = self.size
        if bgr.shape[:2] != (height, width):
            bgr = cv2.resize(bgr, (width, height), interpolation=cv2.INTER_AREA)
        code = cv2.COLOR_BGR2BGR565 if self.bits == 16 else cv2.COLOR_BGR2BGRA
        self._fb[:, :width] = cv2.cvtColor(bgr, code).view(self._fb.dtype)[..., 0]

    def off(self) -> None:
        self._fb[:] = 0


class Eyes:
    def __init__(self, screen: Screen | None = None) -> None:
        self.screen = screen
        self.base = "idle"
        self.paused = False  # a game has the screen
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
            bob = BOUNCE_PX * abs(math.sin(math.pi * BOUNCE_HZ * now))
        return draw(expression, blink, look, bob, self.screen.scale if self.screen else 1)

    def tick(self) -> None:
        try:
            frame = self.frame(time.monotonic())
            with self.screen.lock:
                if not self.paused:  # checked under the lock: a game may have just taken over
                    self.screen.show(frame)
            self._failing = False
        except Exception as exc:  # noqa: BLE001 - a screen problem must not stop the visit
            if not self._failing:
                print(f"fallback: face screen write failed ({exc!r}); retrying every frame")
            self._failing = True

    def _run(self) -> None:
        while not self._stop.wait(1 / config.EYES_FPS):
            self.tick()

    def start(self) -> Eyes:
        """Open the screen and animate it; without one (a Mac, no HDMI) the face is just skipped."""
        if self.screen is None:
            try:
                self.screen = Screen()
            except Exception as exc:  # noqa: BLE001 - no sysfs on a Mac, OSError with no screen
                print(f"fallback: no face screen ({type(exc).__name__}: {exc})")
                return self
        atexit.register(self.stop)  # a dead program must not leave the eyes frozen open
        self._thread = threading.Thread(target=self._run, daemon=True, name="eyes")
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1)  # a frame half-sent after off() would light the eyes again
        if self.screen is not None:
            try:
                self.screen.off()
            except Exception as exc:  # noqa: BLE001
                print(f"eyes: could not blank the face screen: {exc!r}")
