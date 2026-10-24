import json
from pathlib import Path

import httpx

from bellhop.adapters.wikipedia_content import WikipediaContentFeed
from bellhop.ports.content import ContentItem

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "1955_in_music_api.json"
FALLBACK_ITEM = ContentItem(id="f1", kind="song", year=1960, title="Fallback", blurb="local")


class FakeFallback:
    def __init__(self) -> None:
        self.calls = 0

    def for_era(self, birth_year: int, limit: int = 5) -> list[ContentItem]:
        self.calls += 1
        return [FALLBACK_ITEM]


def make(handler):
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    fb = FakeFallback()
    feed = WikipediaContentFeed(fb, transport=httpx.MockTransport(wrapped))
    return feed, fb, calls


def page(request: httpx.Request) -> httpx.Response:
    year = request.url.params["page"].split("_")[0]
    body = json.loads(FIXTURE.read_text())
    body["parse"]["text"] = body["parse"]["text"].replace("1955", year)
    return httpx.Response(200, json=body)


def test_fetches_the_action_api_with_a_descriptive_user_agent():
    feed, fb, calls = make(page)
    items = feed.for_era(1935, limit=5)
    assert len(items) == 5 and fb.calls == 0
    req = calls[0]
    assert req.url.host == "en.wikipedia.org" and req.url.path == "/w/api.php"
    params = req.url.params
    assert params["action"] == "parse" and params["prop"] == "text"
    assert params["format"] == "json" and params["page"] == "1955_in_music"
    assert "Bellhop" in req.headers["user-agent"]


def test_samples_up_to_three_years_in_the_residents_youth_one_fetch_each():
    feed, _, calls = make(page)
    items = feed.for_era(1935, limit=9)
    pages = [c.url.params["page"] for c in calls]
    assert len(pages) == 3 and len(set(pages)) == 3
    assert all(1935 + 15 <= int(p[:4]) <= 1935 + 25 for p in pages)
    assert len({i.year for i in items}) == 3


def test_results_are_cached_per_year():
    feed, _, calls = make(page)
    feed.for_era(1935)
    feed.for_era(1935, limit=1)
    assert len(calls) == 3
    feed.for_era(1938)  # years 1958 and 1955 are already cached, only 1961 is new
    assert len(calls) == 4


def test_limit_is_respected_and_never_negative():
    feed, _, _ = make(page)
    assert len(feed.for_era(1935, limit=2)) == 2
    assert feed.for_era(1935, limit=0) == []


def test_timeout_falls_back_and_stops_after_the_first_failure():
    def boom(request):
        raise httpx.ReadTimeout("slow", request=request)

    feed, fb, calls = make(boom)
    assert feed.for_era(1935) == [FALLBACK_ITEM]
    assert len(calls) == 1


def test_http_error_malformed_and_missing_page_fall_back():
    for handler in (
        lambda r: httpx.Response(503),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: httpx.Response(200, json={"error": {"code": "missingtitle"}}),
        lambda r: httpx.Response(200, json={"parse": {"text": "<p>no lists here</p>"}}),
    ):
        feed, _, _ = make(handler)
        assert feed.for_era(1935) == [FALLBACK_ITEM]


def test_one_good_year_is_enough_when_others_fail():
    def flaky(request):
        if request.url.params["page"].startswith("1955"):
            return page(request)
        return httpx.Response(503)

    feed, fb, _ = make(flaky)
    items = feed.for_era(1935, limit=3)
    assert items and all(i.year == 1955 for i in items) and fb.calls == 0
