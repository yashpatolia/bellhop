"""Pure decisions for one visit, plus the per-turn debug log. No hardware, no network."""

from __future__ import annotations

import json
import math
import re
import time
import wave
from datetime import date
from pathlib import Path

import numpy as np

from rover import config
from rover.agent.context import VisitHistory

GOODBYE = re.compile(r"\b(good ?bye|bye|see you (later|soon)|not now)\b")


def normalize(text: str) -> str:
    text = text.lower().replace("'", "").replace("’", "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def is_goodbye(text: str) -> bool:
    return GOODBYE.search(normalize(text)) is not None


def is_echo(text: str, last_reply: str) -> bool:
    """The robot hearing its own last reply (whole, or a run of its words)."""
    heard, said = normalize(text), normalize(last_reply)
    if len(heard.split()) < config.ECHO_MIN_WORDS:
        return False
    return f" {heard} " in f" {said} "


def drop_reason(text: str, last_reply: str) -> str | None:
    """Why a finished turn should be ignored, or None to accept it. Not facing the robot is no
    reason: such a turn is still posted and triaged, only not answered."""
    if not normalize(text):
        return "empty transcript"
    if is_echo(text, last_reply):
        return "echo of the robot's last reply"
    return None


def should_start_visit(
    marker_m: float | None, facing_s: float, waited_s: float, forced: bool
) -> str | None:
    """Reason to start the visit now, or None to keep waiting."""
    if forced:
        return "call given on the command line"
    if marker_m is not None and math.isfinite(marker_m) and marker_m <= config.ARRIVE_DISTANCE_M:
        return f"room marker at {marker_m:.2f} m"
    if facing_s >= config.FACE_START_S:
        return f"face facing for {facing_s:.1f} s"
    if waited_s >= config.VISIT_START_FALLBACK_S:
        return "timeout"
    return None


def resolve_decision(urgency: object, triaged: bool = False) -> str:
    """ "robot" resolves the call now; "wait_nurse" stays until a nurse acknowledges.

    No urgency is only safe when nothing was triaged; after triage it means no score landed.
    """
    if urgency is None:
        return "wait_nurse" if triaged else "robot"
    if isinstance(urgency, int) and not isinstance(urgency, bool) and urgency <= 2:
        return "robot"
    return "wait_nurse"  # 3-4, or anything unreadable: lean toward escalation


def urgency_rank(call: dict | None) -> int:
    """A call's urgency for keeping the most urgent triage answer; 0 when unknown."""
    urgency = (call or {}).get("urgency")
    return urgency if isinstance(urgency, int) and not isinstance(urgency, bool) else 0


def stt_fallback_due(pending: bool, flux_ok: bool, silence_s: float) -> bool:
    """Send the turn to Moonshine: Flux is down (end the turn like Flux's own EOT timeout would),
    or Flux is up but sent no EndOfTurn in time."""
    if not pending:
        return False
    limit = config.FLUX_TURN_LIMIT_S if flux_ok else config.EOT_TIMEOUT_MS / 1000
    return silence_s >= limit


def backfill(preroll: list[np.ndarray], closed_run: int) -> list[np.ndarray]:
    """Blocks to send when the gate opens: the zeroed blocks since it closed (at most the
    pre-roll) plus the current one, so the start of speech is never lost or sent twice."""
    if not preroll:
        return []
    return preroll[-(min(closed_run, len(preroll) - 1) + 1) :]


def pair_blocks(blocks: list[np.ndarray]) -> tuple[list[bytes], list[np.ndarray]]:
    """Flux gets two blocks per message; returns (messages, leftover block if odd)."""
    even = len(blocks) - len(blocks) % 2
    pairs = [np.concatenate(blocks[i : i + 2]).tobytes() for i in range(0, even, 2)]
    return pairs, blocks[even:]


def messages_with(history: VisitHistory, text: str) -> list[dict]:
    """History plus one resident line, without touching the real history (for drafts)."""
    draft = VisitHistory()
    for speaker, line in history.transcript():
        draft.add(speaker, line)
    draft.add("resident", text)
    return draft.messages()


def scene_note(message: dict | None) -> str:
    """One line for the prompt from a fresh vision message; "" when there is no vision."""
    if message is None:
        return ""
    face, person = message.get("face"), message.get("person")
    if isinstance(face, dict) and face.get("facing") is True:
        return "You see one person facing you."
    if face or person:
        return "You see one person, not facing you."
    return "No one is in view."


def _rounded(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds, 3)


class TurnLog:
    """runs/<date>/<n>.wav per accepted turn and runs/<date>/turns.jsonl with stage timings."""

    def __init__(self, runs_dir: Path = config.RUNS_DIR) -> None:
        self.runs_dir = runs_dir

    def write(
        self,
        call_id: str,
        text: str,
        source: str,
        audio: np.ndarray | None,
        stt_s: float | None,
        first_text_s: float | None,
        first_sound_s: float | None,
    ) -> None:
        day = self.runs_dir / date.today().isoformat()
        try:
            day.mkdir(parents=True, exist_ok=True)
            if audio is not None and len(audio):
                n = len(list(day.glob("*.wav"))) + 1
                with wave.open(str(day / f"{n}.wav"), "wb") as wav:
                    wav.setnchannels(1)
                    wav.setsampwidth(2)
                    wav.setframerate(config.SAMPLE_RATE)
                    wav.writeframes(audio.astype(np.int16).tobytes())
            line = {
                "t": time.time(),
                "call_id": call_id,
                "text": text,
                "source": source,
                "stt_s": _rounded(stt_s),
                "first_text_s": _rounded(first_text_s),
                "first_sound_s": _rounded(first_sound_s),
            }
            with (day / "turns.jsonl").open("a", encoding="utf-8") as log:
                log.write(json.dumps(line) + "\n")
        except OSError as exc:
            print(f"visit: could not write the debug log in {day}: {exc}")
