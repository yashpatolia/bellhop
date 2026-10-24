"""`python -m bellhop.labelled [output.jsonl]` writes the demo cases and prints a summary."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from bellhop.labelled.cases import CASES
from bellhop.labelled.io import save_jsonl

DEFAULT_PATH = Path("data/labelled_cases.jsonl")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    path = Path(args[0]) if args else DEFAULT_PATH
    save_jsonl(CASES, path)
    by_urgency = Counter(c.expected_urgency for c in CASES)
    print(f"Wrote {len(CASES)} cases to {path}")
    for u in sorted(by_urgency):
        print(f"  urgency {u}: {by_urgency[u]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
