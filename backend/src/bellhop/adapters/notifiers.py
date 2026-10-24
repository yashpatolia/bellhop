"""Notifier adapters: an in-memory recorder and a fan-out composite."""

from __future__ import annotations

import logging

from bellhop.domain import Alert
from bellhop.ports import Notifier

log = logging.getLogger(__name__)


class RecordingNotifier:
    """Keeps every alert sent to it (dashboard feed and tests)."""

    def __init__(self) -> None:
        self.sent: list[Alert] = []

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
