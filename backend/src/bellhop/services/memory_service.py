"""Remember and recall resident facts."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from bellhop.domain import MemoryFact
from bellhop.ports import Clock, IdGenerator, MemoryIndex


class MemoryService:
    def __init__(self, index: MemoryIndex, clock: Clock, ids: IdGenerator) -> None:
        self._index = index
        self._clock = clock
        self._ids = ids

    def remember(
        self,
        resident_id: str,
        text: str,
        tags: Sequence[str] = (),
        *,
        source: str = "staff",
        confidence: float = 1.0,
        quote: str | None = None,
        call_id: str | None = None,
        at: datetime | None = None,
    ) -> MemoryFact:
        now = at or self._clock.now()
        fact = MemoryFact(
            id=self._ids.new_id("fact"),
            resident_id=resident_id,
            text=text,
            tags=list(tags),
            created_at=now,
            source=source,
            confidence=confidence,
            quote=quote,
            call_id=call_id,
            last_confirmed=now,
        )
        self._index.add(fact)
        return fact

    def now(self):
        return self._clock.now()

    def recall(self, resident_id: str, utterance: str, k: int = 3) -> list[MemoryFact]:
        return self._index.recall(resident_id, utterance, k)

    def prompt_context(self, resident_id: str, utterance: str, k: int = 3) -> str:
        facts = self.recall(resident_id, utterance, k)
        return "\n".join(f"- {f.text}" for f in facts)
