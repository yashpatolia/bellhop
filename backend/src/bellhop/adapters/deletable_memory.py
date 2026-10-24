"""Local memory index that supports deleting facts (nurse corrections, privacy)."""

from __future__ import annotations

from bellhop.adapters.local_memory import LocalMemoryIndex, _ResidentIndex
from bellhop.domain import MemoryFact


class DeletableLocalMemoryIndex(LocalMemoryIndex):
    def facts(self, resident_id: str) -> list[MemoryFact]:
        """All facts for a resident, oldest first."""
        index = self._by_resident.get(resident_id)
        if index is None:
            return []
        return sorted(index.facts.values(), key=lambda f: (f.created_at, f.id))

    def update(self, fact: MemoryFact) -> None:
        """A fact changed in place (heard again). A persistent index saves it."""

    def remove(self, fact_id: str) -> bool:
        """Delete one fact by id. Returns whether anything was removed."""
        for resident_id, index in self._by_resident.items():
            if fact_id in index.facts:
                rebuilt = _ResidentIndex()
                for fact in index.facts.values():
                    if fact.id != fact_id:
                        rebuilt.add(fact)
                self._by_resident[resident_id] = rebuilt
                return True
        return False

    def remove_all(self, resident_id: str) -> int:
        """Delete every fact for a resident. Returns the count removed."""
        index = self._by_resident.pop(resident_id, None)
        return len(index.facts) if index else 0
