"""Games on the touchscreen: bingo, tic-tac-toe and memory match, opened by Claude's start_game.

A game opens on a start screen (pulsing rings, "Touch and hold to start"), so a brush of the screen
starts nothing; holding GAME_HOLD_S starts it. One thread draws, and only when something changed:
a touch, a tool call, or the game's own timer (the robot's move, cards turning back). Between
those it sleeps, so a game left alone costs no CPU. The robot's lines go to the visit as events:
("GameSay", line) is spoken, ("GameNote", line) is spoken and kept in the transcript, and
("GameTouch", "") tells the visit the resident is busy playing, not gone quiet.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable

from rover import config
from rover.games.bingo import Bingo
from rover.games.draw import ACCENT, AGAIN, BG, DIM, FINISH, INK, H, W, canvas, text
from rover.games.memory import Memory
from rover.games.tictactoe import TicTacToe, next_slip
from rover.touch import Touch

GAMES = {"bingo": "bingo", "tic_tac_toe": "tic-tac-toe", "memory": "memory match"}  # id: spoken
Post = Callable[[tuple[str, str, float]], None]


class Games:
    def __init__(self, eyes=None, rng: random.Random | None = None) -> None:
        self.eyes = eyes  # its screen shows the game; its face pauses while one is open
        self.rng = rng or random.Random()
        self.slip = config.TICTACTOE_SLIP_START  # carried from game to game: see tictactoe.py
        self.touchable = False
        self.name: str | None = None
        self.game = None
        self.phase: str | None = None  # None, "intro" (the start screen) or "play"
        self.redraws = 0
        self._post: Post | None = None
        self._cond = threading.Condition()  # guards everything above; notified to wake the thread
        self._touches: list[tuple[str, int, int]] = []
        self._dirty = False
        self._held_since: float | None = None
        self._intro_from = self._intro_until = self._next_frame = 0.0
        self._scored = False

    @property
    def screen(self):
        return self.eyes.screen if self.eyes is not None else None

    def start_threads(self, read_touch: bool = True) -> Games:
        """Run the drawing thread, and read the panel (read_touch=False: the caller feeds touch)."""
        threading.Thread(target=self._run, daemon=True, name="games").start()
        if self.screen is None:
            return self
        if not read_touch:
            self.touchable = True
            return self
        try:
            panel = Touch.open(self.screen.size, self.touch)
        except Exception as exc:  # noqa: BLE001 - no /dev/input on a Mac, no permission, unplugged
            print(f"fallback: no touch panel, so no games ({type(exc).__name__}: {exc})")
            return self
        self.touchable = True
        threading.Thread(target=panel.run, daemon=True, name="touch").start()
        return self

    def attach(self, post: Post | None) -> None:
        """Where the robot's lines go: the current visit's event queue, or None between visits."""
        with self._cond:
            self._post = post

    # ---- called from other threads: the brain's tools, the touch panel

    def start(self, name: str, now: float | None = None) -> str:
        if name not in GAMES:
            return f"there is no game {name!r}; the games are {', '.join(GAMES)}"
        if self.screen is None or not self.touchable:
            return "the screen is not available, so you cannot play a game now"
        now = time.monotonic() if now is None else now
        with self._cond:
            if self.name == name and self.phase is not None and not (self.game and self.game.over):
                # Claude does not see its own earlier tool calls: a reset would wipe the board
                if self.phase == "intro":  # it asked again, so the start screen waits longer
                    self._intro_until = now + config.GAME_INTRO_TIMEOUT_S
                return f"{GAMES[name]} is already open, do not start it again. {self.status()}"
            self.name, self.game, self.phase = name, None, "intro"
            self._intro_from = self._next_frame = now
            self._intro_until = now + config.GAME_INTRO_TIMEOUT_S
            self._held_since = None
            self._touches.clear()
            with self.screen.lock:
                self.eyes.paused = True
            self._dirty = True
            self._cond.notify()
        print(f"games: {name} opened")
        return f"{GAMES[name]} is on the screen; tell the resident to touch and hold it to start"

    def stop(self, note: str | None = None) -> str:
        with self._cond:
            if self.phase is None:
                return "no game was open"
            print(f"games: {self.name} closed")
            self.name, self.game, self.phase = None, None, None
            self._touches.clear()
            if self.eyes is not None:
                self.eyes.paused = False  # the face's next frame repaints the whole screen
            if note:
                self._send("GameNote", note)
            self._cond.notify()
        return "the game is closed and your face is back on the screen"

    def status(self) -> str | None:
        with self._cond:
            if self.phase == "intro":
                title = GAMES[self.name].capitalize()
                return f"{title} is on its start screen, waiting for a touch and hold."
            if self.phase == "play":
                return self.game.status()
            return None

    def touch(self, kind: str, x: int, y: int) -> None:
        """kind "down", "move" or "up" at (x, y) screen pixels."""
        width, height = self.screen.size if self.screen is not None else (W, H)
        with self._cond:
            if self.phase is None:
                return
            self._touches.append((kind, x * W // width, y * H // height))  # to canvas pixels
            self._cond.notify()

    # ---- the drawing thread

    def _run(self) -> None:
        with self._cond:
            while True:
                self.step(time.monotonic())
                self._cond.wait(self._wait_s(time.monotonic()))

    def _wait_s(self, now: float) -> float | None:
        if self.phase == "intro":
            return max(0.0, min(self._next_frame, self._intro_until) - now)
        if self.phase == "play" and self.game.due is not None:
            return max(0.0, self.game.due - now)
        return None  # nothing to do until a touch or a tool call

    def step(self, now: float) -> None:
        """Handle what happened since the last step, and redraw if anything changed."""
        with self._cond:
            touches, self._touches = self._touches, []
            changed, self._dirty = self._dirty, False
            for kind, x, y in touches:
                self._send("GameTouch", "")
                changed |= self._on_touch(kind, x, y, now)
            if self.phase == "intro":
                changed |= self._intro(now)
            if self.phase == "play" and self.game.due is not None and now >= self.game.due:
                self._after(self.game.tick(now))
                changed = True
            if changed and self.phase is not None:
                self._draw(now)

    def _on_touch(self, kind: str, x: int, y: int, now: float) -> bool:
        if self.phase == "intro":
            if kind == "down" or (kind == "move" and self._held_since is None):
                # a move with no hold: the finger was already down when the start screen came up
                self._held_since, self._intro_until = now, now + config.GAME_INTRO_TIMEOUT_S
                return True
            if kind == "up":
                self._held_since = None
                return True
            return False
        if self.phase != "play" or kind != "down":
            return False
        if FINISH.hit(x, y):
            self.stop("Thanks for playing with me!")
            return False
        if self.game.over:
            if AGAIN.hit(x, y):
                self._new_game(say_how=False)
                return True
            return False
        self._after(self.game.tap(x, y, now))
        return True

    def _intro(self, now: float) -> bool:
        if self._held_since is not None and now - self._held_since >= config.GAME_HOLD_S:
            self._new_game(say_how=True)
            return True
        if self._held_since is None and now >= self._intro_until:
            self.stop("No problem, I've put the game away.")
            return False
        if now < self._next_frame:
            return False
        self._next_frame = now + 1 / config.GAME_INTRO_FPS
        return True

    def _new_game(self, say_how: bool) -> None:
        if self.name == "bingo":
            self.game = Bingo(self.rng)
        elif self.name == "tic_tac_toe":
            self.game = TicTacToe(self.rng, self.slip)
        else:
            self.game = Memory(self.rng)
        self.phase, self._scored = "play", False
        if say_how:
            self._send("GameSay", self.game.start_line)

    def _after(self, lines: list[tuple[str, str]]) -> None:
        for kind, line in lines:
            self._send("GameNote" if kind == "note" else "GameSay", line)
        if self.game.over and not self._scored and isinstance(self.game, TicTacToe):
            self._scored = True
            self.slip = next_slip(self.slip, robot_lost=self.game.result == "won")

    def _send(self, kind: str, line: str) -> None:
        if line:
            print(f"games: {kind} {line!r}")
        if self._post is not None:
            self._post((kind, line, time.monotonic()))

    def _draw(self, now: float) -> None:
        img = canvas()
        if self.phase == "intro":
            self._draw_intro(img, now)
        else:
            self.game.draw(img)
            FINISH.draw(img, DIM)
            if self.game.over:
                AGAIN.draw(img)
        screen = self.screen
        if screen is not None:
            with screen.lock:
                screen.show_image(img)
        self.redraws += 1

    def _draw_intro(self, img, now: float) -> None:
        import cv2

        cx, cy = W // 2, H // 2 + 10
        text(img, GAMES[self.name].capitalize(), cx, 60, 1.8, INK, 3)
        pulse = (now - self._intro_from) * 0.8 % 1.0  # a ring leaves the centre every 1.25 s
        for k in range(3):
            spread = (pulse + k / 3) % 1.0
            colour = tuple(int(a + (b - a) * spread) for a, b in zip(ACCENT, BG, strict=True))
            cv2.circle(img, (cx, cy), int(60 + 170 * spread), colour, 4, cv2.LINE_AA)
        cv2.circle(img, (cx, cy), 50, ACCENT, -1, cv2.LINE_AA)  # press here (anywhere works)
        if self._held_since is not None:
            done = min(1.0, (now - self._held_since) / config.GAME_HOLD_S)
            cv2.ellipse(img, (cx, cy), (76, 76), -90, 0, 360 * done, INK, 12, cv2.LINE_AA)
        text(img, "Touch and hold to start", cx, H - 50, 1.5, INK, 3)
