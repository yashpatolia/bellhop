import logging
from dataclasses import dataclass

from bellhop.adapters.event_bus import InMemoryEventBus


@dataclass(frozen=True)
class Ping:
    n: int


@dataclass(frozen=True)
class Pong:
    n: int


def test_handlers_run_in_subscription_order():
    bus, seen = InMemoryEventBus(), []
    bus.subscribe(Ping, lambda e: seen.append("first"))
    bus.subscribe(Ping, lambda e: seen.append("second"))
    bus.publish(Ping(1))
    assert seen == ["first", "second"]


def test_only_matching_event_type_is_delivered():
    bus, seen = InMemoryEventBus(), []
    bus.subscribe(Ping, seen.append)
    bus.publish(Pong(1))
    assert seen == []


def test_failing_handler_is_logged_and_does_not_block_others(caplog):
    bus, seen = InMemoryEventBus(), []

    def boom(event):
        raise RuntimeError("bad handler")

    bus.subscribe(Ping, boom)
    bus.subscribe(Ping, seen.append)
    with caplog.at_level(logging.ERROR):
        bus.publish(Ping(1))
    assert seen == [Ping(1)]
    assert "bad handler" in caplog.text


def test_publish_with_no_subscribers_is_fine():
    InMemoryEventBus().publish(Ping(1))


def test_events_published_from_a_handler_are_delivered():
    bus, seen = InMemoryEventBus(), []
    bus.subscribe(Ping, lambda e: bus.publish(Pong(e.n)))
    bus.subscribe(Pong, seen.append)
    bus.publish(Ping(7))
    assert seen == [Pong(7)]
