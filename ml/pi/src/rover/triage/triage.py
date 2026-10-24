"""Triage a visit with Claude, then post the structured result to the backend.

The optional local scorer runs in parallel and can only raise urgency. A slow or failed
model never blocks the visit beyond the configured triage budget.
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

from rover import config
from rover.agent.brain import claude_client
from rover.agent.jev import decide as ask_jev_decision
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
URGENCY_LEVELS = [
    "Urgency 1: chat or company; no staff needed.",
    "Urgency 2: routine request such as water, a blanket, or an errand.",
    "Urgency 3: nurse soon for pain, dizziness, nausea, medication, distress, or a near fall.",
    "Urgency 4: emergency now for a fall, chest pain, breathing trouble, unresponsiveness, "
    "stroke signs, or severe bleeding.",
]


@dataclass
class TriageResult:
    urgency: int
    category: str
    summary: str
    confidence: float
    source: str


def format_visit(transcript: Transcript, risk_flags: list[str]) -> str:
    lines = [f"Risk flags: {', '.join(risk_flags) or 'none'}", "Transcript:"]
    lines += [f"{speaker}: {text}" for speaker, text in transcript]
    return "\n".join(lines)


def ask_claude(transcript: Transcript, risk_flags: list[str]) -> TriageResult | None:
    client = claude_client()
    if client is None:
        print("fallback: no ANTHROPIC_API_KEY, Claude triage skipped")
        return None
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


def _real_ask_local(transcript: Transcript) -> tuple[int, float] | None:
    if not config.LOCAL_TRIAGE:
        return None
    return local.score_transcript(local.get_scorer(), transcript)


def _float(value: object) -> float | None:
    """A malformed remote answer is simply unusable, never an exception in a care visit."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _jev_urgency(value: object) -> int | None:
    """Map Jev's zero-based expected urgency to the rover's one-based 1..4 scale."""
    score = _float(value)
    if score is None:
        return None
    return max(1, min(4, math.floor(score + 0.5) + 1))


def ask_jev(transcript: Transcript, risk_flags: list[str]) -> TriageResult | None:
    """Optional Jev assessment.  It is advisory and must never throw or block Claude.

    The transport returns ``None`` immediately with no ``TYPESAFE_API_KEY``.  Its own timeout is
    bounded; :func:`triage` also never waits for it before Claude or the local scorer proceed.
    """
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        return None
    answers = ask_jev_decision(
        format_visit(transcript, risk_flags),
        {
            "urgency": {
                "type": "score",
                "instructions": (
                    "How urgently does a nurse need to see this care-home resident? "
                    "Lean toward the higher level when unsure."
                ),
                "criteria": URGENCY_LEVELS,
            },
            "category": {
                "type": "choice",
                "instructions": "What is the most urgent thing in this visit about?",
                "criteria": CATEGORIES,
            },
        },
    )
    urgency_answer = answers.get("urgency") if answers else None
    category_answer = answers.get("category") if answers else None
    if not isinstance(urgency_answer, dict):
        return None
    urgency = _jev_urgency(urgency_answer.get("score", urgency_answer.get("value")))
    confidence = _float(urgency_answer.get("confidence"))
    if urgency is None or confidence is None:
        return None
    category = category_answer.get("choice") if isinstance(category_answer, dict) else None
    return TriageResult(
        urgency=urgency,
        category=category if category in CATEGORIES else "ambiguous",
        summary="",
        confidence=max(0.0, min(1.0, confidence)),
        source="jev",
    )


def _last_resident_line(transcript: Transcript) -> str:
    said = [text.strip() for speaker, text in transcript if speaker == "resident" and text.strip()]
    room = config.SUMMARY_MAX_CHARS - len(SUMMARY_QUOTE.format(""))
    return said[-1][:room] if said else ""


