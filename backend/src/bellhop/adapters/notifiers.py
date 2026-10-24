"""Notifier adapters: an in-memory recorder and a fan-out composite."""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from bellhop.domain import Alert
from bellhop.ports import Notifier

log = logging.getLogger(__name__)


class BoundedLog(deque[Any]):
    """Newest-1000 record that still compares equal to a plain list (tests, `== []`)."""

    def __init__(self) -> None:
        super().__init__(maxlen=1000)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, list):
            return list(self) == other
        return super().__eq__(other)

    __hash__ = None  # type: ignore[assignment]


class RecordingNotifier:
    """Keeps the most recent 1000 alerts sent to it (dashboard feed and tests)."""

    def __init__(self) -> None:
        self.sent: BoundedLog = BoundedLog()

    def send(self, alert: Alert) -> None:
        self.sent.append(alert)


class CompositeNotifier:
    """Sends to every channel; one failing channel does not stop the others."""

    def __init__(self, *notifiers: Notifier) -> None:
        self._notifiers = notifiers

    def send(self, alert: Alert) -> None:
        for notifier in self._notifiers:
            try:
                notifier.send(alert)
            except Exception:
                log.exception("notifier %r failed for alert %s", notifier, alert.id)
