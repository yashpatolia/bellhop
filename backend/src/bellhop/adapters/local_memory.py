"""Dependency-free lexical memory index. Default adapter and Moss fallback."""

from __future__ import annotations

import re

from bellhop.domain import MemoryFact

TEXT_WEIGHT = 1.0
TAG_WEIGHT = 2.0

_WORD = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    """a an and any are as at be been but by can could did do does for from get got had has have
    her him his how i if in is it its me my of on or our she so some that the their them then
    there they this to was we were what when where which who will with would you your yours
    please""".split()
)


def tokenize(text: str) -> set[str]:
    """Lowercased content words with a trivial plural stem (sugars -> sugar)."""
    out = set()
    for word in _WORD.findall(text.lower()):
        if word in _STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.add(word)
    return out


class _ResidentIndex:
    def __init__(self) -> None:
        self.facts: dict[str, MemoryFact] = {}
        self.postings: dict[str, dict[str, float]] = {}  # token -> {fact_id: weight}

    @staticmethod
    def _weights(fact: MemoryFact) -> dict[str, float]:
        weights = dict.fromkeys(tokenize(fact.text), TEXT_WEIGHT)
        for token in tokenize(" ".join(fact.tags)):
            weights[token] = weights.get(token, 0.0) + TAG_WEIGHT
        return weights

    def add(self, fact: MemoryFact) -> None:
        old = self.facts.get(fact.id)
        if old is not None:
            for token in self._weights(old):
                del self.postings[token][fact.id]
        self.facts[fact.id] = fact
        for token, weight in self._weights(fact).items():
            self.postings.setdefault(token, {})[fact.id] = weight

    def recall(self, utterance: str, k: int) -> list[MemoryFact]:
        scores: dict[str, float] = {}
        for token in tokenize(utterance):
            for fact_id, weight in self.postings.get(token, {}).items():
                scores[fact_id] = scores.get(fact_id, 0.0) + weight
        # Highest score, then most recent, then id, so ordering is deterministic.
        ranked = sorted(
            scores, key=lambda i: (-scores[i], -self.facts[i].created_at.timestamp(), i)
        )
        return [self.facts[i] for i in ranked[: max(k, 0)]]


class LocalMemoryIndex:
    """Inverted index per resident; implements the `MemoryIndex` port."""

    def __init__(self) -> None:
        self._by_resident: dict[str, _ResidentIndex] = {}

    def add(self, fact: MemoryFact) -> None:
        self._by_resident.setdefault(fact.resident_id, _ResidentIndex()).add(fact)

    def recall(self, resident_id: str, utterance: str, k: int = 3) -> list[MemoryFact]:
        index = self._by_resident.get(resident_id)
        return index.recall(utterance, k) if index else []
