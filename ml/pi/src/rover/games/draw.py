"""Drawing for the games: a BGR canvas, big buttons and big words. OpenCV loads on first draw."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rover import config

W, H = config.GAME_CANVAS
BG = (40, 24, 16)  # deep navy
INK = (240, 240, 240)
DIM = (150, 140, 130)
LINE = (110, 90, 80)
ACCENT = tuple(config.EYES_RGB[::-1])  # the eyes' cyan: the resident's marks
ROBOT = (110, 110, 255)  # coral: the robot's marks
PANEL_X = 660  # boards stay left of this; words and buttons go on the right
FONT = 2  # cv2.FONT_HERSHEY_DUPLEX, without importing OpenCV here


def canvas() -> np.ndarray:
    return np.full((H, W, 3), BG, np.uint8)


def text(img, words: str, cx: int, cy: int, scale: float, colour=INK, thick: int = 2) -> None:
    """Words centred on (cx, cy)."""
    import cv2

    (w, h), _ = cv2.getTextSize(words, FONT, scale, thick)
    cv2.putText(img, words, (cx - w // 2, cy + h // 2), FONT, scale, colour, thick, cv2.LINE_AA)


@dataclass(frozen=True)
class Button:
    label: str
    x0: int
    y0: int
    x1: int
    y1: int

    def hit(self, x: int, y: int) -> bool:
        return self.x0 <= x < self.x1 and self.y0 <= y < self.y1

    def draw(self, img, colour=ACCENT) -> None:
        import cv2

        cv2.rectangle(img, (self.x0, self.y0), (self.x1, self.y1), colour, 4, cv2.LINE_AA)
        text(img, self.label, (self.x0 + self.x1) // 2, (self.y0 + self.y1) // 2, 1.3, colour)


FINISH = Button("Finish", PANEL_X, 500, W - 24, 580)
AGAIN = Button("Play again", PANEL_X, 410, W - 24, 490)
