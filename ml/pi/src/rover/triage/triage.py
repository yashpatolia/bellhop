"""Triage a visit with Jev (TypeSafe) first and Claude as the backup, then post the result.

A confident Jev (JEV_MIN_CONFIDENCE or more) is posted as is, with the resident's last words as the
summary (Jev gives no reasons). An unsure, slow or failed Jev hands over to Claude, then:
both answer -> higher urgency (and its category) with Claude's summary and confidence.
Only Claude -> as is. Only an unsure Jev -> confidence JEV_ONLY_CONFIDENCE so the backend bumps
urgency one level. Neither -> None, posted as triage-failed.
"""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path

import anthropic
from typesafe_sdk import Choice, RetryPolicy, Score, TypeSafeClient, TypeSafeError

from rover import config
from rover.agent.brain import claude_client
from rover.backend import Backend
from rover.triage import local

Transcript = list[tuple[str, str]]

PROMPT = (Path(__file__).parent / "prompt.md").read_text(encoding="utf-8")

CATEGORIES = {
    "social": "chat, company, memories, entertainment",
    "request": "a routine item or errand: water, blanket, glasses",
    "pain": "pain anywhere",
    "fall": "someone fell, is on the floor or cannot get up",
    "confusion": "confused or disoriented",
    "mobility": "help moving, standing, walking or to the toilet; a near fall",
    "ambiguous": "vague complaint, or an emergency with no category of its own",
    "medication": "a question or mix-up about medicines",
    "cardiac": "chest pain or pressure, racing or pounding heart",
    "dizziness": "dizzy, lightheaded, wobbly",
    "nausea": "feeling sick, vomiting, off food",
    "respiratory": "trouble breathing, blue lips, choking",
    "unresponsive": "someone not waking up or not answering",
    "asks_for_nurse": "asks for a nurse or a real person",
}

URGENCY_LEVELS = [  # Jev scores from zero, so index 0 is urgency 1
    "Urgency 1, chat: company or small talk, no need for staff.",
    "Urgency 2, routine: a simple request such as water, a blanket or help to the toilet.",
    "Urgency 3, nurse soon: pain, dizziness, nausea, a medication question, distress, a near "
    "fall, or asking for a nurse.",
    "Urgency 4, emergency now: a fall, chest pain or pressure, breathing trouble, someone "
    "unresponsive, stroke signs, or severe bleeding. Includes idioms, third-person reports, "
    "hedged and past-tense reports of these.",
]

