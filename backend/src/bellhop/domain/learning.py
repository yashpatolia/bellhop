"""What a conversation can teach Bellhop about a resident, before it is trusted."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class FactKind(StrEnum):
    LIKE = "like"
    DISLIKE = "dislike"
    PERSON = "person"
    ROUTINE = "routine"
    HEALTH = "health"
    STYLE = "style"
    EVENT = "event"


class Subject(StrEnum):
    RESIDENT = "resident"
    OTHER = "other"


class CandidateFact(BaseModel):
    """A fact proposed by an extractor. It is a claim to check, not yet a memory."""

    kind: FactKind
    text: str = Field(
        description="One short sentence in third person, e.g. 'Likes tea with two sugars'"
    )
    quote: str = Field(description="The exact words from the transcript that support the fact")
    speaker: Literal["resident", "staff"] = Field(description="Who said the quote")
    subject: Subject = Field(description="Who the fact is about: the resident, or someone else")
    confidence: float = Field(description="0 to 1: how sure the extractor is that the fact is true")


class ExtractedFacts(BaseModel):
    facts: list[CandidateFact]
