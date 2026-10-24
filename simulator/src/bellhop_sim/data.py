"""The fictional home: residents, conversations and call patterns, loaded from data/*.json."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"

# Dashboard-style flags to backend risk flags. Hearing is a preference, not a risk.
RISK_FLAGS = {
    "Fall risk": "falls",
    "Dementia": "dementia",
    "Oxygen": "oxygen",
    "Diabetic": "diabetic",
}


@dataclass(frozen=True)
class Scenario:
    category: str
    urgency: int
    summary: str
    turns: tuple[tuple[str, str], ...]  # (speaker, text), resident first


@cache
def _load(name: str) -> object:
    return json.loads((DATA_DIR / name).read_text())


def residents() -> list[dict]:
    return _load("residents.json")  # type: ignore[return-value]


def scenarios() -> list[Scenario]:
    return [
        Scenario(s["category"], s["urgency"], s["summary"], tuple(tuple(t) for t in s["turns"]))
        for s in _load("scenarios.json")  # type: ignore[union-attr]
    ]


def patterns() -> dict[str, list[list]]:
    """resident id -> [[category, count, hour_from, hour_to], ...]; hour_to above 24 wraps."""
    return _load("patterns.json")  # type: ignore[return-value]


def scenarios_for(category: str) -> list[Scenario]:
    return [s for s in scenarios() if s.category == category]


def risk_flags(resident: dict) -> list[str]:
    return [RISK_FLAGS[f] for f in resident["flags"] if f in RISK_FLAGS]


def hard_of_hearing(resident: dict) -> bool:
    return "Hard of hearing" in resident["flags"]
