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
    r"\b(?:every (?:morning|evening|afternoon|night|day)|always|usually"
    r"|(?:after|before) (?:breakfast|lunch|dinner|supper|tea|bed))\b",
    re.IGNORECASE,
)
# A routine is only about the resident when they are the one doing it ("I always ...").
# "He always comes home at six" or a fragment like "Stew, always stew" is not.
_SELF = re.compile(r"\bI\b")
_OTHER_SUBJECT = re.compile(r"^(?:he|she|they|we|it|you)\b", re.IGNORECASE)
# "Likes it" says nothing; the thing liked must be named.
_PRONOUN_OBJECT = re.compile(r"^(?:it|that|this|them|those|these)\b", re.IGNORECASE)
# "Oh yes, I just love being woken at five" is a complaint, not a like.
_SARCASM = re.compile(
    r"^(?:oh|yeah|well|sure)\b[^.]*\bI (?:just |really )?(?:love|adore|enjoy)", re.IGNORECASE
)
_CONFIDENCE = 0.7

# Rewriting "I always read the paper" as "Always reads the paper", so a nurse reads a fact
# about the resident. The resident's own words stay in the quote.
_LEAD = re.compile(
    r"^(?P<pre>.*?)\bI (?P<adv>(?:always |usually |often |never |just |really |still )?)"
    r"(?P<verb>[a-z]+)\b"
)
_AND_VERB = re.compile(
    r"\band (have|take|go|do|read|say|watch|drink|eat|walk|like|love|sleep|get|make|need|sit"
    r"|listen|play|pray|ring|call|visit|read)\b"
)
_KEEP = {"can", "will", "would", "should", "must", "could", "might", "may", "did", "was", "used"}
_IRREGULAR = {"am": "is", "have": "has", "do": "does", "go": "goes", "be": "is"}


def _third(verb: str) -> str:
    v = verb.lower()
    if v in _IRREGULAR:
        return _IRREGULAR[v]
    if v in _KEEP:
        return v
    if v.endswith(("s", "sh", "ch", "x", "z", "o")):
        return v + "es"
    if len(v) > 1 and v.endswith("y") and v[-2] not in "aeiou":
        return v[:-1] + "ies"
    return v + "s"


def _pronouns(text: str) -> str:
    text = re.sub(r"\b[Mm]yself\b", "themselves", text)
    text = re.sub(r"\b[Mm]y\b", "their", text)
    text = re.sub(r"\bme\b", "them", text)
    return re.sub(r"\bI\b", "they", text)


def _about_resident(sentence: str) -> str:
    """'I always say my prayers before bed' becomes 'Always says their prayers before bed'."""
    if m := _LEAD.match(sentence):
        sentence = f"{m['pre']}{m['adv']}{_third(m['verb'])}{sentence[m.end() :]}"
    sentence = _AND_VERB.sub(lambda v: f"and {_third(v[1])}", sentence)
    return _capital(_pronouns(sentence))


def _about_person(sentence: str) -> str:
    """'My grandson Mateo visits every Sunday' becomes 'Grandson Mateo visits every Sunday'."""
    return _capital(_pronouns(re.sub(r"^[Mm]y ", "", sentence)))


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:]


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
            what = m["what"].strip()
            if not _PRONOUN_OBJECT.match(what):
                found.append(self._fact(FactKind.DISLIKE, f"Dislikes {_pronouns(what)}", sentence))
        elif (m := _LIKE.search(sentence)) and not _SARCASM.search(sentence):
            what = m["what"].strip()
            if not _PRONOUN_OBJECT.match(what):
                found.append(self._fact(FactKind.LIKE, f"Likes {_pronouns(what)}", sentence))
        if _PERSON.search(sentence):
            found.append(
                self._fact(FactKind.PERSON, _about_person(sentence), sentence, Subject.OTHER)
            )
        if (
            not found
            and _ROUTINE.search(sentence)
            and _SELF.search(sentence)
            and not _OTHER_SUBJECT.match(sentence)
            and not _SARCASM.search(sentence)
        ):
            found.append(self._fact(FactKind.ROUTINE, _about_resident(sentence), sentence))
        return found
