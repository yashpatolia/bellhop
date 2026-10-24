"""Text mode for the voice process: no microphone, Deepgram, Moonshine or Piper audio.

    uv run python -m rover.speech --script visit.jsonl [--live-claude]

The script is JSON lines: an optional {"greeting": "..."} and then {"say": "resident words",
"reply": "robot words"} per turn ("reply" is optional). The real Visit state machine runs on top
of it (posting turns, triage, ending, resolve, going home), so only the senses are replaced:
- the resident's lines come from the script, one at a time, when the worker is idle;
- the robot's replies come from the script (or a short default), printed instead of spoken;
- triage is a keyword mock that goes through the real merge and the real backend posts, so no
  ANTHROPIC_API_KEY is needed. --live-claude uses the real brain and real triage instead.
When the script is used up, the visit goes quiet and ends the way a silent resident's would.
"""

from __future__ import annotations

import json
import math
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from rover import config
from rover.agent.brain import Brain
from rover.backend import Backend
from rover.speech import __main__ as voice_main
from rover.speech.gates import FaceGate
from rover.speech.visit import TurnLog
from rover.triage.triage import TriageResult, triage

DEFAULT_GREETING = "Hello, I'm here. How are you today?"
DEFAULT_REPLY = "I hear you."
POLL_S = 0.02
NO_AUDIO = np.zeros(0, dtype=np.int16)

# (urgency, category, pattern): the first level that matches, from the top, wins
KEYWORDS: list[tuple[int, str, re.Pattern[str]]] = [
    (
        4,
        "fall",
        re.compile(r"\b(fell|fallen|on the floor|cant get up|can t get up)\b"),
    ),
    (
        4,
        "cardiac",
        re.compile(r"\b(chest (pain|hurts|is tight)|heart attack)\b"),
    ),
    (4, "respiratory", re.compile(r"\b(cant|can t|cannot|hard to) breathe?\b|\bbreathing\b")),
    (3, "asks_for_nurse", re.compile(r"\b(nurse|doctor|someone to come|a real person)\b")),
    (3, "pain", re.compile(r"\b(hurts?|pain|dizzy|sick|nauseous)\b")),
    (2, "request", re.compile(r"\b(water|blanket|glasses|tea|toilet|bathroom|cold)\b")),
]


def _normal(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text.lower().replace("'", "")).split())


def score_text(text: str) -> tuple[int, str]:
    plain = _normal(text)
    for urgency, category, pattern in KEYWORDS:
        if pattern.search(plain):
            return urgency, category
    return 1, "social"


def mock_triage(transcript: list[tuple[str, str]], risk_flags: list[str]) -> TriageResult | None:
    """A stand-in for the models: the most urgent resident line decides."""
    said = [text for speaker, text in transcript if speaker == "resident"]
    if not said:
        return None
    urgency, category = max((score_text(line) for line in said), key=lambda pair: pair[0])
    return TriageResult(urgency, category, f"Resident said: {said[-1][:200]}", 0.9, "mock")


def mock_triage_and_post(
    backend: Backend, call_id: str, transcript: list[tuple[str, str]], risk_flags: list[str]
) -> dict | None:
    """rover.triage.triage_and_post with the mock as the only model (local scorer off)."""
    result = triage(
        transcript,
        risk_flags,
        ask_jev=lambda t, f: None,
        ask_claude=lambda t, f: mock_triage(t, f),
    )
    if result is None:
        print("fallback: triage failed (mock answered nothing), posting triage-failed")
        return backend.triage_failed(call_id)
    print(
        f"triage: urgency {result.urgency} {result.category} (confidence {result.confidence:.2f})"
    )
    return backend.score(
        call_id, result.urgency, result.category, result.summary, result.confidence
    )


@dataclass
class ScriptTurn:
    say: str
    reply: str | None = None
    pause_s: float = 0.0  # wait this long after this turn before the next one


@dataclass
class Script:
    greeting: str = DEFAULT_GREETING
    turns: list[ScriptTurn] = field(default_factory=list)


