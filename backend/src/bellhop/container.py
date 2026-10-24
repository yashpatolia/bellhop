"""Composition root: the only place that chooses concrete adapters."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx

from bellhop.adapters.event_bus import InMemoryEventBus
from bellhop.adapters.guards import (
    GuardedMemoryIndex,
    GuardedNotifier,
    GuardedRobotGateway,
    SerializedSubscriptions,
)
from bellhop.adapters.http_robot_gateway import HttpRobotGateway
from bellhop.adapters.local_memory import LocalMemoryIndex
from bellhop.adapters.memory_store import InMemoryStore
from bellhop.adapters.moss_memory import MossMemoryIndex
from bellhop.adapters.notifiers import RecordingNotifier
from bellhop.adapters.robot_gateway import RecordingRobotGateway
from bellhop.adapters.spacetimedb_store import SpacetimeDBStore
from bellhop.adapters.system import SystemClock, UuidIds
from bellhop.ports import EventBus, MemoryIndex, Notifier, RobotGateway
from bellhop.seed import seed_demo
from bellhop.services.analytics import Analytics
from bellhop.services.call_service import CallService
from bellhop.services.dispatcher import DefaultPolicy, Dispatcher
from bellhop.services.feedback import FeedbackService
from bellhop.services.liaison import Liaison
from bellhop.services.memory_service import MemoryService
from bellhop.services.robot_signals import RobotSignals
from bellhop.services.workload import Workload

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    memory: str = "local"  # local | moss
    store: str = "memory"  # memory | spacetimedb
    seed_demo: bool = False
    spacetimedb_url: str = "http://127.0.0.1:3000"
    spacetimedb_db: str = "bellhop"
    spacetimedb_token: str | None = None
    moss_project_id: str | None = None
    moss_project_key: str | None = None
    guard_timeouts: bool = True
    notifier_timeout: float = 2.0
    gateway_timeout: float = 2.0
    memory_budget_ms: float = 50
    robot_url: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            memory=env.get("BELLHOP_MEMORY", "local"),
            store=env.get("BELLHOP_STORE", "memory"),
            seed_demo=env.get("BELLHOP_SEED_DEMO", "") == "1",
            spacetimedb_url=env.get("BELLHOP_STDB_URL", "http://127.0.0.1:3000"),
            spacetimedb_db=env.get("BELLHOP_STDB_DB", "bellhop"),
            spacetimedb_token=env.get("BELLHOP_STDB_TOKEN"),
            moss_project_id=env.get("MOSS_PROJECT_ID"),
            moss_project_key=env.get("MOSS_PROJECT_KEY"),
            guard_timeouts=env.get("BELLHOP_GUARDS", "1") != "0",
            robot_url=env.get("BELLHOP_ROBOT_URL") or None,
        )


@dataclass
class Container:
    store: InMemoryStore | SpacetimeDBStore
    bus: InMemoryEventBus
    notifier: RecordingNotifier
    gateway: RecordingRobotGateway | HttpRobotGateway
    memory: MemoryService
    call_service: CallService
    dispatcher: Dispatcher
    liaison: Liaison
    feedback: FeedbackService
    analytics: Analytics
    workload: Workload
    # Guarded wrappers actually injected into services (None when guards are off).
    guarded_notifier: GuardedNotifier | None = None
    guarded_gateway: GuardedRobotGateway | None = None


def _memory_index(settings: Settings) -> MemoryIndex:
    local = LocalMemoryIndex()
    if settings.memory == "moss":
        moss = MossMemoryIndex(local, settings.moss_project_id, settings.moss_project_key)
        if settings.guard_timeouts:
            return GuardedMemoryIndex(moss, local, settings.memory_budget_ms)
        return moss
    return local


def _build_store(
    settings: Settings, stdb_client: httpx.Client | None
) -> InMemoryStore | SpacetimeDBStore:
    if settings.store == "memory":
        return InMemoryStore()
    if settings.store != "spacetimedb":
        raise ValueError(f"unsupported store: {settings.store}")
    stdb = SpacetimeDBStore(
        settings.spacetimedb_url,
        settings.spacetimedb_db,
        settings.spacetimedb_token,
        client=stdb_client,
    )
    try:
        stdb.hydrate()
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        log.warning(
            "SpacetimeDB at %s unusable (%s); falling back to in-memory store",
            settings.spacetimedb_url,
            type(exc).__name__,
        )
        return InMemoryStore()
    return stdb


def build_container(
    settings: Settings | None = None, *, stdb_client: httpx.Client | None = None
) -> Container:
    settings = settings or Settings()
    clock, ids = SystemClock(), UuidIds()
    store, bus = _build_store(settings, stdb_client), InMemoryEventBus()
    notifier = RecordingNotifier()
    gateway: RecordingRobotGateway | HttpRobotGateway = (
        HttpRobotGateway(settings.robot_url, settings.gateway_timeout)
        if settings.robot_url
        else RecordingRobotGateway()
    )
    guarded_notifier = guarded_gateway = None
    out_notifier: Notifier = notifier
    out_gateway: RobotGateway = gateway
    dispatcher_bus: EventBus = bus
    if settings.guard_timeouts:
        guarded_notifier = GuardedNotifier(notifier, settings.notifier_timeout)
        guarded_gateway = GuardedRobotGateway(gateway, settings.gateway_timeout)
        out_notifier, out_gateway = guarded_notifier, guarded_gateway
        dispatcher_bus = SerializedSubscriptions(bus)
    memory = MemoryService(_memory_index(settings), clock, ids)

    container = Container(
        store=store,
        bus=bus,
        notifier=notifier,
        gateway=gateway,
        memory=memory,
        call_service=CallService(store.calls, store.residents, bus, clock, ids, store.nurses),
        dispatcher=Dispatcher(
            store.calls,
            store.residents,
            store.robots,
            store.nurses,
            out_gateway,
            DefaultPolicy(),
            dispatcher_bus,
            clock,
        ),
        liaison=Liaison(store.calls, store.nurses, store.alerts, out_notifier, bus, clock, ids),
        feedback=FeedbackService(store.visits, store.calls, bus, ids),
        analytics=Analytics(store.calls, store.visits),
        workload=Workload(store.calls, store.robots, store.nurses, bus),
        guarded_notifier=guarded_notifier,
        guarded_gateway=guarded_gateway,
    )
    RobotSignals(store.calls, out_gateway, bus)
    if settings.seed_demo:
        seed_demo(store, memory)
    return container
