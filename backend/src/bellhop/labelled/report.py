"""Precision/recall, confusion matrix and escalation threshold over labelled cases."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from bellhop.labelled.cases import LabelledCase

LEVELS = (1, 2, 3, 4)
Predictions = Mapping[str, tuple[int, float]]


@dataclass(frozen=True)
class ThresholdReport:
    precision: dict[int, float]
    recall: dict[int, float]
    confusion: dict[int, dict[int, int]]  # confusion[expected][predicted]
    under_escalations: list[str]
    suggested_threshold: float | None

    @property
    def under_escalation_count(self) -> int:
        return len(self.under_escalations)

    def format(self) -> str:
        lines = [
            f"UNDER-ESCALATIONS: {self.under_escalation_count}"
            + (f" ({', '.join(self.under_escalations)})" if self.under_escalations else ""),
            f"Suggested escalation threshold: {self.suggested_threshold}",
            "Urgency  precision  recall",
        ]
        lines += [f"{u:>7}  {self.precision[u]:>9.2f}  {self.recall[u]:>6.2f}" for u in LEVELS]
        lines.append("Confusion (rows expected, columns predicted 1-4):")
        lines += [f"  {e}: {[self.confusion[e][p] for p in LEVELS]}" for e in LEVELS]
        return "\n".join(lines)


def _scored(cases: Iterable[LabelledCase], predictions: Predictions):
    return [(c, *predictions[c.id]) for c in cases if c.id in predictions]


def suggest_escalation_threshold(
    cases: Iterable[LabelledCase], predictions: Predictions
) -> float | None:
    """Lowest cutoff t such that bumping every prediction with confidence < t up one level
    leaves no under-escalation. None when no cutoff can achieve that."""
    scored = _scored(cases, predictions)
    candidates = sorted({0.0, 1.0, *(conf for _, _, conf in scored)})
    for t in candidates:
        ok = True
        for c, pred, conf in scored:
            final = min(pred + 1, 4) if conf < t else pred
            if final < c.expected_urgency:
                ok = False
                break
        if ok:
            return t
    return None


def threshold_report(cases: Iterable[LabelledCase], predictions: Predictions) -> ThresholdReport:
    cases = list(cases)
    scored = _scored(cases, predictions)
    confusion = {e: {p: 0 for p in LEVELS} for e in LEVELS}
    for c, pred, _ in scored:
        confusion[c.expected_urgency][pred] += 1

    precision, recall = {}, {}
    for u in LEVELS:
        predicted = sum(confusion[e][u] for e in LEVELS)
        expected = sum(confusion[u].values())
        precision[u] = confusion[u][u] / predicted if predicted else 0.0
        recall[u] = confusion[u][u] / expected if expected else 0.0

    return ThresholdReport(
        precision=precision,
        recall=recall,
        confusion=confusion,
        under_escalations=[c.id for c, pred, _ in scored if pred < c.expected_urgency],
        suggested_threshold=suggest_escalation_threshold(cases, predictions),
    )
