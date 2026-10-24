"""Moss-backed memory index with a lexical fallback.

The Moss SDK is imported lazily and every Moss call is guarded: a missing SDK, missing
credentials, a network error or an empty answer all degrade to the wrapped `MemoryIndex`.
"""

from __future__ import annotations

import logging
from typing import Any

from bellhop.domain import MemoryFact
from bellhop.ports import MemoryIndex

log = logging.getLogger(__name__)


class MossMemoryIndex:
    def __init__(
        self,
        fallback: MemoryIndex,
        project_id: str | None = None,
        project_key: str | None = None,
        index_name: str = "bellhop-memory",
    ) -> None:
        self._fallback = fallback
        self._project_id = project_id
        self._project_key = project_key
        self._index_name = index_name
        self._facts: dict[str, MemoryFact] = {}

    @property
    def _configured(self) -> bool:
        return bool(self._project_id and self._project_key)

    def add(self, fact: MemoryFact) -> None:
        self._fallback.add(fact)
        self._facts[fact.id] = fact
        if self._configured:
            try:
                self._upsert(fact)
            except Exception:
                log.warning("moss upsert failed; fallback index still has the fact", exc_info=True)

    def recall(self, resident_id: str, utterance: str, k: int = 3) -> list[MemoryFact]:
        if self._configured:
            try:
                found = self._resolve(resident_id, self._search(resident_id, utterance, k))
                if found:
                    return found[:k]
            except Exception:
                log.warning("moss search failed; using fallback index", exc_info=True)
        return self._fallback.recall(resident_id, utterance, k)

    def remove(self, fact_id: str) -> bool:
        """Forget one fact: drop it here and in the wrapped index."""
        self._facts.pop(fact_id, None)
        remover = getattr(self._fallback, "remove", None)
        return bool(remover(fact_id)) if remover else False

    def remove_all(self, resident_id: str) -> int:
        """Forget every fact for a resident."""
        for fid in [i for i, f in self._facts.items() if f.resident_id == resident_id]:
            del self._facts[fid]
        remover = getattr(self._fallback, "remove_all", None)
        return int(remover(resident_id)) if remover else 0

    def facts(self, resident_id: str) -> list[MemoryFact]:
        lister = getattr(self._fallback, "facts", None)
        if lister is not None:
            return lister(resident_id)
        return [f for f in self._facts.values() if f.resident_id == resident_id]

    def _resolve(self, resident_id: str, fact_ids: list[str]) -> list[MemoryFact]:
        # The wrapped index is the source of truth: Moss may still hold deleted facts.
        live = {f.id for f in self.facts(resident_id)}
        facts = (self._facts.get(i) for i in fact_ids if i in live)
        return [f for f in facts if f is not None and f.resident_id == resident_id]

    # --- Moss SDK boundary: the only code that touches the SDK (API shape unverified). ---

    def _client(self) -> Any:
        from moss import MossClient  # type: ignore[import-not-found]  # lazy, optional

        return MossClient(self._project_id, self._project_key)

    def _upsert(self, fact: MemoryFact) -> None:
        doc = {"id": fact.id, "text": fact.text, "metadata": {"resident_id": fact.resident_id}}
        self._client().add_documents(self._index_name, [doc])

    def _search(self, resident_id: str, utterance: str, k: int) -> list[str]:
        result = self._client().query(self._index_name, utterance, top_k=k * 4)
        return [d.id for d in result.docs]
