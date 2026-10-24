"""Care signals: per-visit mood/pain/drink entries, flags, preferences, family messages.

Kept apart from `models.py` (call lifecycle). Observations only: nothing here diagnoses.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class FlagType(StrEnum):
    """Only four flag types, each with a reason, so nurses keep trusting them."""

    PAIN = "pain"
    ASKS_FOR_NURSE = "asks_for_nurse"
    DISTRESS = "distress"
    NO_ANSWER = "no_answer"


class EntryKind(StrEnum):
    MOOD = "mood"  # 1 (low) .. 5 (good)
    PAIN = "pain"  # 1 (none) .. 5 (severe), from the tap-a-face scale or pain words
    DRINK = "drink"  # a drink was offered and taken
    REPEAT_QUESTION = "repeat_question"  # resident asked the same thing again


class CareEntry(BaseModel):
    id: str
    resident_id: str
    call_id: str | None = None
    kind: EntryKind
    value: float | None = Field(default=None, ge=1, le=5)
    note: str = ""
    at: datetime


class Flag(BaseModel):
    id: str
    resident_id: str
    call_id: str | None = None
    type: FlagType
    reason: str  # always say why
    created_at: datetime
    resolved_at: datetime | None = None


class Preferences(BaseModel):
    resident_id: str
    hard_of_hearing: bool = False  # slower, louder, captions
    quiet_mode: bool = False  # "not now" means leave
    night_mode: bool = False  # calm tone, dim screen
    favourite_drink: str | None = None


class MessageDirection(StrEnum):
    TO_RESIDENT = "to_resident"
    FROM_RESIDENT = "from_resident"


class FamilyMessage(BaseModel):
    id: str
    resident_id: str
    direction: MessageDirection
    text: str
    created_at: datetime
