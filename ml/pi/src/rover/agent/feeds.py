"""News and trends from Apify, refreshed in the background into runs/<feed>.json.

An Apify run takes seconds to a minute, so the news and trends tools only read the cache and
answer at once. The token goes in the Authorization header only and is never printed.
"""

from __future__ import annotations

import json
import os
import threading
import time

import httpx

from rover import config

KEEP = {  # the fields kept from each Apify item; the first one must be there
    "news": ("title", "source", "description", "publishedAt"),
    "trends": ("term", "category", "trend_volume", "related_terms"),
}
HEADS = {"news": "Top stories", "trends": "Trending in US Google searches over the last day"}


def cache_path(name: str):
    return config.RUNS_DIR / f"{name}.json"


def load(name: str) -> dict | None:
    try:
        cached = json.loads(cache_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return cached if isinstance(cached, dict) and cached.get("items") else None


def due(name: str, now: float) -> bool:
    cached = load(name)
    return cached is None or now - float(cached.get("at", 0)) >= config.FEEDS[name]["every_s"]


def refresh(name: str, token: str, transport: httpx.BaseTransport | None = None) -> int:
    """One Apify run. The cache is replaced only when it brought items; returns how many."""
    feed = config.FEEDS[name]
    with httpx.Client(transport=transport, timeout=config.APIFY_TIMEOUT_S) as client:
        response = client.post(
            f"{config.APIFY_API}/acts/{feed['actor']}/run-sync-get-dataset-items",
            params={
                "timeout": config.APIFY_RUN_S,
                "maxTotalChargeUsd": config.APIFY_MAX_CHARGE_USD,
            },
            json=feed["input"],
            headers={"Authorization": f"Bearer {token.strip()}"},  # a pasted newline
        )
        response.raise_for_status()
        data = response.json()
    keep = KEEP[name]
    rows = data if isinstance(data, list) else []
    items = [{k: raw[k] for k in keep if raw.get(k)} for raw in rows if isinstance(raw, dict)]
    items = [_tidy(item) for item in items if keep[0] in item]
    items = list({item[keep[0]]: item for item in items}.values())  # the same story twice
    if not items:
        raise ValueError("the run brought no items")
    path = cache_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"at": time.time(), "items": items}), encoding="utf-8")
    os.replace(temp, path)  # a reader never sees half a file
    return len(items)


def _tidy(item: dict) -> dict:
    """Google News titles end in " - <source>", which the line already says."""
    suffix = f" - {item.get('source')}"
    if "title" in item and item["title"].endswith(suffix):
        item["title"] = item["title"][: -len(suffix)]
    return item


def why_failed(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"Apify answered {exc.response.status_code}"
    if isinstance(exc, httpx.LocalProtocolError):  # its message can hold the header: the token
        return "the token has characters a header cannot hold"
    return f"{type(exc).__name__}: {exc}"


def refresh_due(token: str, retry_at: dict[str, float], now: float) -> None:
    """Run each feed that has no cache or an old one; a failure waits FEED_RETRY_S."""
    for name in config.FEEDS:
        if now < retry_at.get(name, 0.0) or not due(name, now):
            continue
        try:
            print(f"feeds: {name} refreshed ({refresh(name, token)} items)")
        except Exception as exc:
            retry_at[name] = now + config.FEED_RETRY_S
            wait = f"next try in {config.FEED_RETRY_S:g} s"
            print(f"fallback: {name} refresh failed ({why_failed(exc)}); {wait}")


def start() -> threading.Thread | None:
    """At start-up a feed with no cache (or an old one) runs at once, then each when it is due."""
    token = os.environ.get("APIFY_TOKEN", "")
    if not token:
        print("fallback: no APIFY_TOKEN; news and trends are off")
        return None

    def loop() -> None:
        retry_at: dict[str, float] = {}
        while True:
            refresh_due(token, retry_at, time.time())
            time.sleep(config.FEED_CHECK_S)

    thread = threading.Thread(target=loop, daemon=True, name="feeds")
    thread.start()
    return thread


def _ago(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 2:
        return "just now"
    if minutes < 90:
        return f"{minutes} minutes ago"
    hours = round(minutes / 60)
    return f"{hours} hours ago" if hours < 36 else f"{round(hours / 24)} days ago"


def _line(name: str, item: dict) -> str:
    if name == "news":
        line = item["title"] + (f" ({item['source']})" if item.get("source") else "")
        description = str(item.get("description") or "")[: config.FEED_DESCRIPTION_CHARS]
        return f"{line}: {description}" if description else line
    details = [str(item[k]) for k in ("category",) if item.get(k)]
    if item.get("trend_volume"):
        details.append(f"{item['trend_volume']} searches")
    related = [str(term) for term in (item.get("related_terms") or [])[:3]]
    if related:
        details.append("related: " + ", ".join(related))
    return item["term"] + (f" ({'; '.join(details)})" if details else "")


def tool_text(name: str, now: float | None = None) -> str:
    """The news or trends tool's answer, from the cache."""
    cached = load(name)
    if cached is None:
        if not os.environ.get("APIFY_TOKEN"):
            return f"{name} is not available (no Apify key); use web_search instead"
        return f"still fetching the latest {name}; use web_search for now"
    age = _ago((time.time() if now is None else now) - float(cached.get("at", 0)))
    lines = "\n".join(f"- {_line(name, item)}" for item in cached["items"])
    return f"{HEADS[name]}, fetched {age}:\n{lines}"
