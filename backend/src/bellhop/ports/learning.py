"""Port for turning a finished conversation into candidate facts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from bellhop.domain import Turn
from bellhop.domain.learning import CandidateFact


class FactExtractor(Protocol):
    """Reads a (scrubbed) transcript and proposes facts, each with a supporting quote."""

    def extract(
        self, transcript: Sequence[Turn], known_facts: Sequence[str] = ()
    ) -> list[CandidateFact]: ...
