"""In-memory repositories. Snapshots are stored and copies returned (mutate, then save).

The six repository ports share method names with different return types (`get`,
`list_all`, `for_call`), so one class cannot satisfy them all. `InMemoryStore` is a
facade that exposes one port-conforming repository per aggregate.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

from bellhop.domain import Alert, Call, CallStatus, Nurse, Resident, Robot, Visit

M = TypeVar("M", bound=BaseModel)


class _Table(Generic[M]):  # noqa: UP046
    def __init__(self) -> None:
        self._items: dict[str, M] = {}

    def save(self, item: M) -> None:
        self._items[item.id] = item.model_copy(deep=True)  # type: ignore[attr-defined]

    def get(self, item_id: str) -> M | None:
        item = self._items.get(item_id)
        return item.model_copy(deep=True) if item else None

    def list_all(self) -> list[M]:
        return [i.model_copy(deep=True) for i in list(self._items.values())]


class _Calls(_Table[Call]):
    def list_open(self) -> list[Call]:
        done = {CallStatus.RESOLVED, CallStatus.CLOSED}
        return [c for c in self.list_all() if c.status not in done]


class _Residents(_Table[Resident]):
    def by_room(self, room: str) -> Resident | None:
        return next((r for r in self.list_all() if r.room == room), None)


class _Nurses(_Table[Nurse]):
    def list_on_shift(self) -> list[Nurse]:
        return [n for n in self.list_all() if n.on_shift]


class _Visits(_Table[Visit]):
    def for_call(self, call_id: str) -> Visit | None:
        return next((v for v in self.list_all() if v.call_id == call_id), None)


class _Alerts(_Table[Alert]):
    def for_call(self, call_id: str) -> list[Alert]:
        return [a for a in self.list_all() if a.call_id == call_id]


class InMemoryStore:
    def __init__(self) -> None:
        self.calls = _Calls()
        self.residents = _Residents()
        self.nurses = _Nurses()
        self.robots: _Table[Robot] = _Table()
        self.visits = _Visits()
        self.alerts = _Alerts()
