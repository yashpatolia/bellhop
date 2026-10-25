"""Memory match: 12 face-down cards hide 6 pairs of big coloured shapes; find every pair."""

from __future__ import annotations

import random

import numpy as np

from rover import config
from rover.games.draw import ACCENT, DIM, INK, LINE, PANEL_X, W, text

# shape: BGR colour, each easy to tell apart at a glance
SHAPES = {
    "circle": (80, 80, 235),
    "square": (235, 150, 60),
    "triangle": (90, 200, 90),
    "star": (60, 215, 240),
    "diamond": (215, 110, 200),
    "cross": (240, 240, 240),
}
COLS, ROWS = 4, 3
CARD_W, CARD_H, GAP, GRID_X, GRID_Y = 140, 175, 16, 26, 22
FACE_DOWN, FACE_UP = (70, 48, 34), (90, 66, 50)


def _shape(img, shape: str, cx: int, cy: int, r: int) -> None:
    import cv2

    colour = SHAPES[shape]
    if shape == "circle":
        cv2.circle(img, (cx, cy), r, colour, -1, cv2.LINE_AA)
        return
    if shape == "square":
        cv2.rectangle(img, (cx - r, cy - r), (cx + r, cy + r), colour, -1)
        return
    if shape == "cross":
        w = r // 3
        cv2.rectangle(img, (cx - w, cy - r), (cx + w, cy + r), colour, -1)
        cv2.rectangle(img, (cx - r, cy - w), (cx + r, cy + w), colour, -1)
        return
    if shape == "triangle":
        points = [(cx, cy - r), (cx + r, cy + r), (cx - r, cy + r)]
    elif shape == "diamond":
        points = [(cx, cy - r), (cx + r, cy), (cx, cy + r), (cx - r, cy)]
    else:  # star: five points, alternating outer and inner radius
        angles = np.pi / 2 + np.arange(10) * np.pi / 5
        radii = np.where(np.arange(10) % 2, r * 0.45, r)
        points = list(zip(cx + radii * np.cos(angles), cy - radii * np.sin(angles), strict=True))
    cv2.fillPoly(img, [np.array(points, np.int32)], colour, cv2.LINE_AA)


class Memory:
    name = "memory"
    start_line = "Tap two cards to turn them over, and find the pairs that match."

    def __init__(self, rng: random.Random) -> None:
        self.deck = list(SHAPES) * 2
        rng.shuffle(self.deck)
        self.matched: set[int] = set()
        self.open: list[int] = []
        self.tries = 0
        self.due: float | None = None  # when a pair that does not match turns back over
        self.over = False

    def _card(self, x: int, y: int) -> int | None:
        col, row = (x - GRID_X) // (CARD_W + GAP), (y - GRID_Y) // (CARD_H + GAP)
        if not (0 <= col < COLS and 0 <= row < ROWS):
            return None
        inside = (x - GRID_X) % (CARD_W + GAP) < CARD_W and (y - GRID_Y) % (CARD_H + GAP) < CARD_H
        return row * COLS + col if inside else None

    def tap(self, x: int, y: int, now: float) -> list[tuple[str, str]]:
        card = self._card(x, y)
        if self.over or card is None or card in self.matched or card in self.open:
            return []
        if len(self.open) == 2:
            self.tick(now)  # a quick third tap turns the last pair back straight away
        self.open.append(card)
        if len(self.open) < 2:
            return []
        self.tries += 1
        first, second = self.open
        if self.deck[first] != self.deck[second]:
            self.due = now + config.MEMORY_PEEK_S
            return []
        self.matched |= {first, second}
        self.open = []
        if len(self.matched) < len(self.deck):
            return []
        self.over = True
        return [("note", f"You found all the pairs in {self.tries} tries, well done!")]

    def tick(self, now: float) -> list[tuple[str, str]]:
        self.open, self.due = [], None
        return []

    def status(self) -> str:
        pairs = len(self.matched) // 2
        done = " All found!" if self.over else ""
        return f"Memory match: {pairs} of {len(SHAPES)} pairs found in {self.tries} tries.{done}"

    def draw(self, img) -> None:
        import cv2

        for card, shape in enumerate(self.deck):
            x = GRID_X + (card % COLS) * (CARD_W + GAP)
            y = GRID_Y + (card // COLS) * (CARD_H + GAP)
            up = card in self.matched or card in self.open
            cv2.rectangle(img, (x, y), (x + CARD_W, y + CARD_H), FACE_UP if up else FACE_DOWN, -1)
            border = LINE if card in self.matched else ACCENT
            cv2.rectangle(img, (x, y), (x + CARD_W, y + CARD_H), border, 4)
            if up:
                _shape(img, shape, x + CARD_W // 2, y + CARD_H // 2, 48)
            else:
                text(img, "?", x + CARD_W // 2, y + CARD_H // 2, 2.2, DIM, 4)
        mid = (PANEL_X + W) // 2
        text(img, "Memory match", mid, 70, 1.3, INK, 2)
        text(img, f"Pairs: {len(self.matched) // 2} of {len(SHAPES)}", mid, 180, 1.4, ACCENT, 3)
        text(img, f"Tries: {self.tries}", mid, 250, 1.2, DIM, 2)
