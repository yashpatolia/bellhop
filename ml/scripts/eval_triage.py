"""(Mac) Run triage on labelled cases and count under-escalations (the number that matters).

    uv run python scripts/eval_triage.py [cases.jsonl ...]

Default cases: the backend's labelled set plus data/hard_cases.jsonl. Nothing is posted to the
backend. Writes runs/predictions.json as {id: [urgency, confidence]} for the backend's
threshold_report. Success looks like "UNDER-ESCALATIONS: 0".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from rover import config
from rover.agent.brain import claude_client
from rover.triage.triage import triage

DEFAULT_CASES = [
    config.ML_DIR / "../../calhacks-13-backend/backend/data/labelled_cases.jsonl",
    config.ML_DIR / "data/hard_cases.jsonl",
]
LEVELS = (1, 2, 3, 4)


def load_cases(paths: list[Path]) -> list[dict]:
    cases = []
    for path in paths:
        with path.open(encoding="utf-8") as lines:
            cases += [json.loads(line) for line in lines if line.strip()]
    return cases


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[round(share * (len(ordered) - 1))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path, default=DEFAULT_CASES)
    paths = parser.parse_args().paths

    if claude_client() is None and not os.environ.get("TYPESAFE_API_KEY", "").strip():
        print("fallback: no ANTHROPIC_API_KEY and no TYPESAFE_API_KEY, nothing to evaluate")
        return 1

    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        print(f"no such case file: {', '.join(missing)}")
        return 1
    cases = load_cases(paths)
    if not cases:
        print("no cases in the given files")
        return 1
    rows = []
    for case in cases:
        transcript = [(speaker, text) for speaker, text in case["transcript"]]
        started = time.perf_counter()
        result = triage(transcript, case.get("risk_flags", []))
        rows.append((case, result, time.perf_counter() - started))

    under = [(c, r) for c, r, _ in rows if r is not None and r.urgency < c["expected_urgency"]]
    failed = [c for c, r, _ in rows if r is None]
    print(f"UNDER-ESCALATIONS: {len(under)}")
    for case, result in under:
        print(f"  {case['id']}: expected {case['expected_urgency']}, got {result.urgency} "
              f"({result.category}, {result.source}, confidence {result.confidence:.2f})")
        for speaker, text in case["transcript"]:
            print(f"      {speaker}: {text}")
    if failed:
        print(f"FAILED (backend would default to urgency 3): {', '.join(c['id'] for c in failed)}")

    scored = [(c, r) for c, r, _ in rows if r is not None]
    exact = sum(r.urgency == c["expected_urgency"] for c, r in scored)
    category = sum(r.category == c["expected_category"] for c, r in scored)
    print(f"\ncases {len(rows)}  scored {len(scored)}  exact urgency {exact}  "
          f"over {len(scored) - exact - len(under)}  under {len(under)}  "
          f"category match {category}")
    print("confusion (rows expected, columns predicted 1-4):")
    for expected in LEVELS:
        counts = [sum(c["expected_urgency"] == expected and r.urgency == got for c, r in scored)
                  for got in LEVELS]
        print(f"  {expected}: {counts}")
    latencies = [seconds for _, _, seconds in rows]
    print(f"latency p50 {percentile(latencies, 0.5):.2f}s  p95 {percentile(latencies, 0.95):.2f}s")

    config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    out = config.RUNS_DIR / "predictions.json"
    out.write_text(json.dumps({c["id"]: [r.urgency, r.confidence] for c, r in scored}, indent=1))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
