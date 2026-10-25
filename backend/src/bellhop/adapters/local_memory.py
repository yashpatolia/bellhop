"""Dependency-free lexical memory index. Default adapter and Moss fallback."""

from __future__ import annotations

import re
import unicodedata

from bellhop.domain import MemoryFact

TEXT_WEIGHT = 1.0
TAG_WEIGHT = 2.0

# Scripts written without spaces between words: index them as character bigrams.
_UNSPACED = "\u0e00-\u0e7f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af"
_WORD = re.compile(rf"[{_UNSPACED}]+|[^\W_{_UNSPACED}]+|[^\w\s]")
_STOPWORDS = frozenset(
    """a an and any are as at be been but by can could did do does for from get got had has have
    her him his how i if in is it its me my of on or our she so some that the their them then
    there they this to was we were what when where which who will with would you your yours
    please""".split()
)


def tokenize(text: str) -> set[str]:
    """Lowercased content words (unicode aware) with a trivial plural stem.

    Unspaced scripts (CJK, Thai) become character bigrams; emoji count as one token each.
    """
    out: set[str] = set()
    for word in _WORD.findall(text.casefold()):
        if re.match(f"[{_UNSPACED}]", word):
            out.update(word[i : i + 2] for i in range(max(len(word) - 1, 1)))
        elif len(word) == 1 and not word.isalnum():
            if unicodedata.category(word) in ("So", "Sk"):
                out.add(word)
        elif word not in _STOPWORDS:
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
        if k <= 0:
            return []
        # An empty query is a deliberate resident briefing request from the rover and the
        # learning pipeline. There are no lexical terms to score, so return a bounded,
        # deterministic newest-first briefing instead of pretending this resident has no
        # memories at all.
        if not utterance.strip():
            ranked = sorted(
                self.facts,
                key=lambda i: (-self.facts[i].created_at.timestamp(), i),
            )
            return [self.facts[i] for i in ranked[:k]]
        scores: dict[str, float] = {}
        for token in tokenize(utterance):
            for fact_id, weight in list(self.postings.get(token, {}).items()):
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
