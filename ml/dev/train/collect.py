"""(1) Collect public text. Dev only; never shipped to the Pi.

    cd ml/pi && uv run --group train python ../dev/train/collect.py apify [--dry-run]
    cd ml/pi && uv run --group train python ../dev/train/collect.py hf

apify: public subreddit posts through the Apify actor trudax/reddit-scraper-lite (pay per result).
       APIFY_TOKEN comes from ml/dev/.env or the environment and is never printed or stored.
       Each run has a max charge; the spend is written to data/collect_log.json.
hf:    empathetic_dialogues_llm (Apache-2.0), first speaker turns for chat and emotion phrasing.

Output: data/candidates.jsonl rows {id, source, text}. No usernames, URLs or post links are kept.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from train import textprep  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
ACTOR = "trudax/reddit-scraper-lite"
HF_DATASET = "Estwld/empathetic_dialogues_llm"
MAX_RUN_USD = Decimal("2.0")

# community, search terms, max items. About 1500 posts in all, roughly $6.
REDDIT_RUNS = [
    (
        "AgingParents",
        ["fell", "chest pain", "can't breathe", "confused", "medication", "dizzy"],
        90,
    ),
    ("AskDocs", ["chest pain", "short of breath", "dizzy", "fainted", "numbness", "nausea"], 90),
    ("dementia", ["fell", "confused", "pain", "medication", "hospital"], 90),
    ("lonely", ["tea", "talk", "company", "memories"], 90),
    ("CasualConversation", ["weather", "garden", "music", "grandchildren"], 90),
]  # the actor is slow (about 4 posts a minute), so the runs go in parallel; about $2 in all


def post_to_rows(item: dict, source: str) -> list[dict]:
    """A scraped post becomes one row per sentence: title and body, cleaned, nothing personal."""
    post_id = hashlib.sha1(str(item.get("id", "")).encode()).hexdigest()[:8]
    community = str(item.get("parsedCommunityName") or "")
    text = f"{item.get('title', '')}. {item.get('body', '')}"
    return [
        {"id": f"{source}-{post_id}-{i}", "source": f"{source}:{community}", "text": chunk}
        for i, chunk in enumerate(textprep.to_chunks(text))
    ]


def run_apify(dry_run: bool) -> None:
    from apify_client import ApifyClient
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    token = os.environ.get("APIFY_TOKEN", "").strip()
    if not token:
        sys.exit("APIFY_TOKEN is not set (ml/dev/.env or the environment)")
    if dry_run:
        for community, terms, limit in REDDIT_RUNS:
            print(f"would run {ACTOR} r/{community} {terms} maxItems {limit}")
        return
    client = ApifyClient(token)
    started = []
    for community, terms, limit in REDDIT_RUNS:
        run = client.actor(ACTOR).start(
            run_input={
                "searches": terms,
                "searchCommunityName": community,
                "searchPosts": True,
                "skipComments": True,
                "skipUserPosts": True,
                "skipCommunity": True,
                "includeNSFW": False,
                "maxItems": limit,
                "maxPostCount": limit,
                "sort": "relevance",
                "proxy": {"useApifyProxy": True, "apifyProxyGroups": ["RESIDENTIAL"]},
            },
            max_total_charge_usd=MAX_RUN_USD,
            run_timeout=timedelta(minutes=20),
        )
        started.append((community, run))
    rows, log = [], []
    for community, run in started:
        run = client.run(run.id).wait_for_finish()  # returns when the run ends or times out
        items = list(client.dataset(run.default_dataset_id).iterate_items())
        new = [r for item in items for r in post_to_rows(item, "reddit")]
        rows += new
        cost = float(run.usage_total_usd or 0)
        log.append(
            {"community": community, "status": str(run.status), "posts": len(items),
             "rows": len(new), "usd": cost}
        )  # fmt: skip
        print(f"r/{community}: {run.status} {len(items)} posts, {len(new)} sentences, ${cost:.3f}")
    DATA.mkdir(exist_ok=True)
    (DATA / "collect_log.json").write_text(json.dumps({"apify": log}, indent=1))
    merge_candidates(rows)


def run_hf() -> None:
    import polars as pl
    from huggingface_hub import hf_hub_download

    path = hf_hub_download(HF_DATASET, "data/train-00000-of-00001.parquet", repo_type="dataset")
    frame = pl.read_parquet(path)
    rows = []
    for conv_id, turns in zip(frame["conv_id"], frame["conversations"], strict=True):
        first = next((t["content"] for t in turns if t["role"] == "user"), "")
        for i, chunk in enumerate(textprep.to_chunks(first, min_words=4, max_chars=160)[:1]):
            rows.append({"id": f"hf-{conv_id}-{i}", "source": "hf:empathetic", "text": chunk})
    print(f"hf: {len(rows)} sentences from {len(frame)} conversations")
    merge_candidates(rows)


def merge_candidates(rows: list[dict]) -> None:
    path = DATA / "candidates.jsonl"
    old = textprep.read_jsonl(path) if path.exists() else []
    merged = textprep.dedupe(old + rows)
    textprep.write_jsonl(path, merged)
    print(f"candidates.jsonl: {len(merged)} rows")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", choices=["apify", "hf"])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    run_apify(args.dry_run) if args.source == "apify" else run_hf()
    return 0


if __name__ == "__main__":
    sys.exit(main())
