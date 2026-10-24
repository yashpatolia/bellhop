import httpx

from bellhop.adapters.apify_content import ApifyContentFeed, map_item
from bellhop.ports.content import ContentItem

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
    return httpx.Response(
        200,
        json=[
            {"title": "Rock Around the Clock", "text": "A hit record. " * 30, "year": 1955},
            {"metadata": {"title": "Peter Pan opens"}, "text": "Short blurb."},
            {"url": "no title or text"},
        ],
    )


def test_success_maps_items():
    feed, fb, calls = make(ok)
    items = feed.for_era(1935, limit=5)
    assert [i.title for i in items] == ["Rock Around the Clock", "Peter Pan opens"]
    assert all(isinstance(i, ContentItem) for i in items)
    assert len(items[0].blurb) <= 200
    assert fb.calls == 0
    req = calls[0]
    assert "/v2/acts/user~actor/run-sync-get-dataset-items" in req.url.path
    assert req.headers["authorization"] == "Bearer secret-token"


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


def test_map_item_skips_unusable():
    assert map_item({}, 1955, 0) is None
    item = map_item({"title": "T", "text": "B"}, 1955, 3)
    assert item is not None and item.year == 1955 and item.id == "apify-1955-3"
