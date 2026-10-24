"""Read-only dashboard counters over calls and visits."""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable
from typing import Any

from bellhop.domain import Call
from bellhop.ports import CallRepository, VisitRepository

_KEYS = {
    "hour": lambda c: c.created_at.hour,
    "room": lambda c: c.room,
    "category": lambda c: c.category,
}


class Analytics:
    def __init__(self, calls: CallRepository, visits: VisitRepository) -> None:
        self._calls = calls
        self._visits = visits

    def resolved_without_nurse(self) -> int:
        return sum(1 for v in self._visits.list_all() if v.resolved_by_robot)

    def minutes_saved(self, minutes_per_call: float = 4.0) -> float:
        return self.resolved_without_nurse() * minutes_per_call

    def share_answered_within(self, seconds: float = 600) -> float:
        times = [s for c in self._calls.list_all() if (s := c.response_seconds) is not None]
        if not times:
            return 0.0
        return sum(1 for s in times if s <= seconds) / len(times)

    def calls_by(self, key: str) -> dict[Hashable, int]:
        if key not in _KEYS:
            raise ValueError(f"key must be one of {sorted(_KEYS)}")
        return dict(Counter(_KEYS[key](c) for c in self._calls.list_all()))

    def labelled_examples(self) -> list[dict[str, Any]]:
        examples = []
        for visit in self._visits.list_all():
            if visit.nurse_urgency_override is None:
                continue
            call: Call | None = self._calls.get(visit.call_id)
            if call is None:
                continue
            examples.append(
                {
                    "call_id": call.id,
                    "transcript": [{"speaker": t.speaker, "text": t.text} for t in call.transcript],
                    "robot_urgency": int(call.urgency) if call.urgency is not None else None,
                    "nurse_urgency": int(visit.nurse_urgency_override),
                }
            )
        return examples
