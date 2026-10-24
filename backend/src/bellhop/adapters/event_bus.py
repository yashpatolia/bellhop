"""Synchronous in-process event bus."""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from bellhop.ports import Handler

log = logging.getLogger(__name__)


class InMemoryEventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    def publish(self, event: Any) -> None:
        for handler in list(self._handlers[type(event)]):
            try:
                handler(event)
            except Exception:
                log.exception("handler failed for %s", type(event).__name__)
