"""Bingo: a 5x5 card with a free centre. "Next number" calls one, and it is crossed off the card.

The resident sets the pace, so nothing runs between calls. A called number on the card is crossed
off for them (and the robot says so), and a full row, column or diagonal is struck through: Bingo.
"""

from __future__ import annotations

import random

from rover.games.draw import ACCENT, DIM, INK, LINE, PANEL_X, Button, W, text

LETTERS = "BINGO"
FREE = 0  # the centre square has no number
CARD_X, CARD_Y, HEADER_H = 30, 20, 80
CELL_W, CELL_H = 116, 96  # 5 columns of 116 px, then 5 rows of 96 px under the header
NEXT = Button("Next number", PANEL_X, 300, W - 24, 390)
Cell = tuple[int, int]  # (row, column)


def call_label(number: int) -> str:
    return f"{LETTERS[(number - 1) // 15]} {number}"


def make_card(rng: random.Random) -> list[list[int]]:
    columns = [rng.sample(range(1 + 15 * c, 16 + 15 * c), 5) for c in range(5)]
    card = [[columns[c][r] for c in range(5)] for r in range(5)]
    card[2][2] = FREE
    return card


def winning_line(marked: list[list[bool]]) -> list[Cell] | None:
    """The first full row, column or diagonal, as its five cells."""
    lines = [[(r, c) for c in range(5)] for r in range(5)]
    lines += [[(r, c) for r in range(5)] for c in range(5)]
    lines += [[(i, i) for i in range(5)], [(i, 4 - i) for i in range(5)]]
    return next((line for line in lines if all(marked[r][c] for r, c in line)), None)


def _centre(cell: Cell) -> tuple[int, int]:
    row, col = cell
    return CARD_X + col * CELL_W + CELL_W // 2, CARD_Y + HEADER_H + row * CELL_H + CELL_H // 2


class Bingo:
    name = "bingo"
    start_line = "Tap Next number and I'll call it out. If it's on your card, I'll cross it off."

    def __init__(self, rng: random.Random) -> None:
        self.card = make_card(rng)
        self.marked = [[number == FREE for number in row] for row in self.card]
        self.pool = rng.sample(range(1, 76), 75)  # every number once, in a random order
        self.called: list[int] = []
        self.just: Cell | None = None  # the square the last call crossed off
        self.line: list[Cell] | None = None
        self.due: float | None = None  # bingo never waits on a timer
        self.over = False

    def tap(self, x: int, y: int, now: float) -> list[tuple[str, str]]:
        if self.over or not NEXT.hit(x, y):
            return []
        if not self.pool:
            return [("say", "That was every number.")]
        number = self.pool.pop()
        self.called.append(number)
        found = [
            (r, c) for r, row in enumerate(self.card) for c, n in enumerate(row) if n == number
        ]
        self.just = found[0] if found else None
        if self.just is None:
            return [("say", call_label(number))]
        self.marked[self.just[0]][self.just[1]] = True
        lines = [("say", f"{call_label(number)}, you've got that one!")]
        self.line = winning_line(self.marked)
        if self.line is not None:
            self.over = True
            lines.append(("note", "Bingo! That's a full line, well done!"))
        return lines

    def tick(self, now: float) -> list[tuple[str, str]]:
        return []

    def status(self) -> str:
        crossed = sum(map(sum, self.marked)) - 1  # not the free centre
        last = f", the last was {call_label(self.called[-1])}" if self.called else ""
        state = "They got a full line: Bingo!" if self.over else f"{crossed} of 24 crossed off."
        return f"Bingo: {len(self.called)} numbers called{last}. {state}"

    def draw(self, img) -> None:
        import cv2

        for col, letter in enumerate(LETTERS):
            x = CARD_X + col * CELL_W + CELL_W // 2
            text(img, letter, x, CARD_Y + HEADER_H // 2, 2.0, ACCENT, 4)
        arm = CELL_H // 2 - 14
        for row in range(5):
            for col in range(5):
                x, y = CARD_X + col * CELL_W, CARD_Y + HEADER_H + row * CELL_H
                cx, cy = _centre((row, col))
                cv2.rectangle(img, (x, y), (x + CELL_W, y + CELL_H), LINE, 3)
                number, crossed = self.card[row][col], self.marked[row][col]
                words = "FREE" if number == FREE else str(number)
                text(img, words, cx, cy, 0.9 if number == FREE else 1.4, DIM if crossed else INK, 3)
                if crossed:
                    cv2.line(
                        img, (cx - arm, cy - arm), (cx + arm, cy + arm), ACCENT, 8, cv2.LINE_AA
                    )
                    cv2.line(
                        img, (cx - arm, cy + arm), (cx + arm, cy - arm), ACCENT, 8, cv2.LINE_AA
                    )
        if self.just is not None and not self.over:  # point out the square that was just called
            x, y = CARD_X + self.just[1] * CELL_W, CARD_Y + HEADER_H + self.just[0] * CELL_H
            cv2.rectangle(img, (x + 4, y + 4), (x + CELL_W - 4, y + CELL_H - 4), INK, 5)
        if self.line is not None:  # strike through the winning line
            cv2.line(img, _centre(self.line[0]), _centre(self.line[-1]), INK, 14, cv2.LINE_AA)
        mid = (PANEL_X + W) // 2
        if self.over:
            text(img, "BINGO!", mid, 120, 2.6, ACCENT, 6)
        elif self.called:
            text(img, call_label(self.called[-1]), mid, 120, 3.0, ACCENT, 6)
            earlier = ", ".join(call_label(n) for n in self.called[-5:-1][::-1])
            text(img, earlier, mid, 230, 0.9, DIM, 2)
        else:
            text(img, "Bingo", mid, 120, 2.0, INK, 3)
        if not self.over:
            NEXT.draw(img)
