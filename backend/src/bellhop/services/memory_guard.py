"""Guarded writes to resident memory: no made-up, duplicate or clinical facts."""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
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
    quote: str | None = None
    call_id: str | None = None


class PendingStore(Protocol):
    """Where facts wait for a nurse. In memory by default; persistent when the data must survive."""

    def add(self, item: PendingFact) -> None: ...
    def get(self, pending_id: str) -> PendingFact:
        """Raises KeyError for an unknown id."""
        ...

    def remove(self, pending_id: str) -> None: ...
    def for_resident(self, resident_id: str) -> list[PendingFact]: ...
    def last_number(self) -> int:
        """The highest N in ids shaped `pending-N`, so new ids never repeat a stored one."""
        ...


class InMemoryPending:
    def __init__(self) -> None:
        self._items: dict[str, PendingFact] = {}

    def add(self, item: PendingFact) -> None:
        self._items[item.id] = item

    def get(self, pending_id: str) -> PendingFact:
        return self._items[pending_id]

    def remove(self, pending_id: str) -> None:
        del self._items[pending_id]

    def for_resident(self, resident_id: str) -> list[PendingFact]:
        return [p for p in self._items.values() if p.resident_id == resident_id]

    def last_number(self) -> int:
        return max((_number(i) for i in self._items), default=0)


def _number(pending_id: str) -> int:
    tail = pending_id.rpartition("-")[2]
    return int(tail) if tail.isdigit() else 0


class _Index(Protocol):
    def facts(self, resident_id: str) -> list[MemoryFact]: ...
    def update(self, fact: MemoryFact) -> None: ...
    def remove(self, fact_id: str) -> bool: ...
    def remove_all(self, resident_id: str) -> int: ...


def _normalise(text: str) -> str:
    return " ".join(text.casefold().split())


def _similar(a: str, b: str) -> bool:
    ta, tb = tokenize(a), tokenize(b)
    if not ta and not tb:
        # Nothing to compare lexically: only identical text is a duplicate.
        return _normalise(a) == _normalise(b)
    return len(ta & tb) / len(ta | tb) >= DUPLICATE_JACCARD


class MemoryGuard:
    def __init__(
        self, memory_service: MemoryService, index: _Index, pending: PendingStore | None = None
    ) -> None:
        self._memory = memory_service
        self._index = index
        self._pending = pending if pending is not None else InMemoryPending()
        self._seq = count(self._pending.last_number() + 1)
        self._lock = threading.RLock()  # makes check-then-store atomic

    def propose(
        self,
        resident_id: str,
        text: str,
        tags: Sequence[str] = (),
        source: str = "conversation",
        confidence: float = 1.0,
        quote: str | None = None,
        call_id: str | None = None,
        at: datetime | None = None,
    ) -> Result:
        """`at` dates a history import: when the fact was learned, or heard again."""
        text = text.strip()
        with self._lock:
            if (rejected := self._check(resident_id, text)) is not None:
                if rejected.reason == "duplicate":
                    self._reconfirm(resident_id, text, at)
                return rejected
            if source != "staff" and confidence < MIN_CONFIDENCE:
                pid = f"pending-{next(self._seq)}"
                self._pending.add(
                    PendingFact(
                        pid, resident_id, text, tuple(tags), source, confidence, quote, call_id
                    )
                )
                return Rejected("pending_review")
            return Accepted(
                self._memory.remember(
                    resident_id,
                    text,
                    tags,
                    source=source,
                    confidence=confidence,
                    quote=quote,
                    call_id=call_id,
                    at=at,
                )
            )

    def _check(self, resident_id: str, text: str) -> Rejected | None:
        """Safety and duplicate rules shared by propose and approve."""
        if len(text) < MIN_LEN:
            return Rejected("too_short")
        if len(text) > MAX_LEN:
            return Rejected("too_long")
        if _CLINICAL.search(text):
            return Rejected("clinical_claim")
        if self._is_duplicate(resident_id, text):
            return Rejected("duplicate")
        return None

    def pending(self, resident_id: str) -> list[PendingFact]:
        return self._pending.for_resident(resident_id)

    def _owned(self, pending_id: str, resident_id: str | None) -> PendingFact:
        item = self._pending.get(pending_id)
        if resident_id is not None and item.resident_id != resident_id:
            raise KeyError(pending_id)
        return item

    def approve(self, pending_id: str, resident_id: str | None = None) -> Result:
        """Store a pending fact after re-running the safety and duplicate rules.

        A fact that is now unsafe or a duplicate is dropped and returned as Rejected.
        """
        with self._lock:
            item = self._owned(pending_id, resident_id)
            self._pending.remove(pending_id)
            if (rejected := self._check(item.resident_id, item.text)) is not None:
                return rejected
            return Accepted(
                self._memory.remember(
                    item.resident_id,
                    item.text,
                    item.tags,
                    source=item.source,
                    confidence=item.confidence,
                    quote=item.quote,
                    call_id=item.call_id,
                )
            )

    def reject(self, pending_id: str, resident_id: str | None = None) -> None:
        self._owned(pending_id, resident_id)
        self._pending.remove(pending_id)

    def facts(self, resident_id: str) -> list[MemoryFact]:
        """Every stored fact for the resident, oldest first."""
        return self._index.facts(resident_id)

    def _reconfirm(self, resident_id: str, text: str, at: datetime | None = None) -> None:
        """Hearing a known fact again raises its times_seen and refreshes last_confirmed."""
        for fact in self._index.facts(resident_id):
            if _similar(text, fact.text):
                fact.times_seen += 1
                fact.last_confirmed = max(
                    filter(None, [fact.last_confirmed, at or self._memory.now()])
                )
                self._index.update(fact)
                return

    def forget(self, resident_id: str, fact_id: str) -> bool:
        if not any(f.id == fact_id for f in self._index.facts(resident_id)):
            return False
        return self._index.remove(fact_id)

    def forget_all(self, resident_id: str) -> int:
        for pid in [p.id for p in self.pending(resident_id)]:
            self._pending.remove(pid)
        return self._index.remove_all(resident_id)

    def _is_duplicate(self, resident_id: str, text: str) -> bool:
        return any(_similar(text, f.text) for f in self._index.facts(resident_id))
