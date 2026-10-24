"""(2) Prepare labelling batches and assemble train / eval files. Dev only.

    cd ml/pi && uv run --group train python ../dev/train/prepare.py eval-fixed
    cd ml/pi && uv run --group train python ../dev/train/prepare.py sample --source reddit --n 100 \
        --out verify
    cd ml/pi && uv run --group train python ../dev/train/prepare.py label-claude --batch NAME
    cd ml/pi && uv run --group train python ../dev/train/prepare.py build

Labels come from `data/labels/NAME.txt` lines `id 1-4`, written by hand or by label-claude
(needs ANTHROPIC_API_KEY). The eval set is: hard_cases.jsonl, the backend labelled cases and the
hand-verified sample `verify`. None of those texts, nor near copies, reach train.jsonl.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from train import labels, textprep  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
LABELS = DATA / "labels"
HARD_CASES = HERE.parent / "hard_cases.jsonl"
BACKEND_CASES = (
    HERE.parents[2].parent / "calhacks-13" / "backend" / "src" / "bellhop" / "labelled" / "cases.py"
)
SYNTHETIC = HERE / "synthetic_utterances.tsv"
VERIFY = "verify"  # the batch that is held out as the hand-verified eval sample


def load_backend_cases(path: Path) -> list[dict]:
    spec = importlib.util.spec_from_file_location("backend_cases", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["backend_cases"] = module
    spec.loader.exec_module(module)
    return [
        {
            "id": f"backend-{c.id}",
            "transcript": [list(turn) for turn in c.transcript],
            "urgency": c.expected_urgency,
            "label_source": "backend",
        }
        for c in module.CASES
    ]


def load_hard_cases() -> list[dict]:
    return [
        {
            "id": f"hard-{r['id']}",
            "transcript": r["transcript"],
            "urgency": r["expected_urgency"],
            "label_source": "hard_cases",
        }
        for r in textprep.read_jsonl(HARD_CASES)
    ]


def read_synthetic(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        level, text = line.split("\t", 1)
        rows.append(
            {
                "id": f"syn-{number}",
                "source": "synthetic",
                "text": text.strip(),
                "urgency": int(level),
                "label_source": "written for the task",
            }
        )
    return rows


def eval_text(row: dict) -> str:
    return " ".join(t for s, t in row["transcript"] if s == "resident")


HEALTH = re.compile(
    r"\b(?:fell|fall|fallen|floor|chest|breath\w*|dizzy|faint\w*|confus\w*|pain\w*|hurts?|"
    r"bleed\w*|blood|unresponsive|collaps\w*|stroke|numb\w*|nause\w*|vomit\w*|pills?|"
    r"medic\w*|dose|nurse|hospital|ER|ambulance|choking|seizure|slurred|weak|sick|lonely|"
    r"bored|tea|garden|music)\b",
    re.I,
)  # picks out utterances about symptoms, falls, medicines and company


def sample(source: str, n: int, seed: int, exclude: set[str], kind: str = "any") -> list[dict]:
    rows = [
        r
        for r in textprep.read_jsonl(DATA / "candidates.jsonl")
        if r["source"].startswith(source)
        and r["id"] not in exclude
        and (kind == "any" or bool(HEALTH.search(r["text"])) == (kind == "health"))
    ]
    random.Random(seed).shuffle(rows)
    return rows[:n]


def build() -> None:
    fixed = load_hard_cases() + load_backend_cases(BACKEND_CASES)
    candidates = {r["id"]: r for r in textprep.read_jsonl(DATA / "candidates.jsonl")}
    verified_labels = labels.read_manual_labels(LABELS / f"{VERIFY}.txt")
    verified = labels.join_labels(
        [candidates[i] for i in verified_labels], verified_labels, "hand-verified"
    )
    eval_rows = fixed + [{**r, "transcript": [["resident", r["text"]]]} for r in verified]
    textprep.write_jsonl(DATA / "eval.jsonl", eval_rows)

    pool = read_synthetic(SYNTHETIC)
    for path in sorted(LABELS.glob("*.txt")):
        if path.stem == VERIFY:
            continue
        got = labels.read_manual_labels(path)
        pool += labels.join_labels([candidates[i] for i in got if i in candidates], got, path.stem)
    pool = textprep.dedupe(pool)
    held = [eval_text(r) for r in eval_rows]
    kept = textprep.drop_leaks(pool, held, threshold=0.7)
    textprep.write_jsonl(DATA / "train.jsonl", kept)
    per = {lv: sum(r["urgency"] == lv for r in kept) for lv in (1, 2, 3, 4)}
    print(f"eval rows {len(eval_rows)} (hard+backend {len(fixed)}, verified {len(verified)})")
    print(f"train rows {len(kept)} (dropped {len(pool) - len(kept)} as eval look-alikes) {per}")


def label_claude(batch: str, model: str) -> None:
    import anthropic

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set; label by hand into data/labels/NAME.txt instead")
    rows = textprep.read_jsonl(DATA / "batches" / f"{batch}.jsonl")
    got = labels.label_with_claude(anthropic.Anthropic(), model, [r["text"] for r in rows])
    LABELS.mkdir(parents=True, exist_ok=True)
    lines = [f"{r['id']} {g}" for r, g in zip(rows, got, strict=True) if g]
    (LABELS / f"{batch}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"labelled {len(lines)} of {len(rows)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    one = sub.add_parser("sample")
    one.add_argument("--source", required=True)
    one.add_argument("--n", type=int, required=True)
    one.add_argument("--seed", type=int, default=1)
    one.add_argument("--kind", choices=["any", "health", "other"], default="any")
    one.add_argument("--out", required=True, help="batch name")
    claude = sub.add_parser("label-claude")
    claude.add_argument("--batch", required=True)
    claude.add_argument("--model", default="claude-haiku-5-5")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        build()
    elif args.cmd == "sample":
        used = {r["id"] for p in (DATA / "batches").glob("*.jsonl") for r in textprep.read_jsonl(p)}
        rows = sample(args.source, args.n, args.seed, used, args.kind)
        textprep.write_jsonl(DATA / "batches" / f"{args.out}.jsonl", rows)
        print(f"{len(rows)} rows -> data/batches/{args.out}.jsonl")
    else:
        label_claude(args.batch, args.model)
    return 0


if __name__ == "__main__":
    sys.exit(main())
