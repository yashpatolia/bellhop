"""Pure domain models. No I/O, no framework imports beyond pydantic."""

from __future__ import annotations

from datetime import datetime
from enum import IntEnum, StrEnum

from pydantic import BaseModel, Field


class Urgency(IntEnum):
    CHAT = 1  # lonely, wants tea: robot handles alone
    ROUTINE = 2  # simple request: robot handles alone
    NURSE_SOON = 3  # nurse gets a written summary
    EMERGENCY = 4  # alert immediately, robot stays


class CallStatus(StrEnum):
    RINGING = "ringing"
    ASSIGNED = "assigned"
    ROBOT_EN_ROUTE = "robot_en_route"
    IN_VISIT = "in_visit"
    RESOLVED = "resolved"
    ESCALATED = "escalated"
    NURSE_ACKED = "nurse_acked"
    CLOSED = "closed"


class InvalidTransition(ValueError):
    pass


_TRANSITIONS: dict[CallStatus, set[CallStatus]] = {
    CallStatus.RINGING: {CallStatus.ASSIGNED, CallStatus.ESCALATED},
    CallStatus.ASSIGNED: {
        CallStatus.ROBOT_EN_ROUTE,
        CallStatus.IN_VISIT,
        CallStatus.RESOLVED,
        CallStatus.ESCALATED,
    },
    CallStatus.ROBOT_EN_ROUTE: {CallStatus.IN_VISIT, CallStatus.RESOLVED, CallStatus.ESCALATED},
    CallStatus.IN_VISIT: {CallStatus.RESOLVED, CallStatus.ESCALATED},
    CallStatus.ESCALATED: {CallStatus.NURSE_ACKED, CallStatus.RESOLVED},
    CallStatus.NURSE_ACKED: {CallStatus.RESOLVED},
    CallStatus.RESOLVED: {CallStatus.CLOSED},
    CallStatus.CLOSED: set(),
}


class Turn(BaseModel):
    speaker: str  # "resident" | "robot" | "nurse"
    text: str
    at: datetime


class Call(BaseModel):
    id: str
    room: str
    resident_id: str | None = None
    urgency: Urgency | None = None
    category: str | None = None
    status: CallStatus = CallStatus.RINGING
    transcript: list[Turn] = Field(default_factory=list)
    summary: str | None = None
    assigned_to: list[str] = Field(default_factory=list)  # robot and/or nurse ids
    robot_id: str | None = None
    nurse_tasks: set[str] = Field(default_factory=set)  # nurses charged for this call
    created_at: datetime
    assigned_at: datetime | None = None
    first_response_at: datetime | None = None
    resolved_at: datetime | None = None
    resolved_by_robot: bool | None = None  # set when the call is resolved

    @property
    def needs_nurse(self) -> bool:
        return self.urgency is not None and self.urgency >= Urgency.NURSE_SOON

    @property
    def response_seconds(self) -> float | None:
        if self.first_response_at is None:
            return None
        return (self.first_response_at - self.created_at).total_seconds()

    def transition(self, to: CallStatus, at: datetime) -> None:
        if to not in _TRANSITIONS[self.status]:
            raise InvalidTransition(f"{self.status} -> {to}")
        self.status = to
        if to is CallStatus.ASSIGNED:
            self.assigned_at = at
        elif to is CallStatus.IN_VISIT and self.first_response_at is None:
            self.first_response_at = at
        elif to is CallStatus.RESOLVED:
            self.resolved_at = at

    def start_visit(self, at: datetime) -> None:
        """The robot reached the resident (in-visit report).

        After escalation the robot may still arrive; that is accepted as a first response but
        the status stays ESCALATED or NURSE_ACKED so the escalation never disappears.
        """
        if self.status in (CallStatus.ESCALATED, CallStatus.NURSE_ACKED):
            if self.first_response_at is None:
                self.first_response_at = at
            return
        self.transition(CallStatus.IN_VISIT, at)

    def score(self, urgency: Urgency, category: str) -> None:
        """Record a triage result. Urgency only ever ratchets up (lean toward escalation)."""
        if self.urgency is None or urgency > self.urgency:
            self.urgency = urgency
            self.category = category

    def charge(self, nurse: Nurse) -> None:
        """Count this call against a nurse's load, at most once per nurse."""
        if nurse.id not in self.nurse_tasks:
            self.nurse_tasks.add(nurse.id)
            nurse.open_tasks += 1

    def add_turn(self, speaker: str, text: str, at: datetime) -> None:
        self.transcript.append(Turn(speaker=speaker, text=text, at=at))


class Resident(BaseModel):
    id: str
    name: str
    room: str
    risk_flags: set[str] = Field(default_factory=set)  # e.g. {"falls", "dementia"}
    birth_year: int | None = None


class MemoryFact(BaseModel):
    id: str
    resident_id: str
    text: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    # Provenance: where the fact came from and how sure we are. Defaults suit hand-entered facts.
    source: str = "staff"  # staff | conversation | family | inferred
    confidence: float = 1.0
    quote: str | None = None  # the resident's own words, when heard from them
    call_id: str | None = None
    last_confirmed: datetime | None = None
    times_seen: int = 1


class Nurse(BaseModel):
    id: str
    name: str
    on_shift: bool = True
    open_tasks: int = 0


class RobotStatus(StrEnum):
    IDLE = "idle"
    BUSY = "busy"
    CHARGING = "charging"
    FAULT = "fault"
    OFFLINE = "offline"  # added by staff, has not reported in yet: never given a call


class LedState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    NURSE_ON_WAY = "nurse_on_way"
    EMERGENCY = "emergency"


class Robot(BaseModel):
    id: str
    status: RobotStatus = RobotStatus.IDLE
    battery: float = 1.0  # 0..1
    room: str | None = None


class Alert(BaseModel):
    id: str
    call_id: str
    nurse_id: str | None  # None = broadcast
    level: Urgency
    message: str
    created_at: datetime
    acked_at: datetime | None = None


class Visit(BaseModel):
    """Per-call outcome record; the 'learning from every call' data model."""

    id: str
    call_id: str
    resident_id: str | None
    robot_id: str | None
    resolved_by_robot: bool = False
    rating: int | None = None  # 1..5 spoken rating
    mood: str | None = None
    nurse_urgency_override: Urgency | None = None  # labelled example for triage tuning
