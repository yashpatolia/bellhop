"""Small helpers the routes need beyond the existing services."""

from __future__ import annotations

from bellhop.adapters.system import SystemClock
from bellhop.container import Container
from bellhop.domain import Alert, Call, Urgency
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


class ResidentNotFound(LookupError):
    pass


def require_resident(container: Container, resident_id: str) -> str:
    if container.store.residents.get(resident_id) is None:
        raise ResidentNotFound(resident_id)
    return resident_id


def triage_score(
    container: Container,
    call_id: str,
    model_urgency: Urgency | None,
    category: str,
    summary: str | None,
    confidence: float | None,
) -> None:
    """Score a call through the deterministic safety net (never lowers the model's urgency)."""
    call = get_call(container, call_id)
    transcript = [(t.speaker, t.text) for t in call.transcript]
    decision = container.triage_guard.decide(transcript, model_urgency, confidence)
    if model_urgency is None or decision.urgency > model_urgency:
        summary = decision.reason if summary is None else f"{summary} ({decision.reason})"
    container.call_service.score(call_id, decision.urgency, category, summary)
