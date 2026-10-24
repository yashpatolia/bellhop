"""Records per-call outcomes (Visit) plus ratings and nurse corrections."""

from __future__ import annotations

from bellhop.domain import Urgency, Visit
from bellhop.domain.events import CallResolved
from bellhop.ports import CallRepository, EventBus, IdGenerator, VisitRepository


class FeedbackService:
    def __init__(
        self,
        visits: VisitRepository,
        calls: CallRepository,
        bus: EventBus,
        ids: IdGenerator,
    ) -> None:
        self._visits = visits
        self._calls = calls
        self._ids = ids
        bus.subscribe(CallResolved, self._on_resolved)

    def _on_resolved(self, event: CallResolved) -> None:
        call = self._calls.get(event.call_id)
        if call is None:
            return
        self.record_resolution(event.call_id, call.robot_id, resolved_by_robot=event.by_robot)

    def record_resolution(
        self, call_id: str, robot_id: str | None, *, resolved_by_robot: bool = True
    ) -> None:
        if self._visits.for_call(call_id) is not None:
            return
        call = self._calls.get(call_id)
        if call is None:
            return
        self._visits.save(
            Visit(
                id=self._ids.new_id("visit"),
                call_id=call_id,
                resident_id=call.resident_id,
                robot_id=robot_id,
                resolved_by_robot=resolved_by_robot,
            )
        )

    def rate(self, call_id: str, rating: int, mood: str | None = None) -> None:
        if not 1 <= rating <= 5:
            raise ValueError("rating must be between 1 and 5")
        visit = self._visit(call_id)
        visit.rating = rating
        visit.mood = mood
        self._visits.save(visit)

    def nurse_override(self, call_id: str, urgency: Urgency) -> None:
        visit = self._visit(call_id)
        visit.nurse_urgency_override = urgency
        self._visits.save(visit)

    def _visit(self, call_id: str) -> Visit:
        visit = self._visits.for_call(call_id)
        if visit is None:
            raise LookupError(f"no visit recorded for call {call_id}")
        return visit
