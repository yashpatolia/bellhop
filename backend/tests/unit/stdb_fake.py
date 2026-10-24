"""A fake SpacetimeDB HTTP server that behaves like the module in spacetimedb/src/index.ts.

Reducers upsert or delete rows in per-table dicts, and the SQL route reads them back, so a test
can write through one store, build a second store on the same server and check what comes back.
"""

from __future__ import annotations

import json

import httpx

from bellhop.adapters import spacetimedb_data as data
from bellhop.adapters import spacetimedb_store as core

UPSERT = {
    "save_call": "call",
    "save_resident": "resident",
    "save_nurse": "nurse",
    "save_robot": "robot",
    "save_alert": "alert",
    "save_visit": "visit",
    "save_memory_fact": "memory_fact",
    "save_pending_fact": "pending_fact",
    "save_care_entry": "care_entry",
    "save_flag": "flag",
    "save_preferences": "preferences",
    "save_family_message": "family_message",
    "save_family_delivery": "family_delivery",
    "save_medical_record": "medical_record",
}
DELETE = {"delete_memory_fact": "memory_fact", "delete_pending_fact": "pending_fact"}


def columns(table: str) -> tuple[str, ...]:
    if table == "call_turn":
        return core.TURN_COLUMNS
    return core.COLUMNS.get(table) or data.DATA_COLUMNS[table]


class FakeStdb:
    def __init__(self) -> None:
        self.tables: dict[str, dict[str, list]] = {}
        self.calls: list[tuple[str, list]] = []
        self.down = False
        self.missing: set[str] = set()  # tables an out of date module does not have

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down", request=request)
        path = request.url.path
        if "/call/" in path:
            reducer = path.rsplit("/", 1)[-1]
            args = json.loads(request.content)
            if reducer in UPSERT and UPSERT[reducer] in self.missing:
                return httpx.Response(404)
            self.calls.append((reducer, args))
            self._apply(reducer, args)
            return httpx.Response(200)
        if path.endswith("/sql"):
            table = request.content.decode().rsplit(" ", 1)[-1].strip().rstrip(";")
            if table in self.missing:
                return httpx.Response(404)
            return httpx.Response(200, json=[self._select(table)])
        return httpx.Response(404)

    def _apply(self, reducer: str, args: list) -> None:
        if reducer == "append_turn":
            call_id, seq, *rest = args
            self.tables.setdefault("call_turn", {})[f"{call_id}:{seq}"] = [
                f"{call_id}:{seq}", call_id, seq, *rest
            ]  # fmt: skip
        elif reducer in UPSERT:
            table = UPSERT[reducer]
            assert len(args) == len(columns(table)), (reducer, args)
            self.tables.setdefault(table, {})[args[0]] = args
        elif reducer in DELETE:
            self.tables.setdefault(DELETE[reducer], {}).pop(args[0], None)
        elif reducer == "delete_resident_memory":
            rows = self.tables.setdefault("memory_fact", {})
            for key in [k for k, row in rows.items() if row[1] == args[0]]:
                del rows[key]
        else:
            raise AssertionError(f"unknown reducer {reducer}")

    def _select(self, table: str) -> dict:
        return {
            "schema": {
                "elements": [
                    {"name": {"some": c}, "algebraic_type": {"String": []}} for c in columns(table)
                ]
            },
            "rows": list(self.tables.get(table, {}).values()),
        }
