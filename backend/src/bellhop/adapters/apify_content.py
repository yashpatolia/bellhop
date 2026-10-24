"""Apify-backed content feed with a local fallback.

Runs an Apify actor synchronously over the REST API. A missing token, HTTP error, timeout,
malformed body or empty dataset all degrade to the wrapped `ContentFeed`. The token is sent
only in the Authorization header and is never logged.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from bellhop.ports.content import ContentFeed, ContentItem

log = logging.getLogger(__name__)

_BASE_URL = "https://api.apify.com"
_BLURB_MAX = 200


def map_item(raw: dict[str, Any], year: int, index: int) -> ContentItem | None:
    """Map one Apify dataset item to a ContentItem; None when unusable."""
    meta = raw.get("metadata")
    title = raw.get("title") or (meta.get("title") if isinstance(meta, dict) else None)
    text = raw.get("blurb") or raw.get("text") or raw.get("description")
    if not isinstance(title, str) or not title.strip() or not isinstance(text, str):
        return None
    blurb = " ".join(text.split())[:_BLURB_MAX]
    if not blurb:
        return None
    return ContentItem(
        id=f"apify-{year}-{index}", kind="event", year=year, title=title.strip(), blurb=blurb
    )


class ApifyContentFeed:
    def __init__(
        self,
        fallback: ContentFeed,
        token: str | None,
        actor: str = "apify~website-content-crawler",
        timeout: float = 5.0,
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
        mapped = (map_item(r, year, i) for i, r in enumerate(data) if isinstance(r, dict))
        return [m for m in mapped if m is not None]
