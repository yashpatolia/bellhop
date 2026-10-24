"""Learn from a finished conversation, keeping only what survives verification.

The extractor (a model) proposes facts. Code, not the model, decides what is trusted:
a fact must be grounded in a verbatim quote by the right speaker, be about the resident
(or their family), and pass the MemoryGuard. Anything doubtful goes to the nurse review
queue. Precision beats recall: a wrong memory does more harm than a missing one.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from bellhop.domain import MemoryFact, Turn
from bellhop.domain.learning import CandidateFact, FactKind, Subject
from bellhop.ports.learning import FactExtractor
from bellhop.services.memory_guard import Accepted, MemoryGuard
from bellhop.services.scrub import scrub

MIN_CONFIDENCE = 0.3  # below this a candidate is noise, not worth a nurse's time
HEDGED_FACTOR = 0.6  # wishes and maybes are pushed toward review
HEALTH_CAP = 0.55  # health claims always wait for a nurse (guard threshold is 0.6)

_HEDGE = re.compile(
    r"\b(?:would love|i'd love|i wish|if i could|if only|maybe|perhaps|i guess|might|"
    r"used to|someday|one day|sometimes i think)\b",
    re.IGNORECASE,
)
_SPEAKER_TURN = {"resident": "resident", "staff": "nurse"}


@dataclass
class LearnReport:
    stored: list[MemoryFact] = field(default_factory=list)
    pending: int = 0
    dropped: dict[str, int] = field(default_factory=dict)


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", "", text.casefold()).split())


class MemoryLearner:
    def __init__(self, extractor: FactExtractor, guard: MemoryGuard) -> None:
        self._extractor = extractor
        self._guard = guard

    def learn(
        self,
        resident_id: str,
        transcript: Sequence[Turn],
        resident_name: str | None = None,
        known_facts: Sequence[str] = (),
        call_id: str | None = None,
    ) -> LearnReport:
        clean = [t.model_copy(update={"text": scrub(t.text, resident_name)}) for t in transcript]
        report = LearnReport()
        dropped: Counter[str] = Counter()
        seen: set[str] = set()
        for cand in self._extractor.extract(clean, known_facts):
            reason = self._gate(cand, clean)
            if reason is None and _norm(cand.text) in seen:
                reason = "duplicate"
            if reason is not None:
                dropped[reason] += 1
                continue
            seen.add(_norm(cand.text))
            result = self._guard.propose(
                resident_id,
                cand.text,
                tags=[cand.kind.value],
                source="conversation",
                confidence=self._confidence(cand),
                quote=cand.quote,
                call_id=call_id,
            )
            if isinstance(result, Accepted):
                report.stored.append(result.fact)
            elif result.reason == "pending_review":
                report.pending += 1
            else:
                dropped[result.reason] += 1
        report.dropped = dict(dropped)
        return report

    def _gate(self, cand: CandidateFact, transcript: Sequence[Turn]) -> str | None:
        if not cand.text.strip() or not cand.quote.strip():
            return "empty"
        if not self._grounded(cand, transcript):
            return "not_grounded"
        if cand.subject is Subject.OTHER and cand.kind is not FactKind.PERSON:
            return "not_about_resident"
        if self._confidence(cand) < MIN_CONFIDENCE:
            return "low_confidence"
        return None

    @staticmethod
    def _grounded(cand: CandidateFact, transcript: Sequence[Turn]) -> bool:
        who = _SPEAKER_TURN[cand.speaker]
        quote = _norm(cand.quote)
        return any(quote in _norm(t.text) for t in transcript if t.speaker == who)

    @staticmethod
    def _confidence(cand: CandidateFact) -> float:
        conf = max(0.0, min(1.0, cand.confidence))
        if _HEDGE.search(cand.quote):
            conf *= HEDGED_FACTOR
        if cand.kind is FactKind.HEALTH:
            conf = min(conf, HEALTH_CAP)
        return conf
