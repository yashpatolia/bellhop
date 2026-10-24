"""Local triage scorer: a small ONNX sentence embedding plus a linear head, run offline on the Pi.

It is a recall floor that sits beside Claude. triage.py may only raise the urgency with it, never
lower it. Every failure (no head file, no embedding model, a broken ONNX run) gives None so a
visit is never held up by it.

The head is a few KB (`local_head.npz`, committed next to this file). The embedding model is
downloaded once by `python -m rover.triage.local` into MODELS_DIR/embed. Training lives in
dev/train and is not shipped to the Pi.
"""

from __future__ import annotations

import functools
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from rover import config

Embed = Callable[[str], np.ndarray]
EmbedFactory = Callable[[str, Path], Embed]
Transcript = list[tuple[str, str]]


def softmax(logits: np.ndarray) -> np.ndarray:
    shifted = np.asarray(logits, dtype=np.float64)
    shifted = shifted - shifted.max()
    exp = np.exp(shifted)
    return exp / exp.sum()


@dataclass
class Head:
    weights: np.ndarray  # (4, dim): row 0 is urgency 1
    bias: np.ndarray  # (4,)
    shift: np.ndarray  # (4,) recall tuning added to the logits after training
    model: str  # embedding model the head was trained on

    def predict(self, embedding: np.ndarray) -> tuple[int, float]:
        vec = np.asarray(embedding, dtype=np.float64)
        norm = np.linalg.norm(vec)
        vec = vec / norm if norm > 0 else vec
        probs = softmax(self.weights @ vec + self.bias + self.shift)
        best = int(np.argmax(probs))
        return best + 1, float(probs[best])


def load_head(path: Path) -> Head | None:
    try:
        with np.load(path, allow_pickle=False) as data:
            weights, bias, shift = data["weights"], data["bias"], data["shift"]
            model = str(data["model"])
    except (OSError, ValueError, KeyError):
        return None
    if weights.ndim != 2 or weights.shape[0] != 4 or bias.shape != (4,) or shift.shape != (4,):
        return None
    return Head(
        weights.astype(np.float64), bias.astype(np.float64), shift.astype(np.float64), model
    )


class LocalScorer:
    def __init__(self, head: Head, embed: Embed):
        self.head = head
        self._embed = embed

    def predict(self, text: str) -> tuple[int, float] | None:
        if not text.strip():
            return None
        try:
            return self.head.predict(self._embed(text))
        except Exception as exc:  # a bad ONNX run must not stop the visit
            print(f"local triage: embedding failed: {exc!r}")
            return None


def fastembed_factory(model: str, directory: Path) -> Embed:
    from fastembed import TextEmbedding  # imported late: only the Pi triage path needs it

    engine = TextEmbedding(model_name=model, cache_dir=str(directory), local_files_only=True)

    def embed(text: str) -> np.ndarray:
        return np.asarray(next(iter(engine.embed([text]))))

    return embed


def load_scorer(
    head_path: Path, embed_dir: Path, factory: EmbedFactory = fastembed_factory
) -> LocalScorer | None:
    head = load_head(head_path)
    if head is None:
        return None
    try:
        return LocalScorer(head, factory(head.model, embed_dir))
    except Exception as exc:
        print(f"fallback: local triage model not available ({type(exc).__name__}), skipped")
        return None


@functools.lru_cache(maxsize=1)
def get_scorer() -> LocalScorer | None:
    return load_scorer(config.LOCAL_HEAD, config.LOCAL_EMBED_DIR)


def score_transcript(
    scorer: LocalScorer | None, transcript: Transcript
) -> tuple[int, float] | None:
    """The most urgent score over the resident's lines (each line alone, so one calm sentence
    cannot dilute an emergency in another)."""
    if scorer is None:
        return None
    scores = [
        score
        for speaker, text in transcript
        if speaker == "resident" and (score := scorer.predict(text)) is not None
    ]
    return max(scores, key=lambda s: (s[0], s[1])) if scores else None


def download() -> int:
    """(Mac or Pi, online) Fetch the embedding model named by the head into MODELS_DIR/embed."""
    head = load_head(config.LOCAL_HEAD)
    if head is None:
        print(f"no head file at {config.LOCAL_HEAD}; run dev/train first")
        return 1
    from fastembed import TextEmbedding

    config.LOCAL_EMBED_DIR.mkdir(parents=True, exist_ok=True)
    TextEmbedding(model_name=head.model, cache_dir=str(config.LOCAL_EMBED_DIR))
    print(f"embedding model {head.model} is in {config.LOCAL_EMBED_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(download())
