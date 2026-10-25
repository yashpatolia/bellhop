import asyncio
import json
import threading

import pytest

from bellhop.adapters.event_bus import InMemoryEventBus
from bellhop.adapters.memory_store import InMemoryStore
from bellhop.api.events import EventStream, TooManyClients
from bellhop.domain.events import (
    AlertRaised,
    CallAssigned,
    CallRaised,
    CallResolved,
    CallScored,
    CallUpdated,
)
from bellhop.domain.models import Robot, RobotStatus, Urgency


def make(**kw) -> tuple[InMemoryEventBus, EventStream]:
    bus = InMemoryEventBus()
    return bus, EventStream(bus, InMemoryStore(), **kw)


def drain(client) -> list:
    out = []
    while (m := client.pop()) is not None:
        out.append(m)
    return out


def test_bus_events_fan_out_to_every_client_with_names_and_monotonic_ids():
    bus, stream = make()
    a, b = stream.connect(), stream.connect()
    bus.publish(CallRaised("c1", "12"))
    bus.publish(CallAssigned("c1", "robot_1", None))
    bus.publish(CallUpdated("c1"))
    bus.publish(CallScored("c1", Urgency.NURSE_SOON, "pain"))
    bus.publish(CallResolved("c1", True))
    bus.publish(AlertRaised("a1", "c1", Urgency.NURSE_SOON))
    names = [
        "call.raised",
        "call.assigned",
        "call.updated",
        "call.scored",
        "call.resolved",
        "alert.raised",
    ]
    for client in (a, b):
        got = drain(client)
        assert [m.name for m in got] == names
        assert [m.id for m in got] == sorted({m.id for m in got})
    assert drain(a) == [] and drain(b) == []


def test_event_ids_carry_only_ids_not_objects():
    bus, stream = make()
    client = stream.connect()
    bus.publish(CallScored("c1", Urgency.EMERGENCY, "fall"))
    (m,) = drain(client)
    assert m.ids == {"call_id": "c1", "urgency": 4, "category": "fall"}


def test_full_object_is_snapshotted_when_the_event_is_emitted():
    """A delayed SSE client must not receive a later robot state under an old event."""
    bus, store = InMemoryEventBus(), InMemoryStore()
    stream = EventStream(bus, store)
    store.robots.save(Robot(id="r1", status=RobotStatus.IDLE))
    client = stream.connect()

    stream.emit("robot.updated", {"robot_id": "r1"})
    store.robots.save(Robot(id="r1", status=RobotStatus.CHARGING))

    (message,) = drain(client)
    payload = json.loads(stream.frame(message).split("data: ", 1)[1])
    assert payload["robot"]["status"] == "idle"


def test_full_queue_drops_oldest_and_never_blocks():
    _, stream = make(queue_size=3)
    client = stream.connect()
    for i in range(10):
        stream.emit("robot.updated", {"robot_id": str(i)})
    got = drain(client)
    assert [m.ids["robot_id"] for m in got] == ["7", "8", "9"]


def test_client_cap_raises_and_disconnect_frees_a_slot():
    _, stream = make(max_clients=2)
    a, _b = stream.connect(), stream.connect()
    with pytest.raises(TooManyClients):
        stream.connect()
    stream.disconnect(a)
    stream.disconnect(a)  # idempotent
    assert stream.client_count == 1
    stream.connect()


def test_disconnected_client_gets_nothing():
    _, stream = make()
    a = stream.connect()
    stream.disconnect(a)
    stream.emit("robot.updated", {"robot_id": "r"})
    assert drain(a) == []


def test_publishing_from_worker_threads_is_safe_and_ordered_per_client():
    bus, stream = make(queue_size=10_000)
    client = stream.connect()

    def work(n: int) -> None:
        for i in range(100):
            bus.publish(CallRaised(f"t{n}-{i}", "1"))

    threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    got = drain(client)
    assert len(got) == 800
    ids = [m.id for m in got]
    assert ids == sorted(ids) and len(set(ids)) == 800


async def test_worker_thread_publish_wakes_a_waiting_generator():
    _, stream = make(heartbeat=5)
    client = stream.connect()
    frames = stream.frames(client)
    first = await anext(frames)  # retry hint
    assert first.startswith("retry:")
    waiter = asyncio.ensure_future(anext(frames))
    await asyncio.sleep(0.05)
    threading.Thread(target=stream.emit, args=("robot.updated", {"robot_id": "r1"})).start()
    frame = await asyncio.wait_for(waiter, 2)
    assert frame.startswith("id: 1\nevent: robot.updated\ndata: ")
    assert frame.endswith("\n\n")
    await frames.aclose()
    assert stream.client_count == 0


async def test_idle_generator_sends_ping_comment():
    _, stream = make(heartbeat=0.02)
    frames = stream.frames(stream.connect())
    await anext(frames)
    assert await asyncio.wait_for(anext(frames), 2) == ": ping\n\n"
    await frames.aclose()


def test_publish_to_a_closed_loop_drops_that_client_without_raising():
    _, stream = make()
    loop = asyncio.new_event_loop()

    async def attach():
        client = stream.connect()
        await anext(stream.frames(client))
        return client

    loop.run_until_complete(attach())
    loop.close()
    stream.emit("robot.updated", {"robot_id": "r"})
    assert stream.client_count == 0
