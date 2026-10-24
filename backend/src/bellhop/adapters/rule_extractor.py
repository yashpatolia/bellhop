"""A deliberately simple extractor: phrase patterns on what the resident said.

It is the baseline Claude must beat (see `bellhop.labelled.memory_eval`) and an offline
fallback. It cannot read negation, sarcasm or confusion; the MemoryLearner gates and the
nurse review queue exist partly because of that.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from bellhop.domain import Turn
from bellhop.domain.learning import CandidateFact, FactKind, Subject

_SENTENCE = re.compile(r"[^.!?]+[.!?]?")
_LIKE = re.compile(
    r"\bI (?:really |just )?(?:love|like|enjoy|adore)\s+(?P<what>[^,.]+)", re.IGNORECASE
)
_DISLIKE = re.compile(
    r"\bI (?:really )?(?:hate|dislike|cannot stand|can't stand|can not stand)\s+(?P<what>[^,.]+)",
    re.IGNORECASE,
)
_PERSON = re.compile(
    r"\b(?i:my) (?:late |dear )?(?:grandson|granddaughter|daughter|son|wife|husband|sister|brother|"
    r"niece|nephew|friend)\s+(?P<name>[A-Z][a-z]+)",
)
_ROUTINE = re.compile(
    r"\b(?:every (?:morning|evening|afternoon|night|day)|always)\b", re.IGNORECASE
)
_CONFIDENCE = 0.7


class RuleFactExtractor:
    def extract(
        self, transcript: Sequence[Turn], known_facts: Sequence[str] = ()
    ) -> list[CandidateFact]:
        out: list[CandidateFact] = []
        for turn in transcript:
            if turn.speaker != "resident":
                continue
            for raw in _SENTENCE.findall(turn.text):
                sentence = raw.strip()
                if not sentence or sentence.endswith("?"):
                    continue
                out.extend(self._from_sentence(sentence.rstrip(".!")))
        return out

    @staticmethod
    def _fact(
        kind: FactKind, text: str, quote: str, subject: Subject = Subject.RESIDENT
    ) -> CandidateFact:
        return CandidateFact(
            kind=kind,
            text=text,
            quote=quote,
            speaker="resident",
            subject=subject,
            confidence=_CONFIDENCE,
        )

    def _from_sentence(self, sentence: str) -> list[CandidateFact]:
        found: list[CandidateFact] = []
        if m := _DISLIKE.search(sentence):
            found.append(self._fact(FactKind.DISLIKE, f"Dislikes {m['what'].strip()}", sentence))
        elif m := _LIKE.search(sentence):
            found.append(self._fact(FactKind.LIKE, f"Likes {m['what'].strip()}", sentence))
        if m := _PERSON.search(sentence):
            found.append(self._fact(FactKind.PERSON, sentence, sentence, Subject.OTHER))
        if _ROUTINE.search(sentence) and not found:
            found.append(self._fact(FactKind.ROUTINE, sentence, sentence))
        return found
