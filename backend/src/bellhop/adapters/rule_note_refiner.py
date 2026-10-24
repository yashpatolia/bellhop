"""Offline note tidy: simple rules, no network. The fallback when Claude is unavailable."""

from __future__ import annotations

import re

from bellhop.domain.care import NoteCategory, RefinedNote
from bellhop.ports import Clock

_SHORTHAND: list[tuple[re.Pattern[str], str]] = [
    (re.compile(p, re.IGNORECASE), full)
    for p, full in [
        (r"\bhtn\b", "high blood pressure"),
        (r"\b(?:dm2|t2dm)\b", "type 2 diabetes"),
        (r"\bdm\b", "diabetes"),
        (r"\bcopd\b", "COPD"),
        (r"\boa\b", "osteoarthritis"),
        (r"\bafib\b", "atrial fibrillation"),
        (r"\bnkda\b", "no known drug allergies"),
        (r"\bbp\b", "blood pressure"),
        (r"\bmeds\b", "medicines"),
        (r"\bc/o\b", "complains of"),
        (r"\bpt\b", "the resident"),
    ]
]
_PRONOUN_VERB = re.compile(
    r"^(?:she|he|they|the resident|resident)\s+(likes|loves|enjoys|prefers|dislikes|hates)\b\s*",
    re.IGNORECASE,
)
_DOSE = re.compile(r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|units?|iu)\b", re.IGNORECASE)
_TIMING = re.compile(
    r"\b(?:once a day|twice a day|twice daily|three times a day|daily|nightly|at night|"
    r"in the morning|bd|od|tds|qds|prn|as needed)\b",
    re.IGNORECASE,
)
_EMPTY_MESSAGE = "Nothing to add. Type a note first."


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


class RuleNoteRefiner:
    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def refine(self, category: NoteCategory, text: str) -> RefinedNote:
        notes: list[str] = []
        text = re.sub(r"\s+", " ", text).strip().strip("\"'")
        if not text:
            raise ValueError(_EMPTY_MESSAGE)

        letters = re.sub(r"[^A-Za-z]", "", text)
        upper = re.sub(r"[^A-Z]", "", letters)
        if len(letters) > 3 and len(upper) / len(letters) > 0.6:
            text = text.lower()
            notes.append("Rewrote the capital letters in normal case")

        for pattern, full in _SHORTHAND:

            def swap(m: re.Match[str], full: str = full) -> str:
                if m.group(0).lower() != full.lower():
                    notes.append(f'Wrote "{m.group(0)}" as "{full}"')
                return full

            text = pattern.sub(swap, text)

        since: str | None = None
        if category is NoteCategory.CONDITION:
            year = re.search(r"\b(?:since|from)\s+((?:19|20)\d{2})\b", text, re.IGNORECASE)
            years = re.search(r"\bfor\s+(\d{1,2})\s+years?\b", text, re.IGNORECASE)
            if year:
                since = year.group(1)
                text = text.replace(year.group(0), "")
            elif years:
                since = str(self._clock.now().year - int(years.group(1)))
                text = text.replace(years.group(0), "")
            if since:
                notes.append(f"Recorded the start as {since}")

        if category is NoteCategory.MEDICINE:
            stripped = _TIMING.sub("", _DOSE.sub("", text))
            if stripped != text:
                text = stripped
                notes.append("Dose and timing removed: only the medicine name is kept")

        if category.is_fact:
            lead = _PRONOUN_VERB.match(text)
            if lead:
                text = _sentence_case(lead.group(1).lower()) + " " + text[lead.end() :]
                notes.append("Wrote it as a short third-person note")

        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"[\s,;.]+$", "", text).strip()
        cased = _sentence_case(text)
        if cased != text:
            notes.append("Fixed capitalisation")
        if not cased:
            raise ValueError(_EMPTY_MESSAGE)
        return RefinedNote(category=category, text=cased, since=since, notes=notes)
