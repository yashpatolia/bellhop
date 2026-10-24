"""(4) Evaluate on the held-out eval set. Dev only.

    cd ml/pi && uv run --group train python ../dev/train/evaluate.py [--claude]

Compares, per group (hard+backend cases, hand-verified sample, all):
  floor          the backend's keyword floor alone (no hit counts as urgency 1)
  local          the local scorer alone
  floor+local    max of the two: what the local scorer adds on top of the keyword floor
and, with --claude (needs ANTHROPIC_API_KEY):
  claude, claude+floor, claude+floor+local
Under-escalation = predicted below true when true >= 3. Over-escalation rate = share predicted above
true. It also prints local latency and the artifact size.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
PI_SRC = Path(__file__).resolve().parents[2] / "pi" / "src"
BACKEND_SRC = Path(__file__).resolve().parents[3].parent / "calhacks-13" / "backend" / "src"
sys.path[:0] = [str(PI_SRC), str(BACKEND_SRC)]

from rover import config  # noqa: E402
from rover.triage import local  # noqa: E402
from train import metrics, textprep  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"


def floor_urgency(transcript) -> int:
    from bellhop.services.triage_guard import keyword_floor

    floor = keyword_floor([tuple(t) for t in transcript]).urgency
    return int(floor) if floor is not None else 1


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[round(share * (len(ordered) - 1))]


def show(name: str, y_true: list[int], y_pred: list[int]) -> dict:
    rep = metrics.report(y_true, y_pred)
    recall = " ".join(f"{rep['recall'][lv]:.2f}" for lv in metrics.LEVELS)
    prec = " ".join(f"{rep['precision'][lv]:.2f}" for lv in metrics.LEVELS)
    print(
        f"  {name:<18} under {rep['under_escalations']:>2}  "
        f"over {rep['over_escalation_rate']:.3f}  false-alarm {rep['false_alarm_rate']:.3f}  "
        f"exact {rep['exact']:.3f}  urgent recall {rep['urgent_recall']:.3f}  "
        f"recall[1-4] {recall}  precision[1-4] {prec}"
    )
    return rep


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--claude", action="store_true", help="also run Claude (ANTHROPIC_API_KEY)")
    parser.add_argument("--min-confidence", type=float, default=config.LOCAL_MIN_CONFIDENCE)
    args = parser.parse_args(argv)
    config.LOCAL_MIN_CONFIDENCE = args.min_confidence

    rows = textprep.read_jsonl(DATA / "eval.jsonl")
    scorer = local.get_scorer()
    if scorer is None:
        print("no local scorer: train first (train.py) and fetch the model")
        return 1
    claude_ask = None
    if args.claude:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("ANTHROPIC_API_KEY is not set: skipping the Claude columns")
        else:
            from rover.triage.triage import ask_claude as claude_ask  # noqa: F811

    preds: dict[str, list[int]] = {k: [] for k in ("floor", "local", "floor+local")}
    if claude_ask:
        preds |= {"claude": [], "claude+floor": [], "claude+floor+local": []}
    latencies = []
    for row in rows:
        transcript = [tuple(t) for t in row["transcript"]]
        floor = floor_urgency(transcript)
        started = time.perf_counter()
        score = local.score_transcript(scorer, transcript)
        latencies.append((time.perf_counter() - started) * 1000)
        usable = score[0] if score and score[1] >= config.LOCAL_MIN_CONFIDENCE else 1
        preds["floor"].append(floor)
        preds["local"].append(usable)
        preds["floor+local"].append(max(floor, usable))
        if claude_ask:
            result = claude_ask(transcript, [])
            base = result.urgency if result else 3  # the backend's default when triage fails
            preds["claude"].append(base)
            preds["claude+floor"].append(max(base, floor))
            preds["claude+floor+local"].append(max(base, floor, usable))

    groups = {
        "hard+backend": [
            i for i, r in enumerate(rows) if r["label_source"] in ("backend", "hard_cases")
        ],
        "hand-verified": [i for i, r in enumerate(rows) if r["label_source"] == "hand-verified"],
        "all": list(range(len(rows))),
    }
    for group, idx in groups.items():
        y = [rows[i]["urgency"] for i in idx]
        counts = [y.count(lv) for lv in metrics.LEVELS]
        print(f"{group} (n={len(idx)}, per class {counts}, min conf {config.LOCAL_MIN_CONFIDENCE})")
        for name, values in preds.items():
            show(name, y, [values[i] for i in idx])
    p50, p95 = percentile(latencies, 0.5), percentile(latencies, 0.95)
    print(f"local latency per visit (embed + head): p50 {p50:.1f} ms, p95 {p95:.1f} ms")
    print(f"head file {config.LOCAL_HEAD.stat().st_size} bytes, model {scorer.head.model}")
    missed = [
        (rows[i]["id"], rows[i]["urgency"], preds["floor+local"][i])
        for i in range(len(rows))
        if rows[i]["urgency"] >= 3 and preds["floor+local"][i] < rows[i]["urgency"]
    ]
    print(f"floor+local misses (id, true, predicted): {missed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
