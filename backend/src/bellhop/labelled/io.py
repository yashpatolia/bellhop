"""JSONL persistence and conversion from nurse overrides."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from bellhop.labelled.cases import LabelledCase


def save_jsonl(cases: Iterable[LabelledCase], path: str | Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = (json.dumps(asdict(c), ensure_ascii=False) for c in cases)
    path.write_text("".join(f"{line}\n" for line in lines), encoding="utf-8")


def load_jsonl(path: str | Path) -> list[LabelledCase]:
    cases = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        d["transcript"] = [(speaker, text) for speaker, text in d["transcript"]]
        cases.append(LabelledCase(**d))
    return cases


def from_overrides(analytics_examples: Iterable[dict[str, Any]]) -> list[LabelledCase]:
    """Nurse overrides become labels; the robot's own score goes in the note."""
    return [
        LabelledCase(
            id=f"override-{ex['call_id']}",
            transcript=[(t["speaker"], t["text"]) for t in ex["transcript"]],
            risk_flags=[],
            expected_urgency=int(ex["nurse_urgency"]),
            expected_category="nurse-override",
            note=f"nurse override; robot scored {ex['robot_urgency']}",
        )
        for ex in analytics_examples
    ]
