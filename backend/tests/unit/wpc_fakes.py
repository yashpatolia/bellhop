"""Tiny local fakes satisfying the ports, for WP-C unit tests."""

from collections import defaultdict
from typing import Any

from bellhop.domain import Alert, Call, Nurse, Visit


class DictRepo:
    """Dict-backed repo covering the call, nurse, alert and visit ports."""

    def __init__(self) -> None:
        self.items: dict[str, Any] = {}

    def save(self, item: Any) -> None:
        self.items[item.id] = item.model_copy(deep=True)

    def get(self, item_id: str) -> Any:
        found = self.items.get(item_id)
        return found.model_copy(deep=True) if found else None

    def list_all(self) -> list[Any]:
        return [i.model_copy(deep=True) for i in self.items.values()]

    def list_open(self) -> list[Call]:
        return [c for c in self.list_all() if c.status not in ("resolved", "closed")]

    def list_on_shift(self) -> list[Nurse]:
        return [n for n in self.list_all() if n.on_shift]


class AlertRepo(DictRepo):
    def for_call(self, call_id: str) -> list[Alert]:
        return [a for a in self.list_all() if a.call_id == call_id]


class VisitRepo(DictRepo):
    def for_call(self, call_id: str) -> Visit | None:
        return next((v for v in self.list_all() if v.call_id == call_id), None)


class SyncBus:
    def __init__(self) -> None:
        self.handlers: dict[type, list] = defaultdict(list)
        self.published: list[Any] = []

    def subscribe(self, event_type: type, handler) -> None:
        self.handlers[event_type].append(handler)

    def publish(self, event: Any) -> None:
        self.published.append(event)
        for h in self.handlers[type(event)]:
            h(event)
