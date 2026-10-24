"""(3) Train the head and export it. Dev only.

    cd ml/pi && uv run --group train python ../dev/train/train.py [--model NAME] [--compare]

Reads data/train.jsonl ({id, text, urgency}); the eval set is never read here. Embeds with
fastembed (ONNX), fits a multinomial logistic regression with class weights that favour recall for
urgency 3 and 4, picks the logit shifts from out-of-fold predictions (so no eval data is used), and
writes the small head to pi/src/rover/triage/local_head.npz.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from train import metrics, textprep  # noqa: E402

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
ML = HERE.parents[1]
HEAD_OUT = ML / "pi" / "src" / "rover" / "triage" / "local_head.npz"
EMBED_DIR = ML / "pi" / "models" / "embed"
MODELS = ["sentence-transformers/all-MiniLM-L6-v2", "BAAI/bge-small-en-v1.5"]
CLASS_WEIGHT = {1: 1.0, 2: 1.0, 3: 2.0, 4: 3.0}
SHIFT_GRID = [round(0.25 * i, 2) for i in range(0, 13)]


def l2_normalise(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


def embed_texts(texts: list[str], model: str) -> np.ndarray:
    """Embed with a small on-disk cache so retraining does not re-run the model."""
    from fastembed import TextEmbedding

    cache = DATA / "emb_cache"
    cache.mkdir(parents=True, exist_ok=True)
    tag = hashlib.md5(model.encode()).hexdigest()[:6]
    paths = [cache / f"{tag}-{hashlib.md5(t.encode()).hexdigest()}.npy" for t in texts]
    missing = [i for i, p in enumerate(paths) if not p.exists()]
    if missing:
        engine = TextEmbedding(model_name=model, cache_dir=str(EMBED_DIR))
        for i, vec in zip(missing, engine.embed([texts[i] for i in missing]), strict=True):
            np.save(paths[i], np.asarray(vec, dtype=np.float32))
    return l2_normalise(np.stack([np.load(p) for p in paths]))


def fit_head(X: np.ndarray, y: np.ndarray, c: float = 4.0):
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(C=c, class_weight=CLASS_WEIGHT, max_iter=2000)
    model.fit(X, y)
    return model


def full_logits(model, X: np.ndarray) -> np.ndarray:
    """Logits for all four classes (columns 0..3 = urgency 1..4), zero if a class is absent."""
    out = np.zeros((len(X), 4))
    for column, level in enumerate(model.classes_):
        out[:, level - 1] = X @ model.coef_[column] + model.intercept_[column]
    return out


def out_of_fold_logits(X: np.ndarray, y: np.ndarray, c: float, folds: int = 5) -> np.ndarray:
    from sklearn.model_selection import StratifiedKFold

    out = np.zeros((len(X), 4))
    for train_idx, test_idx in StratifiedKFold(folds, shuffle=True, random_state=0).split(X, y):
        out[test_idx] = full_logits(fit_head(X[train_idx], y[train_idx], c), X[test_idx])
    return out


def export_head(path: Path, model, shift: np.ndarray, embed_model: str) -> None:
    weights = np.zeros((4, model.coef_.shape[1]), dtype=np.float32)
    bias = np.zeros(4, dtype=np.float32)
    for column, level in enumerate(model.classes_):
        weights[level - 1] = model.coef_[column]
        bias[level - 1] = model.intercept_[column]
    absent = [lv for lv in (1, 2, 3, 4) if lv not in model.classes_]
    bias[[lv - 1 for lv in absent]] = -20.0  # a class never seen in training is never predicted
    np.savez_compressed(
        path,
        weights=weights,
        bias=bias,
        shift=shift.astype(np.float32),
        model=np.asarray(embed_model),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=MODELS[0])
    parser.add_argument("--compare", action="store_true", help="only compare embedding models")
    parser.add_argument("--c", type=float, default=4.0)
    parser.add_argument("--out", type=Path, default=HEAD_OUT)
    args = parser.parse_args(argv)

    rows = textprep.read_jsonl(DATA / "train.jsonl")
    texts, y = [r["text"] for r in rows], np.array([r["urgency"] for r in rows])
    print(f"train rows {len(rows)}  per class {np.bincount(y, minlength=5)[1:]}")
    models = MODELS if args.compare else [args.model]
    scored = {}
    for name in models:
        X = embed_texts(texts, name)
        for c in (1.0, 4.0, 16.0):
            logits = out_of_fold_logits(X, y, c)
            shift = metrics.choose_shift(logits, y, SHIFT_GRID)
            rep = metrics.report(y, (logits + shift).argmax(axis=1) + 1)
            scored[(name, c)] = (rep["under_escalations"], rep["over_escalation_rate"], shift)
            print(
                f"{name} C={c}: out-of-fold under {rep['under_escalations']} "
                f"over {rep['over_escalation_rate']:.3f} exact {rep['exact']:.3f} shift {shift[2:]}"
            )
    if args.compare:
        return 0
    X = embed_texts(texts, args.model)
    shift = scored[(args.model, args.c)][2]
    export_head(args.out, fit_head(X, y, args.c), shift, args.model)
    print(f"wrote {args.out} ({args.out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
