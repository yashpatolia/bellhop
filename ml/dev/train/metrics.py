"""Pure scoring helpers: the report the success criterion is read from, and threshold tuning."""

from __future__ import annotations

import itertools
from collections.abc import Sequence

import numpy as np

LEVELS = (1, 2, 3, 4)


def report(y_true: Sequence[int], y_pred: Sequence[int]) -> dict:
    n = len(y_true)
    confusion = {t: {p: 0 for p in LEVELS} for t in LEVELS}
    for true, pred in zip(y_true, y_pred, strict=True):
        confusion[true][pred] += 1
    precision, recall = {}, {}
    for level in LEVELS:
        tp = confusion[level][level]
        predicted = sum(confusion[t][level] for t in LEVELS)
        actual = sum(confusion[level].values())
        precision[level] = tp / predicted if predicted else 0.0
        recall[level] = tp / actual if actual else 0.0
    urgent = [(t, p) for t, p in zip(y_true, y_pred, strict=True) if t >= 3]
    calm = [(t, p) for t, p in zip(y_true, y_pred, strict=True) if t < 3]
    return {
        "n": n,
        "exact": sum(t == p for t, p in zip(y_true, y_pred, strict=True)) / n if n else 0.0,
        "under_escalations": sum(p < t for t, p in urgent),
        "over_escalation_rate": (
            sum(p > t for t, p in zip(y_true, y_pred, strict=True)) / n if n else 0.0
        ),
        "false_alarm_rate": (sum(p >= 3 for _, p in calm) / len(calm)) if calm else 0.0,
        "urgent_recall": (sum(p >= 3 for _, p in urgent) / len(urgent)) if urgent else 0.0,
        "precision": precision,
        "recall": recall,
        "confusion": confusion,
    }


def choose_shift(
    logits: np.ndarray, y_true: Sequence[int], grid: Sequence[float], miss_cost: float = 10.0
) -> np.ndarray:
    """Pick the (urgency 3, urgency 4) logit shifts that minimise
    miss_cost * under-escalations + over-escalations. Ties go to the smaller shift."""
    y = np.asarray(y_true)
    best_key, best = None, np.zeros(4)
    for s3, s4 in itertools.product(grid, grid):
        shift = np.array([0.0, 0.0, s3, s4])
        pred = (logits + shift).argmax(axis=1) + 1
        under = int(((y >= 3) & (pred < y)).sum())
        over = int((pred > y).sum())
        key = (miss_cost * under + over, s3 + s4, s3)
        if best_key is None or key < best_key:
            best_key, best = key, shift
    return best
