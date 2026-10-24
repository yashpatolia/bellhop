"""Tidy a staff note with Claude, using structured output. Falls back to the rule refiner.

The model only rewrites wording. It must not add facts, doses or diagnoses; staff always
review the result before anything is saved.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import anthropic
from pydantic import BaseModel, Field

from bellhop.domain.care import NoteCategory, RefinedNote
from bellhop.ports.care import NoteRefiner

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5-5"
MODEL_ENV = "BELLHOP_REFINER_MODEL"

SYSTEM_PROMPT = """You tidy short notes that care-home staff type about a resident, so they are \
clear and consistent in the resident's profile. Staff review your wording before it is saved.

Rules:
1. Keep the meaning exactly. Never add a fact, a name, a number or a condition that is not in \
the note. If the note is unclear, keep it as written.
2. Fix spelling and capitalisation, expand common shorthand (htn is high blood pressure, \
c/o is complains of), and write likes, dislikes, routines and people as one short \
third-person sentence, for example "Likes his tea strong".
3. For a condition, write only the condition name and put a start year in `since` when the note \
gives one, or says "for N years" (use the current year to work out the start).
4. For a medicine, keep only the medicine name. Remove doses and timing and say so in `notes`.
5. For an allergy, mobility or diet note, keep it brief and plain.
6. `notes` lists, in plain words, each change you made. Use an empty list if you changed nothing.
7. Never diagnose, advise or interpret."""


class _Out(BaseModel):
    text: str = Field(min_length=1, max_length=280)
    since: str | None = None
    notes: list[str] = Field(default_factory=list)


class ClaudeNoteRefiner:
    def __init__(
        self, fallback: NoteRefiner, client: Any | None = None, model: str | None = None
    ) -> None:
        self._fallback = fallback
        self._client = client if client is not None else anthropic.Anthropic()
        self._model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL

    def refine(self, category: NoteCategory, text: str) -> RefinedNote:
        if not text.strip():
            raise ValueError("Nothing to add. Type a note first.")
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=512,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"Category: {category.value}\nNote: {text}"}],
                output_format=_Out,
            )
            out = response.parsed_output
        except Exception:
            log.exception("note refine failed, using the rule refiner")
            return self._fallback.refine(category, text)
        if out is None or not out.text.strip():
            return self._fallback.refine(category, text)
        since = out.since if category is NoteCategory.CONDITION else None
        return RefinedNote(category=category, text=out.text.strip(), since=since, notes=out.notes)
