"""Domain events published on the EventBus. Immutable facts; handlers must be idempotent."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Urgency


@dataclass(frozen=True)
class CallRaised:
    call_id: str
    room: str


@dataclass(frozen=True)
class CallAssigned:
    call_id: str
    robot_id: str | None
    nurse_id: str | None


@dataclass(frozen=True)
class CallScored:
    call_id: str
    urgency: Urgency
    category: str


@dataclass(frozen=True)
class CallResolved:
    call_id: str
    by_robot: bool


@dataclass(frozen=True)
class AlertRaised:
    alert_id: str
    call_id: str
    level: Urgency
