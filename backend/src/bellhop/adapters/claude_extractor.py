"""Extract candidate facts from a conversation with Claude, using structured outputs.

Runs after a visit, never inside the voice loop. The model only proposes; the
MemoryLearner checks every proposal against the transcript before anything is stored.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

import anthropic

from bellhop.domain import Turn
from bellhop.domain.learning import CandidateFact, ExtractedFacts

DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "high"
MODEL_ENV = "BELLHOP_EXTRACTOR_MODEL"

SYSTEM_PROMPT = """You help a care-home companion robot remember residents. You read one \
finished conversation and list the facts about the resident worth remembering, so the next \
visit can feel familiar. A wrong memory does more harm than a missing one, so be strict.

What to record: stable likes and dislikes, people in the resident's life (name, relationship, \
when they visit or call), daily routines, how the resident prefers to be spoken to, and \
important life events they chose to share.

Rules:
1. Use only what the resident (or nurse) actually said, never what the robot said or offered. \
If the resident did not confirm something the robot suggested, it is not a fact.
2. For every fact, copy the supporting words verbatim from a single turn into `quote`. \
Do not paraphrase the quote. `speaker` is who said it.
3. Do not record: wishes and hypotheticals ("I would love a dog"), jokes, sarcasm and idioms, \
one-off events (what they had for lunch today), declined offers, opinions that belong to \
other people, anything the resident seems confused about (who is coming, what time it is, \
where they are), diagnoses, medications, or numbers and identifiers.
4. Handle negation by recording what is true now ("No longer takes sugar"), never the opposite.
5. Use kind `health` for pain, symptoms, mobility and how the resident feels in their body. \
These are reviewed by a nurse before they are kept.
6. `text` is one short third-person sentence, for example "Likes tea with two sugars". \
Do not include the resident's own name. Keep family and friends' first names.
7. `subject` is `resident` for facts about them, `other` for facts about another person \
(only people facts about family and friends are kept).
8. `confidence` is your honest estimate that the fact is true and lasting: 0.9 or more only \
when stated plainly, 0.6 to 0.8 when stated once and clearly, below 0.5 when unsure.
9. Skip anything in the list of already-known facts.
10. An empty list is the right answer for small talk, accidental bell presses and any \
conversation with nothing reliable to remember. Prefer an empty list to a guess."""


def _render(transcript: Sequence[Turn], known_facts: Sequence[str]) -> str:
    lines = [f"{t.speaker}: {t.text}" for t in transcript]
    body = "Conversation:\n" + "\n".join(lines)
    if known_facts:
        body += "\n\nAlready known (do not repeat):\n" + "\n".join(f"- {f}" for f in known_facts)
    return body


class ClaudeFactExtractor:
    def __init__(
        self,
        client: Any | None = None,
        model: str | None = None,
        effort: str = DEFAULT_EFFORT,
        max_tokens: int = 4096,
    ) -> None:
        self._client = client if client is not None else anthropic.Anthropic()
        self._model = model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL
        self._effort = effort
        self._max_tokens = max_tokens

    def extract(
        self, transcript: Sequence[Turn], known_facts: Sequence[str] = ()
    ) -> list[CandidateFact]:
        response = self._client.messages.parse(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _render(transcript, known_facts)}],
            output_format=ExtractedFacts,
            output_config={"effort": self._effort},
        )
        parsed = response.parsed_output
        return list(parsed.facts) if parsed else []
