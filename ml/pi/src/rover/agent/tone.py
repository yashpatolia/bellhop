"""Jev picks each reply's tone tag (so the voice and the OLED eyes) while Claude writes the reply.

Claude's own tag is the backup: used when Jev has no key, fails, is unsure (below
JEV_MIN_CONFIDENCE) or has not answered by the first sentence. One tone per reply, like Claude's.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Callable

from typesafe_sdk import Choice, RetryPolicy, TypeSafeClient, TypeSafeError

from rover import config

CONTEXT_LINES = 6  # the end of the conversation is what sets the mood
TONE_CRITERIA = {  # same rules as persona.md gives Claude
    "cheerful": "greetings and everyday chat",
    "excited": "good news, a win, something to celebrate",
    "calm": "pain, worry, confusion, an emergency, or night time",
    "gentle": "sadness, loss, loneliness or bad news",
}
AskTone = Callable[[list[tuple[str, str]]], "tuple[str, float] | None"]


def ask_jev_tone(transcript: list[tuple[str, str]]) -> tuple[str, float] | None:
    """(tone, confidence) for the robot's next reply, or None."""
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        print("fallback: no TYPESAFE_API_KEY, Claude's tone tag used")
        return None
    state = "\n".join(f"{speaker}: {text}" for speaker, text in transcript[-CONTEXT_LINES:])
    try:
        with TypeSafeClient(
            model=config.JEV_MODEL,
            timeout=config.JEV_TIMEOUT_S,
            retry=RetryPolicy(max_retries=0),
        ) as client:
            result = client.system_one(
                state=state,
                questions={
                    "tone": Choice(
                        instructions=(
                            "A care-home robot is about to reply to the resident. Which tone "
                            "should its reply have?"
                        ),
                        criteria=TONE_CRITERIA,
                    )
                },
            )
    except TypeSafeError as exc:
        print(f"tone: Jev failed: {type(exc).__name__}: {exc}")
        return None
    choice = result.choices.get("tone")
    if choice is None or choice.choice not in config.TONES:
        print(f"tone: Jev gave no usable tone: {choice}")
        return None
    return choice.choice, choice.confidence


class TonePick:
    """Asks Jev in the background as soon as the resident's turn is in."""

    def __init__(self, transcript: list[tuple[str, str]], ask: AskTone = ask_jev_tone) -> None:
        self._answer: tuple[str, float] | None = None
        self._done = threading.Event()
        self.tone: str | None = None
        threading.Thread(target=self._run, args=(ask, transcript), daemon=True).start()

    def _run(self, ask: AskTone, transcript: list[tuple[str, str]]) -> None:
        try:
            self._answer = ask(transcript)
        except Exception as exc:  # noqa: BLE001 - a bug here must not cost the reply its voice
            print(f"tone: Jev crashed: {exc!r}")
        finally:
            self._done.set()

    def choose(self, claude_tone: str) -> str:
        """The reply's tone, fixed at its first sentence: Jev's when it is sure, else Claude's."""
        if self.tone is None:
            answered = self._done.wait(config.JEV_TONE_WAIT_S)
            answer = self._answer
            if answer is not None and answer[1] >= config.JEV_MIN_CONFIDENCE:
                self.tone = answer[0]
            else:
                if not answered:
                    print(f"fallback: Jev's tone not ready, using Claude's [{claude_tone}]")
                elif answer is not None:
                    print(f"fallback: Jev unsure of the tone ({answer[1]:.2f}), [{claude_tone}]")
                self.tone = claude_tone
        return self.tone