def load_script(path: str | os.PathLike) -> Script:
    script = Script()
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise ValueError(f"{path}: line {number}: not JSON ({exc})") from None
        if not isinstance(row, dict):
            raise ValueError(f"{path}: line {number}: expected a JSON object")
        if "greeting" in row and "say" not in row:
            greeting = row["greeting"]
            if not isinstance(greeting, str) or not greeting.strip():
                raise ValueError(f"{path}: line {number}: greeting must be non-empty text")
            script.greeting = greeting
            continue
        say, reply = row.get("say"), row.get("reply")
        if not isinstance(say, str) or not say.strip():
            raise ValueError(f"{path}: line {number}: 'say' must be non-empty text")
        if reply is not None and not isinstance(reply, str):
            raise ValueError(f"{path}: line {number}: 'reply' must be text")
        pause = row.get("pause_s", 0.0)
        if isinstance(pause, bool) or not isinstance(pause, int | float) or not 0 <= pause <= 600:
            raise ValueError(f"{path}: line {number}: 'pause_s' must be a number from 0 to 600")
        script.turns.append(ScriptTurn(say.strip(), reply, float(pause)))
    return script


class ScriptedBrain:
    """Brain.reply stand-in: the greeting first, then each turn's scripted reply in order."""

    def __init__(self, script: Script) -> None:
        self.script = script
        self._replies = [script.greeting] + [t.reply or DEFAULT_REPLY for t in script.turns]
        self._next = 0
        self._lock = threading.Lock()

    def reply(self, system, messages, on_sentence, tool_ctx, allow_tools=True, cancel=None):
        with self._lock:
            text = self._replies[min(self._next, len(self._replies) - 1)]
            self._next += 1
        on_sentence("calm", text)
        return text, False


class PrintVoice:
    settings: dict | None = None

    def say(self, sentence: str, tone: str) -> None:
        print(f"robot: {sentence}")


class TextVisit(voice_main.Visit):
    """The real Visit with its inputs swapped: script for the mic, mock for the models."""

    def __init__(
        self,
        call: dict,
        room: str,
        backend: Backend,
        script: Script,
        live_claude: bool = False,
    ) -> None:
        super().__init__(
            call,
            room,
            backend,
            Brain() if live_claude else ScriptedBrain(script),
            PrintVoice(),
            None,
            NoVision(),
            FaceGate(None, disabled=True),
            gates=_NoGates(),
            triage_fn=None if live_claude else mock_triage_and_post,
        )
        self.script = script
        if not live_claude:
            self.ask_tone = None  # offline mocks: no Jev call for the tone either
        runs = os.environ.get("ROVER_TEXT_RUNS") or str(Path(tempfile.gettempdir()) / "rover-text")
        self.log = TurnLog(Path(runs))

    def run(self) -> None:
        self.begin()
        self.submit(self.greet)
        pending = list(self.script.turns)
        exhausted = False
        not_before = 0.0
        try:
            while not (self.done and self.idle()):
                now = time.monotonic()
                if self.idle() and self.phase == "talk" and now >= not_before:
                    if pending:
                        turn = pending.pop(0)
                        not_before = now + turn.pause_s
                        self.submit(
                            self.handle_turn, turn.say, "script", NO_AUDIO, 0.0, now, None, True
                        )
                    elif not exhausted:
                        exhausted = True
                        self.last_activity = now - config.VISIT_QUIET_END_S  # the quiet starts
                self.check_timers(now)
                time.sleep(POLL_S)
        finally:
            self.phase = "over"
            self.pool.shutdown(wait=False, cancel_futures=True)
        print(f"visit: call {self.call_id} done")


class NoVision:
    """VisionListener stand-in: no camera, so the prompt gets no scene note."""

    def latest(self) -> dict | None:
        return None

    def age(self, now: float) -> float:
        return math.inf


class _NoGates:
    """Visit.record_robot opens the attention window on Gates; text mode has no audio gates."""

    def open_attention(self, now: float) -> None:
        pass
