import json
import time

import httpx
import pytest

from rover import config
from rover.agent import feeds

NEWS = [
    {"title": "Library reopens", "source": "Local Times", "description": "Doors open at nine."},
    {"title": "", "source": "No title, so dropped"},
    {"title": "Team wins - Sports Daily", "source": "Sports Daily", "image": "not kept"},
    {"title": "Team wins - Sports Daily", "source": "Sports Daily"},
]


@pytest.fixture(autouse=True)
def runs(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    monkeypatch.setenv("APIFY_TOKEN", "token-123")
    return tmp_path


def apify(rows, status=201, seen=None):
    def handle(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=rows)

    return httpx.MockTransport(handle)


def test_a_refresh_runs_the_actor_and_caches_the_kept_fields(runs):
    seen = []
    assert feeds.refresh("news", "token-123", apify(NEWS, seen=seen)) == 2
    request = seen[0]
    assert (
        request.url.path
        == "/v2/acts/data_xplorer~google-news-scraper-fast/run-sync-get-dataset-items"
    )
    assert request.url.params["maxTotalChargeUsd"] == str(config.APIFY_MAX_CHARGE_USD)
    assert request.headers["Authorization"] == "Bearer token-123"  # never in the URL
    assert "token-123" not in str(request.url)
    assert json.loads(request.content) == config.FEEDS["news"]["input"]
    cached = json.loads((runs / "news.json").read_text())
    assert [item["title"] for item in cached["items"]] == ["Library reopens", "Team wins"]
    assert "image" not in cached["items"][1]


def test_a_feed_is_due_with_no_cache_or_an_old_one(runs):
    now = time.time()
    assert feeds.due("trends", now)
    (runs / "trends.json").write_text(json.dumps({"at": now - 60, "items": [{"term": "x"}]}))
    assert not feeds.due("trends", now)
    assert feeds.due("trends", now + config.FEEDS["trends"]["every_s"])


def test_a_failed_run_keeps_the_old_cache_and_waits_before_trying_again(runs, monkeypatch, capsys):
    old = {"at": 0, "items": [{"title": "Old story"}]}
    (runs / "news.json").write_text(json.dumps(old))
    with pytest.raises(httpx.HTTPStatusError):
        feeds.refresh("news", "t", apify({"error": {}}, status=402))
    assert json.loads((runs / "news.json").read_text()) == old
    with pytest.raises(ValueError):
        feeds.refresh("news", "t", apify([]))  # nothing came back: keep what we had
    assert json.loads((runs / "news.json").read_text()) == old

    calls = []

    def failing(name, token):
        calls.append(name)
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(feeds, "refresh", failing)
    retry_at: dict[str, float] = {}
    now = time.time()  # the old cache is long overdue
    feeds.refresh_due("t", retry_at, now)
    assert sorted(calls) == ["news", "trends"]
    assert "fallback: news refresh failed (ConnectError: offline)" in capsys.readouterr().out
    feeds.refresh_due("t", retry_at, now + config.FEED_RETRY_S - 1)
    assert len(calls) == 2  # not hammered while it is down


def test_no_token_turns_the_feeds_off(monkeypatch, capsys):
    monkeypatch.delenv("APIFY_TOKEN")
    assert feeds.start() is None
    assert "fallback: no APIFY_TOKEN" in capsys.readouterr().out
    assert "use web_search" in feeds.tool_text("news")


def test_the_tools_answer_from_the_cache(runs):
    assert feeds.tool_text("news").startswith("still fetching the latest news")
    feeds.refresh("news", "t", apify(NEWS))
    text = feeds.tool_text("news", now=time.time() + 25 * 60)
    assert text.startswith("Top stories, fetched 25 minutes ago:")
    assert "- Library reopens (Local Times): Doors open at nine." in text
    trends = [
        {
            "term": "Eclipse",
            "category": "Science",
            "trend_volume": "2M+",
            "related_terms": ["eclipse time", "eclipse glasses", "path", "extra"],
        }
    ]
    feeds.refresh("trends", "t", apify(trends))
    line = "- Eclipse (Science; 2M+ searches; related: eclipse time, eclipse glasses, path)"
    assert line in feeds.tool_text("trends")