CLAUDE_SCHEMA = {
    "type": "object",
    "properties": {
        "urgency": {"type": "integer", "enum": [1, 2, 3, 4]},
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "summary": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["urgency", "category", "summary", "confidence"],
    "additionalProperties": False,
}

SUMMARY_QUOTE = 'Resident said: "{}"'


@dataclass
class TriageResult:
    urgency: int
    category: str
    summary: str
    confidence: float
    source: str  # "jev", "claude" or "jev+claude"


def format_visit(transcript: Transcript, risk_flags: list[str]) -> str:
    lines = [f"Risk flags: {', '.join(risk_flags) or 'none'}", "Transcript:"]
    lines += [f"{speaker}: {text}" for speaker, text in transcript]
    return "\n".join(lines)


def ask_claude(transcript: Transcript, risk_flags: list[str]) -> TriageResult | None:
    client = claude_client()
    if client is None:
        print("fallback: no ANTHROPIC_API_KEY, Claude triage skipped")
        return None
    # No SDK retries: triage() owns the single retry so it can respect the overall budget.
    client = client.with_options(timeout=config.TRIAGE_ATTEMPT_S, max_retries=0)
    try:
        response = client.messages.create(
            model=config.TRIAGE_MODEL,
            max_tokens=config.TRIAGE_MAX_TOKENS,
            system=PROMPT,
            messages=[{"role": "user", "content": format_visit(transcript, risk_flags)}],
            output_config={
                "effort": config.TRIAGE_EFFORT,
                "format": {"type": "json_schema", "schema": CLAUDE_SCHEMA},
            },
        )
    except anthropic.APIStatusError as exc:
        print(f"triage: Claude API error {exc.status_code}: {exc.message}")
        return None
    except anthropic.APIConnectionError as exc:
        print(f"triage: no connection to Claude ({type(exc).__name__})")
        return None
    if response.stop_reason != "end_turn":
        print(f"triage: Claude stopped with {response.stop_reason}")
        return None
    text = next((block.text for block in response.content if block.type == "text"), "")
    try:
        data = json.loads(text)
        return TriageResult(
            urgency=int(data["urgency"]),
            category=str(data["category"]),
            summary=str(data["summary"]).strip(),
            confidence=float(data["confidence"]),
            source="claude",
        )
    except (ValueError, KeyError, TypeError) as exc:
        print(f"triage: Claude answer unreadable: {exc!r}: {text[:200]}")
        return None


def jev_urgency(expected_level: float) -> int:
    """Jev's score is a probability-weighted level counted from 0, so it can fall between levels.
    Round half up (toward escalation) and shift to urgency 1..4."""
    return max(1, min(len(URGENCY_LEVELS), math.floor(expected_level + 0.5) + 1))


def ask_jev(transcript: Transcript, risk_flags: list[str]) -> TriageResult | None:
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        print("fallback: no TYPESAFE_API_KEY, Jev triage skipped")
        return None
    try:
        with TypeSafeClient(
            model=config.JEV_MODEL,
            timeout=config.JEV_TIMEOUT_S,
            retry=RetryPolicy(max_retries=0),
        ) as client:
            result = client.system_one(
                state=format_visit(transcript, risk_flags),
                questions={
                    "urgency": Score(
                        instructions=(
                            "How urgently does a nurse need to see this care-home resident? "
                            "Lean toward the higher level when unsure."
                        ),
                        criteria=URGENCY_LEVELS,
                    ),
                    "category": Choice(
                        instructions="What is the most urgent thing in this visit about?",
                        criteria=CATEGORIES,
                    ),
                },
            )
    except TypeSafeError as exc:
        print(f"triage: Jev failed: {type(exc).__name__}: {exc}")
        return None
    score = result.scores.get("urgency")
    choice = result.choices.get("category")
    if score is None or not math.isfinite(score.score):
        print(f"triage: Jev gave no usable urgency: {score}")
        return None
    return TriageResult(
        urgency=jev_urgency(score.score),
        category=choice.choice if choice else "ambiguous",
        summary="",
        confidence=score.confidence,
        source="jev",
    )


def _real_ask_local(transcript: Transcript) -> tuple[int, float] | None:
    if not config.LOCAL_TRIAGE:
        return None
    return local.score_transcript(local.get_scorer(), transcript)


# triage() takes parameters with these same names, so it reaches the real ones through aliases.
_real_ask_jev, _real_ask_claude = ask_jev, ask_claude


def _last_resident_line(transcript: Transcript) -> str:
    said = [text.strip() for speaker, text in transcript if speaker == "resident" and text.strip()]
    room = config.SUMMARY_MAX_CHARS - len(SUMMARY_QUOTE.format(""))
    return said[-1][:room] if said else ""


def merge(
    jev: TriageResult | None, claude: TriageResult | None, transcript: Transcript
) -> TriageResult | None:
    if jev and claude:
        top = jev if jev.urgency > claude.urgency else claude
        return TriageResult(
            top.urgency, top.category, claude.summary, claude.confidence, "jev+claude"
        )
    if claude:
        return claude
    if jev:
        summary = SUMMARY_QUOTE.format(_last_resident_line(transcript))
        return TriageResult(jev.urgency, jev.category, summary, config.JEV_ONLY_CONFIDENCE, "jev")
    return None


def raise_urgency(
    result: TriageResult | None, score: tuple[int, float] | None, summary: str = ""
) -> TriageResult | None:
    """The local scorer can only raise the urgency, and only when it is sure enough. With no model
    answer at all it is used only for a nurse-soon or emergency score (urgency 3 or 4)."""
    if score is None or score[1] < config.LOCAL_MIN_CONFIDENCE:
        return result
    urgency = score[0]
    if result is None:
        if urgency < 3:
            return None
        return TriageResult(urgency, "ambiguous", summary, config.JEV_ONLY_CONFIDENCE, "local")
    if urgency <= result.urgency:
        return result
    return replace(result, urgency=urgency, source=f"{result.source}+local")


AskFn = Callable[[Transcript, list[str]], TriageResult | None]


def with_retry(ask: AskFn, deadline: float, clock: Callable[[], float], retries: int = 1) -> AskFn:
    """Call `ask` again after a failure (None or a crash) while the budget has room for it."""

    def run(transcript: Transcript, risk_flags: list[str]) -> TriageResult | None:
        result = None
        for attempt in range(retries + 1):
            try:
                result = ask(transcript, risk_flags)
            except Exception as exc:
                print(f"triage: claude attempt {attempt + 1} crashed: {exc!r}")
                result = None
            if result is not None:
                return result
            if attempt < retries and deadline - clock() < config.TRIAGE_RETRY_MIN_S:
                print("triage: no budget left to retry Claude")
                return None
            if attempt < retries:
                print("triage: retrying Claude once")
        return None

    return run


def triage(
    transcript: Transcript,
    risk_flags: list[str],
    ask_jev: AskFn | None = None,
    ask_claude: AskFn | None = None,
    clock: Callable[[], float] = time.monotonic,
    claude_retries: int = 1,
    ask_local: Callable[[Transcript], tuple[int, float] | None] | None = None,
) -> TriageResult | None:
    """Jev first, waited for up to JEV_TIMEOUT_S. A confident Jev is the answer; otherwise Claude
    gets the rest of the budget with one retry, and an unsure Jev can only raise its urgency.
    The local scorer (offline, milliseconds) is applied last and can only raise it too."""
    started = clock()
    budget_end = time.monotonic() + config.TRIAGE_TIMEOUT_S
    pool = ThreadPoolExecutor(max_workers=3)
    jev_future = pool.submit(ask_jev or _real_ask_jev, transcript, risk_flags)
    local_future = pool.submit(ask_local or _real_ask_local, transcript)
    wait([jev_future], timeout=config.JEV_TIMEOUT_S)
    jev = _answer_in_time(jev_future, "jev")
    quote = SUMMARY_QUOTE.format(_last_resident_line(transcript))
    if jev is not None and jev.confidence >= config.JEV_MIN_CONFIDENCE:
        merged = replace(jev, summary=quote)
    else:
        if jev is not None:
            print(f"triage: Jev unsure (confidence {jev.confidence:.2f}), asking Claude")
        claude_ask = with_retry(
            ask_claude or _real_ask_claude, started + config.TRIAGE_TIMEOUT_S, clock, claude_retries
        )
        claude_future = pool.submit(claude_ask, transcript, risk_flags)
        wait([claude_future], timeout=max(0.0, budget_end - time.monotonic()))
        merged = merge(jev, _answer_in_time(claude_future, "claude"), transcript)
    wait([local_future], timeout=max(0.0, budget_end - time.monotonic()))
    pool.shutdown(wait=False, cancel_futures=True)  # never wait on a hung model
    return raise_urgency(merged, _answer_in_time(local_future, "local"), quote)


def _answer_in_time(future, name: str):
    if not future.done():
        print(f"triage: {name} did not answer in time, ignored")
        return None
    return _answer(future, name)


def _answer(future, name: str = "model") -> TriageResult | None:
    try:
        return future.result()
    except Exception as exc:  # a bug in one model's path must not stop the visit
        print(f"triage: {name} crashed: {exc!r}")
        return None


def triage_and_post(
    backend: Backend, call_id: str, transcript: Transcript, risk_flags: list[str]
) -> dict | None:
    result = triage(transcript, risk_flags)
    if result is None:
        print("fallback: triage failed (no model answered), posting triage-failed")
        return backend.triage_failed(call_id)
    print(
        f"triage: urgency {result.urgency} {result.category} "
        f"(confidence {result.confidence:.2f}, {result.source})"
    )
    return backend.score(
        call_id, result.urgency, result.category, result.summary, result.confidence
    )
