"""Reminiscence content port: era-appropriate songs, films, news and events."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel

ContentKind = Literal["song", "film", "news", "event"]


class ContentItem(BaseModel):
    id: str
    kind: ContentKind
    year: int
    title: str
    blurb: str


class ContentFeed(Protocol):
    def for_era(self, birth_year: int, limit: int = 5) -> list[ContentItem]:
        """Items from the resident's youth (roughly ages 15-25), deterministic order."""
        ...
