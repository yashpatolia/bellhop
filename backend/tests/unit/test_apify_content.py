from pathlib import Path

import httpx

from bellhop.adapters.apify_content import ApifyContentFeed
from bellhop.ports.content import ContentItem

REAL_MD = (Path(__file__).resolve().parents[1] / "fixtures" / "1955_in_music.md").read_text()
FALLBACK_ITEM = ContentItem(id="f1", kind="song", year=1960, title="Fallback", blurb="local")


class FakeFallback:
    def __init__(self) -> None:
        self.calls = 0

    def for_era(self, birth_year: int, limit: int = 5) -> list[ContentItem]:
        self.calls += 1
        return [FALLBACK_ITEM]


def make(handler, token="secret-token"):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    fb = FakeFallback()
    feed = ApifyContentFeed(
        fb, token=token, actor="user~actor", transport=httpx.MockTransport(wrapped)
    )
    return feed, fb, calls


def ok(request):
    # Shape of the real actor output: one dataset item holding the whole page.
    return httpx.Response(
        200,
        json=[
            {
                "url": "https://en.wikipedia.org/wiki/1955_in_music",
                "text": "nav " * 50,
                "markdown": REAL_MD,
            }
        ],
    )


def test_success_parses_the_page_markdown_into_many_items():
    feed, fb, calls = make(ok)
    items = feed.for_era(1935, limit=5)
    assert len(items) == 5 and fb.calls == 0
    assert all(isinstance(i, ContentItem) and i.year == 1955 for i in items)
    assert all("Wikipedia" not in i.title + i.blurb and len(i.blurb) <= 200 for i in items)
    assert items[0].id.startswith("apify-1955-")
    req = calls[0]
    assert "/v2/acts/user~actor/run-sync-get-dataset-items" in req.url.path
    assert req.headers["authorization"] == "Bearer secret-token"


def test_default_timeout_allows_a_slow_crawl():
    assert ApifyContentFeed(FakeFallback(), token="t")._timeout == 60.0


def test_item_without_markdown_gives_nothing_and_falls_back():
    feed, _, _ = make(lambda r: httpx.Response(200, json=[{"url": "x", "text": "no bullets"}]))
    assert feed.for_era(1935) == [FALLBACK_ITEM]


def test_cache_means_one_http_call_per_birth_year():
    feed, _, calls = make(ok)
    feed.for_era(1935)
    feed.for_era(1935, limit=1)
    assert len(calls) == 1
    feed.for_era(1940)
    assert len(calls) == 2


def test_limit_respected_from_cache():
    feed, _, _ = make(ok)
    assert len(feed.for_era(1935, limit=1)) == 1


def test_timeout_falls_back():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    feed, fb, _ = make(boom)
    assert feed.for_era(1935) == [FALLBACK_ITEM]


def test_401_falls_back():
    feed, _, _ = make(lambda r: httpx.Response(401, json={"error": "nope"}))
    assert feed.for_era(1935) == [FALLBACK_ITEM]


def test_empty_results_fall_back():
    feed, _, _ = make(lambda r: httpx.Response(200, json=[]))
    assert feed.for_era(1935) == [FALLBACK_ITEM]


def test_malformed_body_falls_back():
    feed, _, _ = make(lambda r: httpx.Response(200, text="not json"))
    assert feed.for_era(1935) == [FALLBACK_ITEM]


def test_missing_token_falls_back_with_zero_http_calls():
    for token in (None, ""):
        feed, fb, calls = make(ok, token=token)
        assert feed.for_era(1935) == [FALLBACK_ITEM]
        assert calls == []
