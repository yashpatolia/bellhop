"""Live events for the dashboard: domain events fanned out to Server-Sent Events clients.

The bus is synchronous and may run in worker threads, so `emit` only appends to a bounded
per-client deque and wakes the client's event loop with `call_soon_threadsafe`. It never
blocks or awaits: a slow or dead client cannot slow `publish`. Messages carry ids only; the
full Call, Alert or Robot is read from the store when a frame is sent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from collections import deque
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from typing import Any

from fastapi.encoders import jsonable_encoder

from bellhop.domain.events import AlertRaised, CallAssigned, CallRaised, CallResolved, CallScored

log = logging.getLogger(__name__)

EVENT_NAMES = {
    CallRaised: "call.raised",
    CallAssigned: "call.assigned",
    CallScored: "call.scored",
    CallResolved: "call.resolved",
    AlertRaised: "alert.raised",
}
RETRY_MS = 3000


class TooManyClients(Exception):
    pass


@dataclass(frozen=True)
class Message:
    id: int
    name: str
    ids: dict[str, Any]


@dataclass(eq=False)
class Client:
    queue: deque[Message]
    wakeup: asyncio.Event | None = None
    loop: asyncio.AbstractEventLoop | None = None
    closed: bool = field(default=False)

    def pop(self) -> Message | None:
        try:
            return self.queue.popleft()
        except IndexError:
            return None


class EventStream:
    def __init__(
        self,
        bus: Any,
        store: Any,
        *,
        max_clients: int = 20,
        queue_size: int = 100,
        heartbeat: float = 15.0,
    ) -> None:
        self._store = store
        self._max_clients = max_clients
        self._queue_size = queue_size
        self._heartbeat = heartbeat
        self._clients: list[Client] = []
        self._lock = threading.Lock()
        self._counter = 0
        for event_type, name in EVENT_NAMES.items():
            bus.subscribe(event_type, self._handler(name))

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def _handler(self, name: str):
        def handle(event: Any) -> None:
            self.emit(name, jsonable_encoder(asdict(event)))

        return handle

    def connect(self) -> Client:
        with self._lock:
            if len(self._clients) >= self._max_clients:
                raise TooManyClients(f"more than {self._max_clients} event clients")
            client = Client(deque(maxlen=self._queue_size))
            self._clients.append(client)
            return client

    def disconnect(self, client: Client) -> None:
        with self._lock:
            client.closed = True
            if client in self._clients:
                self._clients.remove(client)

    def emit(self, name: str, ids: dict[str, Any]) -> None:
        dead: list[Client] = []
        with self._lock:
            self._counter += 1
            message = Message(self._counter, name, ids)
            for client in self._clients:
                client.queue.append(message)  # bounded: the oldest is dropped, never blocks
                if client.loop is not None and client.wakeup is not None:
                    try:
                        client.loop.call_soon_threadsafe(client.wakeup.set)
                    except RuntimeError:  # its loop is closed: the client is gone
                        dead.append(client)
            for client in dead:
                client.closed = True
                self._clients.remove(client)

    def _payload(self, message: Message) -> dict[str, Any]:
        ids = message.ids
        data: dict[str, Any] = dict(ids)
        try:
            if message.name == "alert.raised":
                data["alert"] = jsonable_encoder(self._store.alerts.get(ids["alert_id"]))
            elif message.name == "robot.updated":
                data["robot"] = jsonable_encoder(self._store.robots.get(ids["robot_id"]))
            else:
                data["call"] = jsonable_encoder(self._store.calls.get(ids["call_id"]))
        except Exception:
            log.exception("could not load object for %s", message.name)
        return data

    def frame(self, message: Message) -> str:
        data = json.dumps(self._payload(message), separators=(",", ":"))
        return f"id: {message.id}\nevent: {message.name}\ndata: {data}\n\n"

    async def frames(self, client: Client) -> AsyncIterator[str]:
        """SSE text frames for one connected client; disconnects it when closed or cancelled."""
        client.loop = asyncio.get_running_loop()
        client.wakeup = asyncio.Event()
        try:
            yield f"retry: {RETRY_MS}\n\n"
            while not client.closed:
                message = client.pop()
                if message is None:
                    client.wakeup.clear()
                    message = client.pop()  # a push may have landed before the clear
                if message is not None:
                    yield self.frame(message)
                    continue
                try:
                    await asyncio.wait_for(client.wakeup.wait(), self._heartbeat)
                except TimeoutError:
                    yield ": ping\n\n"
        finally:
            self.disconnect(client)
