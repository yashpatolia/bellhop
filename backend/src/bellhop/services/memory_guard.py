"""Guarded writes to resident memory: no made-up, duplicate or clinical facts."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import count
from typing import Protocol

from bellhop.adapters.local_memory import tokenize
from bellhop.domain import MemoryFact
from bellhop.services.memory_service import MemoryService

MIN_LEN = 8
MAX_LEN = 280
MIN_CONFIDENCE = 0.6
DUPLICATE_JACCARD = 0.8

_CONDITIONS = (
    "diabetes|cancer|dementia|alzheimer|infection|pneumonia|arthritis|hypertension|"
    "depression|anxiety|stroke|parkinson|osteoporosis|anemia|copd|asthma|heart disease"
)
_CLINICAL = re.compile(
    rf"diagnosed with|diagnosis|prescribed|prescription|\bdoses?\b|\bdosage\b|"
    rf"\d\s*(?:mg|mcg|ml)\b|\byou (?:have|got|suffer from) (?:an? |the )?(?:{_CONDITIONS})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Accepted:
    fact: MemoryFact


@dataclass(frozen=True)
class Rejected:
    reason: str


Result = Accepted | Rejected


@dataclass
class PendingFact:
    id: str
    resident_id: str
    text: str
    tags: tuple[str, ...] = field(default_factory=tuple)
    source: str = "conversation"
    confidence: float = 0.0


class _Index(Protocol):
    def facts(self, resident_id: str) -> list[MemoryFact]: ...
    def remove(self, fact_id: str) -> bool: ...
    def remove_all(self, resident_id: str) -> int: ...


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


class MemoryGuard:
    def __init__(self, memory_service: MemoryService, index: _Index) -> None:
        self._memory = memory_service
        self._index = index
        self._pending: dict[str, PendingFact] = {}
        self._seq = count(1)

    def propose(
        self,
        resident_id: str,
        text: str,
        tags: Sequence[str] = (),
        source: str = "conversation",
        confidence: float = 1.0,
    ) -> Result:
        text = text.strip()
        if len(text) < MIN_LEN:
            return Rejected("too_short")
        if len(text) > MAX_LEN:
            return Rejected("too_long")
        if _CLINICAL.search(text):
            return Rejected("clinical_claim")
        if self._is_duplicate(resident_id, text):
            return Rejected("duplicate")
        if source != "staff" and confidence < MIN_CONFIDENCE:
            pid = f"pending-{next(self._seq)}"
            self._pending[pid] = PendingFact(
                pid, resident_id, text, tuple(tags), source, confidence
            )
            return Rejected("pending_review")
        return Accepted(self._memory.remember(resident_id, text, tags))

    def pending(self, resident_id: str) -> list[PendingFact]:
        return [p for p in self._pending.values() if p.resident_id == resident_id]

    def _owned(self, pending_id: str, resident_id: str | None) -> PendingFact:
        item = self._pending[pending_id]
        if resident_id is not None and item.resident_id != resident_id:
            raise KeyError(pending_id)
        return item

    def approve(self, pending_id: str, resident_id: str | None = None) -> Accepted:
        item = self._owned(pending_id, resident_id)
        del self._pending[pending_id]
        return Accepted(self._memory.remember(item.resident_id, item.text, item.tags))

    def reject(self, pending_id: str, resident_id: str | None = None) -> None:
        self._owned(pending_id, resident_id)
        del self._pending[pending_id]

    def forget(self, resident_id: str, fact_id: str) -> bool:
        if not any(f.id == fact_id for f in self._index.facts(resident_id)):
            return False
        return self._index.remove(fact_id)

    def forget_all(self, resident_id: str) -> int:
        for pid in [p.id for p in self.pending(resident_id)]:
            del self._pending[pid]
        return self._index.remove_all(resident_id)

    def _is_duplicate(self, resident_id: str, text: str) -> bool:
        tokens = tokenize(text)
        return any(
            _jaccard(tokens, tokenize(f.text)) >= DUPLICATE_JACCARD
            for f in self._index.facts(resident_id)
        )
