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


class NoteCategory(StrEnum):
    """What staff can add to a resident's profile. The first five become memory facts."""

    LIKE = "like"
    DISLIKE = "dislike"
    PERSON = "person"
    ROUTINE = "routine"
    STYLE = "style"  # how to talk with them
    CONDITION = "condition"
    ALLERGY = "allergy"
    MEDICINE = "medicine"
    MOBILITY = "mobility"
    DIET = "diet"

    @property
    def is_fact(self) -> bool:
        return self in FACT_NOTE_CATEGORIES


FACT_NOTE_CATEGORIES = frozenset(
    {
        NoteCategory.LIKE,
        NoteCategory.DISLIKE,
        NoteCategory.PERSON,
        NoteCategory.ROUTINE,
        NoteCategory.STYLE,
    }
)


class RefinedNote(BaseModel):
    """A staff note after the tidy step: cleaner wording plus what was changed."""

    category: NoteCategory
    text: str
    since: str | None = None  # conditions only
    notes: list[str] = Field(default_factory=list)


class Condition(BaseModel):
    name: str = Field(max_length=200)
    since: str = Field(default="recently", max_length=32)
    note: str | None = Field(default=None, max_length=500)


class MedicalRecord(BaseModel):
    """Medical history entered by staff. Bellhop never learns or changes it by itself."""

    resident_id: str
    conditions: list[Condition] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    medicines: list[str] = Field(default_factory=list)  # names only
    mobility: str = ""
    diet: str = ""
    last_review: datetime | None = None
    reviewed_by: str = ""
