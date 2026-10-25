"""Tic-tac-toe: the resident is X and goes first; the robot is O and loses about 60% of games.

The robot plays perfectly (it can never lose) except for a `slip` chance of a random move, so the
slip alone sets how often it loses. next_slip() nudges it after every game, so the robot settles
at TICTACTOE_TARGET_LOSS losses against an expert, a casual player and a confused one alike.
"""

from __future__ import annotations

import functools
import random

from rover import config
from rover.games.draw import ACCENT, INK, LINE, PANEL_X, ROBOT, W, text

LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))
CELL, BOARD_X, BOARD_Y = 180, 40, 30  # a 540 px board
RESULT = {
    "won": "Three in a row, you win! Well played.",
    "lost": "I got three in a row this time. Good game!",
    "draw": "It's a draw. We're well matched!",
}


def winner(board: list[str] | tuple[str, ...]) -> str | None:
    for a, b, c in LINES:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return None


def _completes(board: list[str], mark: str) -> int | None:
    """The empty cell that would give `mark` three in a row."""
    for line in LINES:
        marks = [board[i] for i in line]
        if marks.count(mark) == 2 and marks.count("") == 1:
            return line[marks.index("")]
    return None


@functools.cache  # at most 3^9 boards, a few ms to fill on the first move
def _score(board: tuple[str, ...], turn: str) -> int:
    """1 if O can force a win from here, -1 if X can, 0 if perfect play draws."""
    win = winner(board)
    if win or all(board):
        return {"O": 1, "X": -1, None: 0}[win]
    after = "X" if turn == "O" else "O"
    scores = [
        _score(board[:i] + (turn,) + board[i + 1 :], after) for i, m in enumerate(board) if not m
    ]
    return max(scores) if turn == "O" else min(scores)


def robot_move(board: list[str], slip: float, rng: random.Random) -> int:
    empty = [i for i, mark in enumerate(board) if not mark]
    if rng.random() < slip:
        return rng.choice(empty)
    cell = _completes(board, "O")
    if cell is not None:
        return cell  # a win now, not a slower forced one
    scores = {i: _score(tuple(board[:i] + ["O"] + board[i + 1 :]), "X") for i in empty}
    best = max(scores.values())
    return rng.choice([i for i, score in scores.items() if score == best])  # varied, all as good


def next_slip(slip: float, robot_lost: bool) -> float:
    """Down a step after a loss, up after a win or draw: they balance at the target loss rate."""
    down = config.TICTACTOE_SLIP_STEP
    up = down * config.TICTACTOE_TARGET_LOSS / (1 - config.TICTACTOE_TARGET_LOSS)
    return min(0.95, max(0.05, slip - down if robot_lost else slip + up))


class TicTacToe:
    name = "tic_tac_toe"
    start_line = "You're the crosses, so you go first. Tap a square."

    def __init__(self, rng: random.Random, slip: float) -> None:
        self.rng, self.slip = rng, slip
        self.board = [""] * 9
        self.due: float | None = None  # when the robot moves
        self.over = False
        self.result: str | None = None  # the resident's: won, lost or draw

    def _cell(self, x: int, y: int) -> int | None:
        col, row = (x - BOARD_X) // CELL, (y - BOARD_Y) // CELL
        return row * 3 + col if 0 <= col < 3 and 0 <= row < 3 else None

    def tap(self, x: int, y: int, now: float) -> list[tuple[str, str]]:
        cell = self._cell(x, y)
        if self.over or self.due is not None or cell is None or self.board[cell]:
            return []
        self.board[cell] = "X"
        lines = self._check()
        if not self.over:
            self.due = now + config.TICTACTOE_MOVE_DELAY_S
        return lines

    def tick(self, now: float) -> list[tuple[str, str]]:
        self.due = None
        self.board[robot_move(self.board, self.slip, self.rng)] = "O"
        return self._check()

    def _check(self) -> list[tuple[str, str]]:
        win = winner(self.board)
        if win is None and not all(self.board):
            return []
        self.over = True
        self.result = {"X": "won", "O": "lost", None: "draw"}[win]
        return [("note", RESULT[self.result])]

    def status(self) -> str:
        rows = " / ".join(" ".join(m or "." for m in self.board[r : r + 3]) for r in (0, 3, 6))
        if self.over:
            now = {"won": "the resident won", "lost": "you won", "draw": "a draw"}[self.result]
        else:
            now = "your move" if self.due is not None else "the resident's turn"
        return f"Tic-tac-toe: the resident is X, you are O. Board: {rows}. Now: {now}."

    def draw(self, img) -> None:
        import cv2

        end = 3 * CELL
        for i in (1, 2):
            x, y = BOARD_X + i * CELL, BOARD_Y + i * CELL
            cv2.line(img, (x, BOARD_Y + 12), (x, BOARD_Y + end - 12), LINE, 6, cv2.LINE_AA)
            cv2.line(img, (BOARD_X + 12, y), (BOARD_X + end - 12, y), LINE, 6, cv2.LINE_AA)
        r = CELL // 2 - 38
        for i, mark in enumerate(self.board):
            cx, cy = BOARD_X + (i % 3) * CELL + CELL // 2, BOARD_Y + (i // 3) * CELL + CELL // 2
            if mark == "X":
                cv2.line(img, (cx - r, cy - r), (cx + r, cy + r), ACCENT, 16, cv2.LINE_AA)
                cv2.line(img, (cx - r, cy + r), (cx + r, cy - r), ACCENT, 16, cv2.LINE_AA)
            elif mark == "O":
                cv2.circle(img, (cx, cy), r, ROBOT, 14, cv2.LINE_AA)
        mid = (PANEL_X + W) // 2
        text(img, "Tic-tac-toe", mid, 70, 1.4, INK, 2)
        if self.over:
            words = {"won": "You win!", "lost": "I win!", "draw": "A draw!"}[self.result]
        else:
            words = "My move..." if self.due is not None else "Your turn"
        text(img, words, mid, 220, 2.0, ROBOT if self.due is not None else ACCENT, 4)
