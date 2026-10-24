"""Merge rover JSON-lines logs (ROVER_LOG files) by time and filter them.

    python dev/tail.py /tmp/run/*.jsonl [--call call_3] [--component drive,speech] [--event backend]
                       [--since 12:00:00] [--json] [--follow]

Lines are those written by rover.obslog: {"t": epoch seconds, "component", "event", ...fields}.
--call keeps lines whose call_id matches; --component takes a comma list; --event is a substring.
--follow keeps reading new lines (Ctrl-C to stop). Lines that are not JSON are skipped, and a
half-written last line is picked up on the next pass.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path

SKIP_FIELDS = {"t", "component", "event", "pid"}


def parse_line(line: str) -> dict | None:
    try:
        row = json.loads(line)
    except ValueError:
        return None
    if not isinstance(row, dict) or not isinstance(row.get("t"), int | float):
        return None
    return row


def read_rows(paths: Iterable[Path]) -> list[dict]:
    rows = []
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            print(f"tail: cannot read {path}: {exc}", file=sys.stderr)
            continue
        for line in text.splitlines():
            row = parse_line(line)
            if row is not None:
                rows.append(row)
    return rows


def matches(
    row: dict,
    call: str | None = None,
    components: set[str] | None = None,
    event: str | None = None,
    since: float | None = None,
) -> bool:
    if call is not None and row.get("call_id") != call:
        return False
    if components and row.get("component") not in components:
        return False
    if event and event not in str(row.get("event", "")):
        return False
    return since is None or row["t"] >= since


def merge(
    paths: Iterable[Path],
    call: str | None = None,
    components: set[str] | None = None,
    event: str | None = None,
    since: float | None = None,
) -> list[dict]:
    rows = [r for r in read_rows(paths) if matches(r, call, components, event, since)]
    rows.sort(key=lambda r: r["t"])  # stable: equal times keep file order
    return rows


def parse_since(text: str, today: datetime | None = None) -> float:
    """Epoch seconds from 'HH:MM:SS' (today, local time) or a plain epoch number."""
    try:
        return float(text)
    except ValueError:
        pass
    now = today or datetime.now()
    clock = datetime.strptime(text, "%H:%M:%S").time()
    return datetime.combine(now.date(), clock).timestamp()


def format_row(row: dict) -> str:
    stamp = datetime.fromtimestamp(row["t"]).strftime("%H:%M:%S.%f")[:-3]
    fields = " ".join(f"{k}={_short(v)}" for k, v in row.items() if k not in SKIP_FIELDS)
    return f"{stamp} {row.get('component', '?'):<7} {row.get('event', '?'):<22} {fields}".rstrip()


def _short(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= 60 and " " not in text else json.dumps(text[:60])


def follow(paths: list[Path], **filters) -> Iterator[dict]:
    """Yield rows as files grow; each pass is sorted, passes are in time of arrival."""
    offsets: dict[Path, int] = {}
    pending: dict[Path, str] = {}
    while True:
        batch = []
        for path in paths:
            try:
                with path.open("rb") as handle:
                    handle.seek(offsets.get(path, 0))
                    chunk = handle.read()
                    offsets[path] = handle.tell()
            except OSError:
                continue
            text = pending.get(path, "") + chunk.decode("utf-8", errors="replace")
            *complete, rest = text.split("\n")
            pending[path] = rest
            for line in complete:
                row = parse_line(line)
                if row is not None and matches(row, **filters):
                    batch.append(row)
        yield from sorted(batch, key=lambda r: r["t"])
        time.sleep(0.3)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--call", help="only this call id")
    parser.add_argument("--component", help="comma list, e.g. drive,speech")
    parser.add_argument("--event", help="substring of the event name")
    parser.add_argument("--since", help="HH:MM:SS today (local) or epoch seconds")
    parser.add_argument("--json", action="store_true", help="print the raw lines")
    parser.add_argument("--follow", action="store_true")
    args = parser.parse_args(argv)
    filters = {
        "call": args.call,
        "components": set(args.component.split(",")) if args.component else None,
        "event": args.event,
        "since": parse_since(args.since) if args.since else None,
    }
    render = (lambda r: json.dumps(r, separators=(",", ":"))) if args.json else format_row
    try:
        rows = follow(args.files, **filters) if args.follow else merge(args.files, **filters)
        for row in rows:
            print(render(row), flush=True)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
