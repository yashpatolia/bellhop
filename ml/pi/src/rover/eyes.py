"""Eyes in the style of Astro Bot on the HDMI screen: round when listening, upside-down crescents
when happy.

The voice process sets `base` (idle, listening, thinking) and calls feel(tone) as each sentence is
spoken, so the face follows Claude's tone tag. A thread draws EYES_FPS frames a second straight
into the Linux framebuffer when the Pi shows its console; the desktop hides the framebuffer, so
under it the face goes into a full-screen window instead.
"""

from __future__ import annotations

import atexit
import math
import os
import random
import signal
import sys
import threading
import time
from pathlib import Path

import numpy as np

from rover import config

W, H = 128, 64  # the face is designed in these "face pixels" and drawn `scale` times bigger
WINDOW = "bellhop"
EYE_GAP = 24  # each eye's centre this far from the middle of the screen
# happy: an oval below the centre is carved out, leaving a thick dome with short legs
HAPPY_CUT_Y, HAPPY_CUT_W, HAPPY_CUT_H = 0.75, 0.85, 0.7  # its centre, width, height (x the eye)
SOFT_LID, SOFT_TILT = 0.35, 0.3  # gentle: lid height above the centre, droop toward the outside
BOUNCE_PX, BOUNCE_HZ = 3, 2.5  # excited
THINK_DRIFT_PX, THINK_DRIFT_S = 10, 3.0  # thinking: the eyes drift side to side, this far and slow
# name: (half width, half height, look x, look y, shape)
EXPRESSIONS = {
    "idle": (14, 16, 0, 0, "round"),
    "listening": (16, 18, 0, 0, "round"),  # a little wider: it is paying attention
    "thinking": (12, 14, 0, -10, "round"),  # looks up, drifting side to side
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


class WindowScreen:
    """The screen while the Pi shows its desktop: a full-screen OpenCV window. One thread makes
    every window call; show() and show_image() only hand it the next picture, replaced whole so it
    is never drawn half-done. A swipe down from the top edge, or q or Esc, stops the robot."""

    def __init__(self, size: tuple[int, int] = config.GAME_CANVAS) -> None:
        width, height = size
        self.size, self.scale = size, min(width // W, height // H)
        self._top, self._left = (height - H * self.scale) // 2, (width - W * self.scale) // 2
        self.picture = np.zeros((height, width, 3), np.uint8)  # BGR
        self.lock = threading.Lock()
        self._swipe_from: int | None = None  # y where a touch began at the top edge

    def show(self, frame: np.ndarray) -> None:
        picture, (h, w) = np.zeros_like(self.picture), frame.shape
        face = picture[self._top : self._top + h, self._left : self._left + w]
        face[frame] = config.EYES_RGB[::-1]  # BGR
        self.picture = picture

    def show_image(self, bgr: np.ndarray) -> None:
        import cv2

        width, height = self.size
        if bgr.shape[:2] != (height, width):
            bgr = cv2.resize(bgr, (width, height), interpolation=cv2.INTER_AREA)
        self.picture = bgr

    def off(self) -> None:
        self.picture = np.zeros_like(self.picture)

    def on_mouse(self, event: int, x: int, y: int, flags: int, param: object = None) -> None:
        """A touch is a mouse press to the window. Only a long drag from the top edge quits, so a
        resident brushing the screen never closes the robot."""
        import cv2

        if event == cv2.EVENT_LBUTTONDOWN:
            self._swipe_from = y if y <= config.EYES_EXIT_EDGE_PX else None
        elif event == cv2.EVENT_LBUTTONUP:
            if self._swipe_from is not None and y - self._swipe_from >= config.EYES_EXIT_SWIPE_PX:
                self.quit()
            self._swipe_from = None

    def quit(self) -> None:
        print("eyes: closed from the window")
        os.kill(os.getpid(), signal.SIGTERM)  # the robot's own shutdown: LED idle, then exit

    def start(self) -> WindowScreen:
        threading.Thread(target=self._run, daemon=True, name="window").start()
        return self

    def _run(self) -> None:
        import cv2

        try:
            cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL | cv2.WINDOW_GUI_NORMAL)
            cv2.setWindowProperty(WINDOW, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
            cv2.setMouseCallback(WINDOW, self.on_mouse)
        except cv2.error as exc:
            print(f"fallback: no face window ({exc})")
            return
        shown = None
        while True:
            picture = self.picture
            if picture is not shown:
                cv2.imshow(WINDOW, picture)
                shown = picture
            if (cv2.waitKey(1000 // config.EYES_FPS) & 0xFF) in (ord("q"), 27):
                self.quit()
                return


def open_screen() -> Screen | WindowScreen:
    """The framebuffer on the console; a full-screen window when a desktop is running."""
    if sys.platform == "linux" and (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        return WindowScreen().start()
    return Screen()


class Eyes:
    def __init__(self, screen: Screen | WindowScreen | None = None) -> None:
        self.screen = screen
        self.base = "idle"
        self.paused = False  # a game has the screen
        self._mood, self._mood_until = "", 0.0
        self._blink_at = self._glance_at = 0.0  # the first frame blinks: it wakes up
        self._blink_from, self._blink_s = -math.inf, config.EYES_BLINK_S
        self._look, self._look_until = (0, 0), 0.0
        self._failing = False
        self._shown: tuple | None = None  # the pose on the screen; None: repaint it
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def feel(self, tone: str, until: float | None = None) -> None:
        """Show this tone (a reply's tag) until EYES_MOOD_HOLD_S after the last call, or after
        `until` (when the sentence being spoken ends)."""
        end = time.monotonic() if until is None else until
        self._mood, self._mood_until = tone, end + config.EYES_MOOD_HOLD_S

    def expression(self, now: float) -> str:
        return self._mood if now < self._mood_until else self.base

    def pose(self, now: float) -> tuple[str, float, tuple[int, int], float]:
        """draw()'s (expression, blink, look, bob) for this moment."""
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
        elif expression == "thinking":
            look = (round(THINK_DRIFT_PX * math.sin(2 * math.pi * now / THINK_DRIFT_S)), 0)
        return expression, blink, look, bob

    def frame(self, now: float) -> np.ndarray:
        return draw(*self.pose(now), scale=self.screen.scale if self.screen else 1)

    def tick(self) -> None:
        try:
            pose = self.pose(time.monotonic())
            if self.paused:
                self._shown = None  # a game drew over the face: repaint it when the game ends
                return
            if pose == self._shown:
                return  # the face is still most of the time: no draw, no screen write
            frame = draw(*pose, scale=self.screen.scale)
            with self.screen.lock:
                if not self.paused:  # checked under the lock: a game may have just taken over
                    self.screen.show(frame)
                    self._shown = pose
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
                self.screen = open_screen()
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
