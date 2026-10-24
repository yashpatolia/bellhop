"""Plain-English answers about calls, alerts and metrics. Pure: no I/O, no uagents."""

import re
from typing import Any

_LEVELS = {1: "a chat", 2: "a routine request", 3: "needs a nurse soon", 4: "an emergency"}
_ROOM = re.compile(r"\b(?:room|rm)\s*#?\s*(\w+)", re.I)

HELP = (
    "I can answer: what happened in a room (for example, 'what happened in room 12?'), "
    "any emergencies or who needs a nurse, how many calls the robot resolved, "
    "and how many minutes were saved."
)


def _level(value: Any) -> str:
    return _LEVELS.get(value, "urgency not yet assessed")


def _call_line(c: dict[str, Any]) -> str:
    when = str(c.get("created_at") or "")[:16].replace("T", " ")
    status = str(c.get("status") or "unknown").replace("_", " ")
    text = f"{when}: {_level(c.get('urgency'))}, {status}."
    return f"{text} {c['summary']}" if c.get("summary") else text


def _room_history(room: str, calls: list[dict[str, Any]]) -> str:
    mine = sorted(
        (c for c in calls if str(c.get("room")) == room),
        key=lambda c: str(c.get("created_at") or ""),
        reverse=True,
    )
    if not mine:
        return f"There are no calls recorded for room {room}."
    lines = "\n".join(f"- {_call_line(c)}" for c in mine[:5])
    return f"Room {room}, newest first:\n{lines}"


def _open_alerts(alerts: list[dict[str, Any]], calls: list[dict[str, Any]]) -> str:
    rooms = {c.get("id"): c.get("room") for c in calls}
    open_ = [a for a in alerts if not a.get("acked_at")]
    if not open_:
        return "There are no open alerts right now. Everyone has been acknowledged."
    open_.sort(key=lambda a: a.get("level") or 0, reverse=True)
    lines = []
    for a in open_[:5]:
        room = rooms.get(a.get("call_id"))
        where = f"Room {room}" if room else "A room"
        lines.append(f"- {where}: {_level(a.get('level'))}. {a.get('message') or ''}".rstrip())
    return "Open alerts, most urgent first:\n" + "\n".join(lines)


def _metrics(question: str, metrics: dict[str, Any]) -> str:
    if "minute" in question or "saved" in question:
        mins = metrics.get("minutes_saved")
        if mins is None:
            return "I do not have a minutes-saved figure yet."
        return f"The robot has saved about {mins:g} nurse minutes."
    n = metrics.get("resolved_without_nurse")
    if n is None:
        return "I do not have a resolved-calls figure yet."
    return f"The robot resolved {n} calls without needing a nurse."


def wants_alerts(q: str) -> bool:
    return any(k in q for k in ("emergenc", "alert", "nurse", "urgent"))


def wants_metrics(q: str) -> bool:
    return any(k in q for k in ("resolve", "minute", "saved", "how many"))


def answer_question(
    question: str,
    calls: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    metrics: dict[str, Any],
) -> str:
    q = (question or "").lower()
    if m := _ROOM.search(q):
        return _room_history(m.group(1), calls)
    if wants_metrics(q):
        return _metrics(q, metrics)
    if wants_alerts(q):
        return _open_alerts(alerts, calls)
    return HELP
