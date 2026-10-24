"""Apify-backed content feed with a local fallback. OPTIONAL: ingest-time (pre-warm) use only.

Runs an Apify actor synchronously over the REST API. The website-content-crawler actor takes
about 12 s for one Wikipedia page and returns ONE dataset item holding the whole page, so the
item's `markdown` goes through `era_parser` (the same parser as `WikipediaContentFeed`, which
fetches the page directly, free and in about a second). Never put this inside the voice loop:
call it from an ingest job or pre-warm step so the cache is hot. A missing token, HTTP error,
timeout, malformed body or empty parse all degrade to the wrapped `ContentFeed`. The token is
sent only in the Authorization header and is never logged.
"""

from __future__ import annotations

import logging

import httpx

from bellhop.adapters.era_parser import parse_era
from bellhop.ports.content import ContentFeed, ContentItem

log = logging.getLogger(__name__)

_BASE_URL = "https://api.apify.com"


class ApifyContentFeed:
    def __init__(
        self,
        fallback: ContentFeed,
        token: str | None,
        actor: str = "apify~website-content-crawler",
        timeout: float = 60.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._fallback = fallback
        self._token = token
        self._actor = actor
        self._timeout = timeout
        self._transport = transport
        self._cache: dict[int, list[ContentItem]] = {}

    def for_era(self, birth_year: int, limit: int = 5) -> list[ContentItem]:
        if not self._token:
            return self._fallback.for_era(birth_year, limit)
        if birth_year not in self._cache:
            try:
                self._cache[birth_year] = self._fetch(birth_year)
            except Exception as exc:  # never break the demo
                log.warning("apify content failed (%s); using fallback", type(exc).__name__)
                self._cache[birth_year] = []
        items = self._cache[birth_year]
        if not items:
            return self._fallback.for_era(birth_year, limit)
        return items[: max(limit, 0)]

    def _fetch(self, birth_year: int) -> list[ContentItem]:
        year = birth_year + 20
        body = {
            "startUrls": [{"url": f"https://en.wikipedia.org/wiki/{year}_in_music"}],
            "maxCrawlPages": 1,
        }
        with httpx.Client(
            base_url=_BASE_URL, timeout=self._timeout, transport=self._transport
        ) as client:
            resp = client.post(
                f"/v2/acts/{self._actor}/run-sync-get-dataset-items",
                json=body,
                headers={"Authorization": f"Bearer {self._token}"},
            )
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, list):
            return []
        items: list[ContentItem] = []
        for raw in data:
            markdown = raw.get("markdown") if isinstance(raw, dict) else None
            if isinstance(markdown, str):
                items += parse_era(markdown, year, id_prefix="apify")
        return items
