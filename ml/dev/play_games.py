"""(Mac) Play the robot's games in a window the size of its screen, with the mouse as a finger.

    cd ml/pi && uv run python ../dev/play_games.py [--talk] [--voice]

Keys: 1 bingo, 2 tic-tac-toe, 3 memory match, 0 close the game, q quit. A game opens on its start
screen: press and hold the mouse for a second. The real controller and games run; only the screen
(this window) and the touch panel (the mouse) are stand-ins.

--talk: chat in this terminal as the resident with the real Claude brain (ANTHROPIC_API_KEY). It
greets you, and opens a game only when you ask for one. "Knows how to play" facts go to
runs/sim_memory.json instead of the backend, so a second run remembers them.
--voice: also speak the robot's lines with macOS `say`.
Success looks like: each game plays, Finish brings the eyes back, and "redraws" stays at 0 while
nothing is touched.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from rover import config
from rover.agent.brain import WAIT, Brain
from rover.agent.context import (
    GAMES_QUERY,
    GREETING,
    VisitHistory,
    build_system_prompt,
    games_known,
)
from rover.agent.tools import ToolContext
from rover.eyes import Eyes
from rover.games import Games

WINDOW = "bellhop screen"
KEYS = {ord("1"): "bingo", ord("2"): "tic_tac_toe", ord("3"): "memory"}
RESIDENT = {"id": "sim", "name": "Margaret", "room": "12"}
REPORT_S = 5.0


class WindowScreen:
    """The 7 inch screen as an OpenCV window: the face and the games both draw here."""

    size, scale = config.GAME_CANVAS, 8

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.image = np.zeros((self.size[1], self.size[0], 3), np.uint8)

    def show(self, frame: np.ndarray) -> None:  # the face, letterboxed like on the real screen
        image = np.zeros_like(self.image)
        top = (self.size[1] - frame.shape[0]) // 2
        image[top : top + frame.shape[0]][frame] = config.EYES_RGB[::-1]
        self.image = image

    def show_image(self, bgr: np.ndarray) -> None:
        self.image = bgr


class SimBackend:
    """The Bellhop API stand-in for --talk: memory facts in a JSON file, nothing else."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def _facts(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return []

    def remember(self, resident_id: str, text: str, tags: list[str]) -> dict | None:
        facts = self._facts()
        if any(fact["text"] == text for fact in facts):
            print(f"memory: already knew {text!r}")
            return None
        facts.append({"text": text, "tags": tags})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(facts, indent=1))
        print(f"memory: saved {text!r} to {self.path}")
        return facts[-1]

    def memory(self, resident_id: str, q: str = "", k: int = 3) -> list[dict]:
        return self._facts()[:k]

    def score(self, *args) -> dict:
        print("backend (sim): request_staff would tell a nurse")
        return {"id": "sim"}


def say(line: str, voice: bool, wait: bool) -> None:
    if voice:
        (subprocess.run if wait else subprocess.Popen)(["say", line])


def chat(games: Games, history: VisitHistory, lock: threading.Lock, voice: bool) -> None:
    """The resident's side of a visit, typed in this terminal."""
    brain, backend = Brain(), SimBackend(config.RUNS_DIR / "sim_memory.json")
    ctx = ToolContext(backend, "sim", RESIDENT["id"], games)

    def speak(tone: str, sentence: str) -> None:
        print(f"robot [{tone}]: {sentence}")
        say(sentence, voice, wait=True)

    def reply(messages: list[dict]) -> None:
        known = games_known(backend.memory(RESIDENT["id"], q=GAMES_QUERY, k=10))
        system = build_system_prompt(
            RESIDENT, None, [], "", None, datetime.now(), known, games.status()
        )
        full, _ = brain.reply(system, messages, speak, ctx)
        if full and full != WAIT:
            with lock:
                history.add("robot", full)

    reply([{"role": "user", "content": GREETING.format(room=RESIDENT["room"])}])
    while True:
        try:
            line = input("you: ").strip()
        except EOFError:
            return
        if line:
            with lock:
                history.add("resident", line)
                messages = history.messages()
            reply(messages)


def main() -> None:
    parser = argparse.ArgumentParser(description="Play the robot's games on the Mac")
    parser.add_argument("--talk", action="store_true", help="chat with the real Claude brain")
    parser.add_argument("--voice", action="store_true", help="speak the robot's lines (say)")
    args = parser.parse_args()
    if args.talk and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("--talk needs ANTHROPIC_API_KEY in ml/pi/.env")

    screen = WindowScreen()
    eyes = Eyes(screen)
    games = Games(eyes).start_threads(read_touch=False)
    history, lock = VisitHistory(), threading.Lock()

    def post(event: tuple[str, str, float]) -> None:  # the visit's role: speak and keep lines
        kind, line, _ = event
        if kind == "GameTouch":
            return
        say(line, args.voice, wait=False)
        if kind == "GameNote":
            with lock:
                history.add("robot", line)

    games.attach(post)

    def on_mouse(event: int, x: int, y: int, flags: int, _) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            games.touch("down", x, y)
        elif event == cv2.EVENT_LBUTTONUP:
            games.touch("up", x, y)
        elif event == cv2.EVENT_MOUSEMOVE and flags & cv2.EVENT_FLAG_LBUTTON:
            games.touch("move", x, y)

    cv2.namedWindow(WINDOW)
    cv2.setMouseCallback(WINDOW, on_mouse)
    if args.talk:
        threading.Thread(target=chat, args=(games, history, lock, args.voice), daemon=True).start()
    print("keys (in the window): 1 bingo, 2 tic-tac-toe, 3 memory match, 0 close, q quit")
    reported_at, reported = time.monotonic(), games.redraws
    while True:
        eyes.tick()  # on this thread: macOS only draws windows from the main thread
        cv2.imshow(WINDOW, screen.image)
        key = cv2.waitKey(1000 // config.EYES_FPS) & 0xFF
        if key == ord("q"):
            break
        if key in KEYS:
            print(games.start(KEYS[key]))
        elif key == ord("0"):
            print(games.stop())
        now = time.monotonic()
        if now - reported_at >= REPORT_S:
            if games.phase == "play":
                print(f"redraws: {games.redraws - reported} in the last {REPORT_S:g} s")
            reported_at, reported = now, games.redraws
    cv2.destroyAllWindows()
    print(f"success: {games.redraws} game redraws in all")


if __name__ == "__main__":
    main()
