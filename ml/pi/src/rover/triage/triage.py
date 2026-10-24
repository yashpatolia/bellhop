"""Triage a visit with Claude, then post the structured result to the backend.

The optional local scorer runs in parallel and can only raise urgency. A slow or failed
model never blocks the visit beyond the configured triage budget.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path

import anthropic

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
) -> TriageResult | None:
    """Use Claude for triage within the fixed budget; optional offline scoring can only escalate."""
    started = clock()
    budget_end = time.monotonic() + config.TRIAGE_TIMEOUT_S
    pool = ThreadPoolExecutor(max_workers=2)
    claude_ask = with_retry(
        ask_claude or ask_claude_real, started + config.TRIAGE_TIMEOUT_S, clock, claude_retries
    )
    claude_future = pool.submit(claude_ask, transcript, risk_flags)
    local_future = pool.submit(ask_local or _real_ask_local, transcript)
    wait([claude_future], timeout=config.TRIAGE_TIMEOUT_S)
    result = _answer_in_time(claude_future, "claude")
    wait([local_future], timeout=max(0.0, budget_end - time.monotonic()))
    local_score = _answer_in_time(local_future, "local")
    pool.shutdown(wait=False, cancel_futures=True)
    return raise_urgency(result, local_score, SUMMARY_QUOTE.format(_last_resident_line(transcript)))


ask_claude_real = ask_claude


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
