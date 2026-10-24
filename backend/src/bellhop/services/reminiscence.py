"""Era-based reminiscence prompts and memory ingest for residents."""

from __future__ import annotations

from bellhop.domain import MemoryFact
from bellhop.ports import ResidentRepository
from bellhop.ports.content import ContentFeed, ContentItem
from bellhop.services.memory_service import MemoryService

TAG = "reminiscence"


class ReminiscenceService:
    def __init__(
        self, feed: ContentFeed, memory: MemoryService, residents: ResidentRepository
    ) -> None:
        self._feed = feed
        self._memory = memory
        self._residents = residents

    def _items(self, resident_id: str, limit: int) -> list[ContentItem]:
        resident = self._residents.get(resident_id)
        if resident is None or resident.birth_year is None:
            return []
        return self._feed.for_era(resident.birth_year, limit)

    @staticmethod
    def _text(item: ContentItem) -> str:
        return f"{item.title} ({item.year}): {item.blurb}"

    def prompt_context(self, resident_id: str, k: int = 3) -> str:
        return "\n".join(f"- {self._text(i)}" for i in self._items(resident_id, k))

    def ingest(self, resident_id: str, limit: int = 5) -> list[MemoryFact]:
        return [
            self._memory.remember(resident_id, self._text(i), tags=[TAG, i.kind])
            for i in self._items(resident_id, limit)
        ]
