"""Urgency labels: the definitions (shared with triage/prompt.md), parsing, manual import."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path

PROMPT_MD = Path(__file__).resolve().parents[2] / "pi" / "src" / "rover" / "triage" / "prompt.md"

LABEL_TASK = (
    "Label ONE utterance spoken by a care-home resident (or about one) to a call-bell robot. "
    "Use the urgency definitions and rules below. Answer with a single digit 1, 2, 3 or 4 and "
    "nothing else.\n\n"
)


def system_prompt() -> str:
    """The same urgency definitions and rules the production triage prompt uses."""
    text = PROMPT_MD.read_text(encoding="utf-8")
    start = text.index("## Urgency")
    end = text.index("## Category")
    return LABEL_TASK + text[start:end].strip()


def parse_label(raw: object) -> int | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if isinstance(data, dict):
        value = data.get("urgency")
        return value if value in (1, 2, 3, 4) else None
    if isinstance(data, int) and not isinstance(data, bool):
        return data if data in (1, 2, 3, 4) else None
    match = re.search(r"\b([1-4])\b", raw)
    return int(match.group(1)) if match else None


def read_manual_labels(path: Path) -> dict[str, int]:
    """Lines of `id label` (anything after # is a note)."""
    out: dict[str, int] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2 or parts[1] not in ("1", "2", "3", "4"):
            raise ValueError(f"{path}:{number}: expected 'id 1-4', got {line!r}")
        out[parts[0]] = int(parts[1])
    return out


def join_labels(rows: list[dict], labels: dict[str, int], source: str) -> list[dict]:
    return [
        {**row, "urgency": labels[row["id"]], "label_source": source}
        for row in rows
        if row["id"] in labels
    ]


def agreement(first: Sequence[int], second: Sequence[int]) -> dict:
    pairs = list(zip(first, second, strict=True))
    n = len(pairs)
    flips = sum((a >= 3) != (b >= 3) for a, b in pairs)
    return {
        "n": n,
        "exact": sum(a == b for a, b in pairs) / n if n else 0.0,
        "urgent_agree": (n - flips) / n if n else 0.0,
        "urgent_disagreements": flips,
    }


def label_with_claude(client, model: str, texts: Sequence[str]) -> list[int | None]:
    """One call per utterance. Needs ANTHROPIC_API_KEY; a failed call gives None."""
    out: list[int | None] = []
    for text in texts:
        try:
            response = client.messages.create(
                model=model,
                max_tokens=8,
                system=system_prompt(),
                messages=[{"role": "user", "content": text}],
            )
            out.append(parse_label(response.content[0].text))
        except Exception as exc:  # keep going; the caller reports how many failed
            print(f"label: call failed: {type(exc).__name__}")
            out.append(None)
    return out
