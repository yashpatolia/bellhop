"""Small helpers the routes need beyond the existing services."""

from __future__ import annotations

from bellhop.adapters.system import SystemClock
from bellhop.container import Container
from bellhop.domain import Alert, Call
from bellhop.services.call_service import CallNotFound


class AlertNotFound(LookupError):
    pass


def get_call(container: Container, call_id: str) -> Call:
    call = container.store.calls.get(call_id)
    if call is None:
        raise CallNotFound(call_id)
    return call


def ack_alert(container: Container, alert_id: str, nurse_id: str) -> Alert:
    alert = container.store.alerts.get(alert_id)
    if alert is None:
        raise AlertNotFound(alert_id)
    container.call_service.ack_by_nurse(alert.call_id, nurse_id)
    alert.acked_at = SystemClock().now()
    container.store.alerts.save(alert)
    return alert
