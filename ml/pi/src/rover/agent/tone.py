"""Optional Jev tone selection; Claude's reply tag remains the safe default."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

from rover.agent.jev import decide

CONTEXT_LINES = 6
TONE_CRITERIA = {
    "cheerful": "greetings and everyday chat",
    "excited": "good news, a win, something to celebrate",
    "calm": "pain, worry, confusion, an emergency, or night time",
    "gentle": "sadness, loss, loneliness or bad news",
}
AskTone = Callable[[list[tuple[str, str]]], "tuple[str, float] | None"]


def _number_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value >= 0 else default


def ask_jev_tone(transcript: list[tuple[str, str]]) -> tuple[str, float] | None:
    state = "\n".join(f"{speaker}: {text}" for speaker, text in transcript[-CONTEXT_LINES:])
    answers = decide(
        state,
        {
            "tone": {
                "type": "choice",
                "instructions": "Which tone should a care-home robot use for its next reply?",
                "criteria": TONE_CRITERIA,
            }
        },
    )
    choice = answers.get("tone") if answers else None
    if not isinstance(choice, dict):
        return None
    tone, confidence = choice.get("choice"), choice.get("confidence")
    if tone not in TONE_CRITERIA or not isinstance(confidence, (int, float)):
        return None
    return tone, float(confidence)


class TonePick:
    """Gets a Jev tone in the background and never holds the voice reply for it."""

    def __init__(self, transcript: list[tuple[str, str]], ask: AskTone = ask_jev_tone) -> None:
        self._answer: tuple[str, float] | None = None
        self._done = threading.Event()
        self.tone: str | None = None
        threading.Thread(target=self._run, args=(ask, transcript), daemon=True).start()

    def _run(self, ask: AskTone, transcript: list[tuple[str, str]]) -> None:
        try:
            self._answer = ask(transcript)
        except Exception as exc:  # a Jev bug must never cost the reply its voice
            print(f"jev tone: unavailable ({type(exc).__name__})")
        finally:
            self._done.set()

    def choose(self, claude_tone: str) -> str:
        if self.tone is None:
            # Tone is cosmetic: if Jev has not returned while Claude was composing the reply,
            # use Claude's tag immediately. This method must never wait on a network request.
            if (
                self._done.is_set()
                and self._answer is not None
                and self._answer[0] in TONE_CRITERIA
                and self._answer[1] >= _number_env("JEV_MIN_CONFIDENCE", 0.7)
            ):
                self.tone = self._answer[0]
            else:
                self.tone = claude_tone
        return self.tone
