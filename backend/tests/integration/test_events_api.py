"""GET /events: drives the ASGI app directly (TestClient buffers streams until they end)."""

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container


class Stream:
    """Minimal ASGI client for one long-lived GET."""

    def __init__(self, app, path="/events", query=b"", headers=()):
        self.app, self.status, self.chunks = app, None, asyncio.Queue()
        self._disconnect = asyncio.Event()
        self._started = asyncio.Event()
        self.scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query,
            "headers": list(headers),
            "scheme": "http",
            "server": ("t", 80),
            "client": ("c", 1),
            "root_path": "",
        }
        self.task = None

    async def _receive(self):
        if not self._started.is_set():
            self._started.set()
            return {"type": "http.request", "body": b"", "more_body": False}
        await self._disconnect.wait()
        return {"type": "http.disconnect"}

    async def _send(self, message):
        if message["type"] == "http.response.start":
            self.status = message["status"]
            self.headers = dict(message["headers"])
        elif message["type"] == "http.response.body":
            await self.chunks.put(message.get("body", b"").decode())

    async def open(self):
        self.task = asyncio.ensure_future(self.app(self.scope, self._receive, self._send))
        for _ in range(200):
            if self.status is not None:
                return self
            await asyncio.sleep(0.01)
        raise AssertionError("no response start")

    async def events(self, n):
        """Next n SSE events as (id, name, data), skipping comments and the retry hint."""
        out = []
        buf = ""
        while len(out) < n:
            buf += await asyncio.wait_for(self.chunks.get(), 5)
            while "\n\n" in buf:
                raw, buf = buf.split("\n\n", 1)
                fields = dict(line.split(": ", 1) for line in raw.splitlines() if ": " in line)
                if "event" in fields:
                    out.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
        return out

    async def close(self):
        self._disconnect.set()
        await asyncio.wait_for(self.task, 5)


@pytest.fixture
def container():
    return build_container(Settings(seed_demo=True))


@pytest.fixture
def app(container):
    return create_app(container)


def test_call_lifecycle_streams_named_events_with_full_objects_in_order(app, container):
    """The HTTP handlers publish into the same broadcaster used by GET /events.

    Do not mix a long-lived direct ASGI request with TestClient: TestClient owns a
    second event loop and can deadlock the test harness.  The endpoint connection
    itself is covered below; this test verifies its live source end-to-end.
    """
    http = TestClient(app)
    subscriber = container.events.connect()

    call = http.post("/calls", json={"room": "12"}).json()
    http.post(f"/calls/{call['id']}/in-visit")
    http.post(f"/calls/{call['id']}/turns", json={"speaker": "resident", "text": "my hip hurts"})
    http.post(
        f"/calls/{call['id']}/score",
        json={"urgency": 3, "category": "pain", "summary": "hip"},
    )
    http.post(f"/calls/{call['id']}/resolve", json={})
    messages = []
    while (message := subscriber.pop()) is not None:
        messages.append(message)
    events = [parse_frame(container.events.frame(message)) for message in messages]
    names = [event[1] for event in events]
    assert names == [
        "call.raised",
        "call.assigned",
        "call.updated",
        "call.updated",
        "call.scored",
        "alert.raised",
        "call.resolved",
    ]
    ids = [e[0] for e in events]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)

    raised, assigned, in_visit, turn, scored, alert, resolved = (e[2] for e in events)
    assert raised["call_id"] == call["id"] and raised["room"] == "12"
    assert raised["call"]["id"] == call["id"]
    assert assigned["robot_id"] == "robot_1" and "call" in assigned
    assert in_visit["call"]["status"] == "in_visit"
    assert turn["call"]["transcript"][-1]["text"] == "my hip hurts"
    assert scored["urgency"] == 3 and scored["category"] == "pain"
    assert scored["call"]["summary"] == "hip"
    assert alert["level"] == 3 and alert["alert"]["id"] == alert["alert_id"]
    assert alert["alert"]["call_id"] == call["id"]
    assert resolved["by_robot"] is False and resolved["call"]["status"] == "resolved"
    container.events.disconnect(subscriber)


def test_put_robot_emits_robot_updated(app, container):
    http = TestClient(app)
    subscriber = container.events.connect()
    http.put("/robots/robot_1", json={"status": "charging", "battery": 0.4, "room": "dock"})
    (message,) = iter(lambda: subscriber.pop(), None)
    _, name, data = parse_frame(container.events.frame(message))
    assert name == "robot.updated"
    assert data["robot_id"] == "robot_1"
    assert data["robot"] == {
        "id": "robot_1",
        "status": "charging",
        "battery": 0.4,
        "room": "dock",
        "target": None,
    }
    container.events.disconnect(subscriber)


def parse_frame(frame: str) -> tuple[int, str, dict]:
    fields = dict(line.split(": ", 1) for line in frame.splitlines() if ": " in line)
    return int(fields["id"]), fields["event"], json.loads(fields["data"])


async def test_disconnect_frees_the_client_slot(app, container):
    stream = await Stream(app).open()
    assert app.state.events.client_count == 1
    await stream.close()
    assert app.state.events.client_count == 0


async def test_above_client_cap_is_503():
    app = create_app(build_container(Settings(seed_demo=True, max_event_clients=1)))
    first = await Stream(app).open()
    second = await Stream(app).open()
    assert second.status == 503
    await asyncio.wait_for(second.task, 5)
    await first.close()


async def test_events_accept_api_key_query_only_when_a_key_is_set():
    app = create_app(build_container(Settings(seed_demo=True, api_key="sekret")))
    denied = await Stream(app).open()
    assert denied.status == 401
    wrong = await Stream(app, query=b"api_key=nope").open()
    assert wrong.status == 401
    ok = await Stream(app, query=b"api_key=sekret").open()
    assert ok.status == 200
    await ok.close()
    header = await Stream(app, headers=[(b"x-api-key", b"sekret")]).open()
    assert header.status == 200
    await header.close()
    # the query parameter is accepted nowhere else
    assert TestClient(app).get("/calls", params={"api_key": "sekret"}).status_code == 401
