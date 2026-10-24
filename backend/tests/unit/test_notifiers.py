from datetime import UTC, datetime

from bellhop.adapters.notifiers import CompositeNotifier, RecordingNotifier
from bellhop.domain import Alert, Urgency


def make_alert(alert_id: str = "a1") -> Alert:
    return Alert(
        id=alert_id,
        call_id="c1",
        nurse_id=None,
        level=Urgency.EMERGENCY,
        message="m",
        created_at=datetime(2026, 10, 24, tzinfo=UTC),
    )


def test_recording_notifier_keeps_sent_alerts_in_order():
    n = RecordingNotifier()
    n.send(make_alert("a1"))
    n.send(make_alert("a2"))
    assert [a.id for a in n.sent] == ["a1", "a2"]


def test_composite_forwards_to_every_notifier():
    a, b = RecordingNotifier(), RecordingNotifier()
    CompositeNotifier(a, b).send(make_alert())
    assert len(a.sent) == len(b.sent) == 1


def test_composite_failing_channel_does_not_stop_others():
    class Boom:
        def send(self, alert: Alert) -> None:
            raise RuntimeError("down")

    ok = RecordingNotifier()
    CompositeNotifier(Boom(), ok).send(make_alert())
    assert len(ok.sent) == 1
