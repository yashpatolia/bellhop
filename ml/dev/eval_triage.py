"""(Mac) Run triage on labelled cases and count under-escalations (the number that matters).

    cd ml/pi && uv run python ../dev/eval_triage.py [cases.jsonl ...] [--mock]

Cases come from, in order of preference:
  * the JSONL files given as arguments (dev/hard_cases.jsonl has 26 hard ones), or
  * with no files, GET /labelled-examples from the Bellhop API (BELLHOP_API, BELLHOP_API_KEY)
    plus dev/hard_cases.jsonl, or
  * --mock: only dev/hard_cases.jsonl and a deterministic fake triager. No network and no API
    keys, so it runs in CI; it checks the plumbing, not the models.

Nothing is posted to the backend. Writes runs/predictions.json as {id: [urgency, confidence]}
for the backend's threshold_report. Success looks like "UNDER-ESCALATIONS: 0".
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from rover import config
from rover.agent.brain import claude_client
from rover.triage.triage import TriageResult, triage

HERE = Path(__file__).resolve().parent
HARD_CASES = HERE / "hard_cases.jsonl"
DEFAULT_FILES = [HARD_CASES]
LEVELS = (1, 2, 3, 4)

# Mock triager: any of these phrases means an emergency; everything else is nurse soon (3),
# the same default the backend uses when triage fails.
MOCK_EMERGENCY_PHRASES = (
    "floor", "hit the deck", "fell", "went down", "slipped", "tumble", "can't get up",
    "not getting up", "legs no go", "chest", "ticker", "blue", "enough air", "breath",
    "not answering", "won't wake", "floppy", "one side", "blood",
)  # fmt: skip


class CaseError(Exception):
    """The cases could not be loaded; the message is for the person running the script."""


def load_cases(paths: list[Path]) -> list[dict]:
    cases = []
    for path in paths:
        if not path.is_file():
            raise CaseError(f"no such case file: {path}")
        with path.open(encoding="utf-8") as lines:
            cases += [json.loads(line) for line in lines if line.strip()]
    return cases


def fetch_labelled(
    base_url: str, api_key: str, transport: httpx.BaseTransport | None = None
) -> list[dict]:
    """GET /labelled-examples: calls where a nurse corrected the robot's urgency."""
    headers = {"X-API-Key": api_key} if api_key else {}
    try:
        with httpx.Client(
            base_url=base_url, headers=headers, timeout=10.0, transport=transport
        ) as client:
            response = client.get("/labelled-examples")
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise CaseError(f"GET {base_url}/labelled-examples failed: {exc}") from exc
    if not isinstance(data, list):
        raise CaseError("GET /labelled-examples did not return a list")
    return data


def cases_from_examples(examples: list[dict]) -> list[dict]:
    """Backend examples {call_id, transcript [{speaker, text}], robot_urgency, nurse_urgency}
    become cases labelled with the nurse's urgency."""
    cases = []
    for example in examples:
        transcript = [
            [turn["speaker"], turn["text"]] if isinstance(turn, dict) else list(turn)
            for turn in example.get("transcript", [])
        ]
        cases.append(
            {
                "id": f"override-{example['call_id']}",
                "transcript": transcript,
                "risk_flags": example.get("risk_flags", []),
                "expected_urgency": example["nurse_urgency"],
                "expected_category": example.get("category") or "ambiguous",
            }
        )
    return cases


def resolve_cases(paths: list[Path], mock: bool) -> list[dict]:
    if paths:
        return load_cases(paths)
    if mock:
        return load_cases(DEFAULT_FILES)
    examples = fetch_labelled(config.BELLHOP_API, config.BELLHOP_API_KEY)
    return cases_from_examples(examples) + load_cases(DEFAULT_FILES)


def mock_triage(transcript: list[tuple[str, str]], risk_flags: list[str]) -> TriageResult:
    said = " ".join(text.lower() for speaker, text in transcript if speaker == "resident")
    urgent = any(phrase in said for phrase in MOCK_EMERGENCY_PHRASES)
    return TriageResult(
        urgency=4 if urgent else 3,
        category="ambiguous",
        summary="mock",
        confidence=0.9 if urgent else 0.5,
        source="mock",
    )


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[round(share * (len(ordered) - 1))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path, help="JSONL case files")
    parser.add_argument("--mock", action="store_true", help="offline: fake triager, no keys")
    args = parser.parse_args(argv)

    if (
        not args.mock
        and claude_client() is None
        and not os.environ.get("TYPESAFE_API_KEY", "").strip()
    ):
        print("fallback: no ANTHROPIC_API_KEY and no TYPESAFE_API_KEY, nothing to evaluate")
        return 1
    try:
        cases = resolve_cases(args.paths, args.mock)
    except CaseError as exc:
        print(exc)
        return 1
    if not cases:
        print("no cases to evaluate")
        return 1
    run: Callable = mock_triage if args.mock else triage
    rows = []
    for case in cases:
        transcript = [(speaker, text) for speaker, text in case["transcript"]]
        started = time.perf_counter()
        result = run(transcript, case.get("risk_flags", []))
        rows.append((case, result, time.perf_counter() - started))

    under = [(c, r) for c, r, _ in rows if r is not None and r.urgency < c["expected_urgency"]]
    failed = [c for c, r, _ in rows if r is None]
    print(f"UNDER-ESCALATIONS: {len(under)}")
    for case, result in under:
        print(
            f"  {case['id']}: expected {case['expected_urgency']}, got {result.urgency} "
            f"({result.category}, {result.source}, confidence {result.confidence:.2f})"
        )
        for speaker, text in case["transcript"]:
            print(f"      {speaker}: {text}")
    if failed:
        print(f"FAILED (backend would default to urgency 3): {', '.join(c['id'] for c in failed)}")

    scored = [(c, r) for c, r, _ in rows if r is not None]
    exact = sum(r.urgency == c["expected_urgency"] for c, r in scored)
    category = sum(r.category == c["expected_category"] for c, r in scored)
    print(
        f"\ncases {len(rows)}  scored {len(scored)}  exact urgency {exact}  "
        f"over {len(scored) - exact - len(under)}  under {len(under)}  "
        f"category match {category}"
    )
    print("confusion (rows expected, columns predicted 1-4):")
    for expected in LEVELS:
        counts = [
            sum(c["expected_urgency"] == expected and r.urgency == got for c, r in scored)
            for got in LEVELS
        ]
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
