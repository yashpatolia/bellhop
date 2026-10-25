"""Run the news and trends Apify actors once and print what the robot's tools would say.

Usage (Mac or Pi): uv run python scripts/check_feeds.py   # about 2 cents of Apify credit
Success: a few stories and trends with titles and sources, then FEEDS OK. "no APIFY_TOKEN": add it
to ml/pi/.env. "Apify answered 401": the token is wrong. "402": the Apify account is out of credit.
Empty fields: the actor changed its output; update KEEP in rover/agent/feeds.py.
"""

import os
import sys
import time

from rover.agent import feeds


def main() -> None:
    token = os.environ.get("APIFY_TOKEN", "")
    if not token:
        sys.exit("no APIFY_TOKEN in ml/pi/.env")
    ok = True
    for name in ("news", "trends"):
        started = time.monotonic()
        try:
            count = feeds.refresh(name, token)
        except Exception as exc:  # noqa: BLE001 - print the reason and check the other feed
            print(f"{name}: failed ({feeds.why_failed(exc)})")
            ok = False
            continue
        print(f"{name}: {count} items in {time.monotonic() - started:.0f} s")
        print(feeds.tool_text(name), "\n")
    print("FEEDS OK" if ok else "FEEDS FAILED")


if __name__ == "__main__":
    main()