def raise_urgency(
    result: TriageResult | None, score: tuple[int, float] | None, summary: str = ""
) -> TriageResult | None:
    """The local scorer only raises urgency; with no model it may create a level-3/4 alert."""
    if score is None or score[1] < config.LOCAL_MIN_CONFIDENCE:
        return result
    urgency = score[0]
    if result is None:
        if urgency < 3:
            return None
        return TriageResult(urgency, "ambiguous", summary, config.LOCAL_ONLY_CONFIDENCE, "local")
    if urgency <= result.urgency:
        return result
    return replace(result, urgency=urgency, source=f"{result.source}+local")


AskFn = Callable[[Transcript, list[str]], TriageResult | None]


def _number_env(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value >= 0 else default


def merge_jev(
    jev: TriageResult | None, claude: TriageResult | None, transcript: Transcript
) -> TriageResult | None:
    """Jev can add an escalation, never replace Claude's narrative or lower its urgency."""
    if claude is not None:
        if jev is None or jev.urgency <= claude.urgency:
            return claude
        return replace(claude, urgency=jev.urgency, category=jev.category, source="claude+jev")
    if jev is None:
        return None
    return replace(
        jev,
        summary=SUMMARY_QUOTE.format(_last_resident_line(transcript)),
        # A Jev-only score is intentionally conservative so the backend's normal safeguards
        # retain their authority.  It still provides a nurse-visible assessment if Claude is down.
        confidence=min(jev.confidence, _number_env("JEV_ONLY_CONFIDENCE", 0.5)),
    )


def with_retry(ask: AskFn, deadline: float, clock: Callable[[], float], retries: int = 1) -> AskFn:
    """Retry Claude once only when the overall budget leaves room for another attempt."""

    def run(transcript: Transcript, risk_flags: list[str]) -> TriageResult | None:
        result = None
        for attempt in range(retries + 1):
            try:
                result = ask(transcript, risk_flags)
            except Exception as exc:
                print(f"triage: Claude attempt {attempt + 1} crashed: {exc!r}")
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


def _answer_in_time(future, name: str):
    if not future.done():
        print(f"triage: {name} did not answer in time, ignored")
        return None
    try:
        return future.result()
    except Exception as exc:
        print(f"triage: {name} crashed: {exc!r}")
        return None


def triage(
    transcript: Transcript,
    risk_flags: list[str],
    ask_claude: AskFn | None = None,
    clock: Callable[[], float] = time.monotonic,
    claude_retries: int = 1,
    ask_local: Callable[[Transcript], tuple[int, float] | None] | None = None,
    ask_jev: AskFn | None = None,
) -> TriageResult | None:
    """Claude remains primary; optional Jev and local scoring can only raise urgency."""
    started = clock()
    budget_end = time.monotonic() + config.TRIAGE_TIMEOUT_S
    pool = ThreadPoolExecutor(max_workers=3)
    claude_ask = with_retry(
        ask_claude or ask_claude_real, started + config.TRIAGE_TIMEOUT_S, clock, claude_retries
    )
    claude_future = pool.submit(claude_ask, transcript, risk_flags)
    local_future = pool.submit(ask_local or _real_ask_local, transcript)
    # Jev starts alongside, rather than ahead of, Claude. A slow paid provider can never consume
    # the reply/triage budget or delay the offline scorer.
    jev_future = pool.submit(ask_jev or _real_ask_jev, transcript, risk_flags)
    wait([claude_future], timeout=config.TRIAGE_TIMEOUT_S)
    result = _answer_in_time(claude_future, "claude")
    jev = _answer_in_time(jev_future, "jev")
    wait([local_future], timeout=max(0.0, budget_end - time.monotonic()))
    local_score = _answer_in_time(local_future, "local")
    pool.shutdown(wait=False, cancel_futures=True)
    merged = merge_jev(jev, result, transcript)
    return raise_urgency(merged, local_score, SUMMARY_QUOTE.format(_last_resident_line(transcript)))


ask_claude_real = ask_claude
_real_ask_jev = ask_jev


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
