"""Remove identifiers from text before it leaves the building.

Family first names stay: they are the memory. The resident's own name, phone numbers,
emails and long digit runs (ids, account numbers) go.
"""

from __future__ import annotations

import re

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"\+?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b")
_LONG_DIGITS = re.compile(r"\b\d{6,}\b")
_LABEL = "the resident"


def _name_pattern(resident_name: str | None) -> re.Pattern[str] | None:
    if not resident_name or not resident_name.strip():
        return None
    parts = [p for p in resident_name.split() if len(p) >= 3]
    names = sorted({resident_name.strip(), *parts}, key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)


def scrub(text: str, resident_name: str | None = None) -> str:
    out = _EMAIL.sub("[email]", text)
    out = _PHONE.sub("[phone]", out)
    out = _LONG_DIGITS.sub("[number]", out)
    name = _name_pattern(resident_name)
    if name is not None:
        out = name.sub(_LABEL, out)
    return out
