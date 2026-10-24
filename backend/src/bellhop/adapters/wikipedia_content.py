"""Wikipedia-backed content feed: era facts fetched directly, parsed, cached, with a fallback.

Reads the "{year} in music" page through the MediaWiki action API (free, about 1-2 s) and runs
the same `era_parser` as the Apify adapter. Intended for ingest time or lazily on the first
request per year; results are cached in memory (failures too, so a dead network costs one
timeout per year, not one per call). A timeout, HTTP error, malformed body or an empty parse
degrades to the wrapped `ContentFeed`. Wikimedia asks API clients to send a descriptive
User-Agent that names a contact.
"""

from __future__ import annotations

import logging
from itertools import zip_longest

import httpx

from bellhop.adapters.era_parser import html_to_markdown, parse_era
from bellhop.ports.content import ContentFeed, ContentItem

log = logging.getLogger(__name__)

_URL = "https://en.wikipedia.org/w/api.php"
# Wikimedia returns 403 to clients without contact info in the User-Agent (verified live).
USER_AGENT = "BellhopCareRobot/0.1 (https://github.com/yashpatolia/calhacks-13; calhacks prototype)"
_AGES = (20, 17, 23)  # sampled ages within 15-25, most formative first


class WikipediaContentFeed:
    def __init__(
        self,
        fallback: ContentFeed,
        timeout: float = 3.0,
        transport: httpx.BaseTransport | None = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        self._user_agent = user_agent
        self._fallback = fallback
        self._timeout = timeout
        self._transport = transport
        self._cache: dict[int, list[ContentItem]] = {}

    def for_era(self, birth_year: int, limit: int = 5) -> list[ContentItem]:
        per_year: list[list[ContentItem]] = []
        for age in _AGES:
            year = birth_year + age
            if year not in self._cache:
                self._cache[year] = self._load(year)
            if not self._cache[year]:
                break  # one failure is enough: do not stack timeouts in a row
            per_year.append(self._cache[year])
        merged = [i for row in zip_longest(*per_year) for i in row if i is not None]
        if not merged:
            return self._fallback.for_era(birth_year, limit)
        return merged[: max(limit, 0)]

    def _load(self, year: int) -> list[ContentItem]:
        try:
            return parse_era(html_to_markdown(self._fetch(year)), year, id_prefix="wiki")
        except Exception as exc:  # never break the demo
            log.warning("wikipedia content failed (%s); using fallback", type(exc).__name__)
            return []

    def _fetch(self, year: int) -> str:
        params = {
            "action": "parse",
            "page": f"{year}_in_music",
            "prop": "text",
            "format": "json",
            "formatversion": "2",
            "redirects": "1",
            "disabletoc": "1",
            "disableeditsection": "1",
        }
        with httpx.Client(
            timeout=self._timeout,
            transport=self._transport,
            headers={"User-Agent": self._user_agent},
        ) as client:
            resp = client.get(_URL, params=params)
            resp.raise_for_status()
            return resp.json()["parse"]["text"]
