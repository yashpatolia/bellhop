"""Composition root: the only place that chooses concrete adapters."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx

from bellhop.adapters.apify_content import ApifyContentFeed
from bellhop.adapters.care_store import InMemoryCareStore
from bellhop.adapters.deletable_memory import DeletableLocalMemoryIndex
from bellhop.adapters.event_bus import InMemoryEventBus
from bellhop.adapters.guards import (
    GuardedMemoryIndex,
    GuardedNotifier,
    GuardedRobotGateway,
    SerializedSubscriptions,
)
from bellhop.adapters.http_robot_gateway import HttpRobotGateway
from bellhop.adapters.local_content import LocalContentFeed
from bellhop.adapters.memory_store import InMemoryStore
from bellhop.adapters.moss_memory import MossMemoryIndex
from bellhop.adapters.notifiers import RecordingNotifier
from bellhop.adapters.robot_gateway import RecordingRobotGateway
from bellhop.adapters.spacetimedb_store import SpacetimeDBStore
from bellhop.adapters.system import SystemClock, UuidIds
from bellhop.adapters.wikipedia_content import WikipediaContentFeed
from bellhop.api.events import EventStream
from bellhop.ports import Clock, EventBus, MemoryIndex, Notifier, RobotGateway
from bellhop.ports.content import ContentFeed
from bellhop.scenarios import apply_scenario, load_scenario
from bellhop.seed import seed_demo
from bellhop.services.admin import AdminService
from bellhop.services.analytics import Analytics
from bellhop.services.call_service import CallService
from bellhop.services.care_signals import CareSignals
from bellhop.services.dispatcher import DefaultPolicy, Dispatcher
from bellhop.services.family import FamilyService
from bellhop.services.feedback import FeedbackService
from bellhop.services.liaison import Liaison
from bellhop.services.memory_guard import MemoryGuard
from bellhop.services.memory_service import MemoryService
from bellhop.services.preferences_service import PreferencesService
from bellhop.services.reminiscence import ReminiscenceService
from bellhop.services.robot_signals import RobotSignals
from bellhop.services.triage_guard import TriageGuard
from bellhop.services.visit_notes import VisitNotes
from bellhop.services.workload import Workload

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Settings:
    memory: str = "local"  # local | moss
    store: str = "memory"  # memory | spacetimedb
    seed_demo: bool = False
    seed_file: str | None = None  # scenario JSON; wins over seed_demo
    spacetimedb_url: str = "http://127.0.0.1:3000"
    spacetimedb_db: str = "bellhop"
    spacetimedb_token: str | None = field(default=None, repr=False)
    moss_project_id: str | None = None
    moss_project_key: str | None = field(default=None, repr=False)
    guard_timeouts: bool = True
    notifier_timeout: float = 2.0
    gateway_timeout: float = 2.0
    memory_budget_ms: float = 50
    max_event_clients: int = 20  # GET /events subscribers; more get 503
    robot_url: str | None = None
    content: str = "local"  # local | wikipedia | apify
    apify_token: str | None = field(default=None, repr=False)
    api_key: str | None = field(default=None, repr=False)  # unset = API is open
    cors_origins: tuple[str, ...] = ("*",)
    allow_new_robots: bool = True  # False: PUT /robots/{id} only updates known robots

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        return cls(
            memory=env.get("BELLHOP_MEMORY", "local"),
            store=env.get("BELLHOP_STORE", "memory"),
            seed_demo=env.get("BELLHOP_SEED_DEMO", "") == "1",
            seed_file=env.get("BELLHOP_SEED_FILE") or None,
            spacetimedb_url=env.get("BELLHOP_STDB_URL", "http://127.0.0.1:3000"),
            spacetimedb_db=env.get("BELLHOP_STDB_DB", "bellhop"),
            spacetimedb_token=env.get("BELLHOP_STDB_TOKEN"),
            moss_project_id=env.get("MOSS_PROJECT_ID"),
            moss_project_key=env.get("MOSS_PROJECT_KEY"),
            guard_timeouts=env.get("BELLHOP_GUARDS", "1") != "0",
            robot_url=env.get("BELLHOP_ROBOT_URL") or None,
            content=env.get("BELLHOP_CONTENT", "local"),
            apify_token=env.get("APIFY_TOKEN") or None,
            api_key=env.get("BELLHOP_API_KEY") or None,
            cors_origins=tuple(
                o.strip() for o in env.get("BELLHOP_CORS_ORIGINS", "*").split(",") if o.strip()
            )
            or ("*",),
            allow_new_robots=env.get("BELLHOP_ALLOW_NEW_ROBOTS", "1") not in ("0", "false", "no"),
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
    clock: Clock
    care_store: InMemoryCareStore
    care_signals: CareSignals
    visit_notes: VisitNotes
    family: FamilyService
    preferences: PreferencesService
    memory_guard: MemoryGuard
    triage_guard: TriageGuard
    reminiscence: ReminiscenceService
    admin: AdminService
    events: EventStream
    # Guarded wrappers actually injected into services (None when guards are off).
    guarded_notifier: GuardedNotifier | None = None
    guarded_gateway: GuardedRobotGateway | None = None
    settings: Settings = field(default_factory=Settings)


def _require_http_url(name: str, url: str) -> None:
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError(f"{name} must start with http:// or https://")


def _memory_index(
    settings: Settings,
) -> tuple[MemoryIndex, DeletableLocalMemoryIndex]:
    """The index MemoryService uses, plus the local index MemoryGuard deletes from."""
    local = DeletableLocalMemoryIndex()
    if settings.memory == "moss":
        moss = MossMemoryIndex(local, settings.moss_project_id, settings.moss_project_key)
        if settings.guard_timeouts:
            return GuardedMemoryIndex(moss, local, settings.memory_budget_ms), local
        return moss, local
    return local, local


def _content_feed(settings: Settings) -> ContentFeed:
    local = LocalContentFeed()
    if settings.content == "local":
        return local
    if settings.content == "wikipedia":
        return WikipediaContentFeed(local)
    if settings.content == "apify":
        return ApifyContentFeed(local, settings.apify_token)
    raise ValueError(f"unsupported content feed: {settings.content}")


def _build_store(
    settings: Settings, stdb_client: httpx.Client | None
) -> InMemoryStore | SpacetimeDBStore:
    if settings.store == "memory":
        return InMemoryStore()
    if settings.store != "spacetimedb":
        raise ValueError(f"unsupported store: {settings.store}")
    _require_http_url("BELLHOP_STDB_URL", settings.spacetimedb_url)
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
            urlsplit(settings.spacetimedb_url).netloc.rpartition("@")[2],
            type(exc).__name__,
        )
        return InMemoryStore()
    return stdb


def build_container(
    settings: Settings | None = None, *, stdb_client: httpx.Client | None = None
) -> Container:
    settings = settings or Settings()
    if settings.robot_url:
        _require_http_url("BELLHOP_ROBOT_URL", settings.robot_url)
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
    # Subscribed before every service so call.raised reaches the stream before call.assigned.
    events = EventStream(bus, store, max_clients=settings.max_event_clients)
    index, local_index = _memory_index(settings)
    memory = MemoryService(index, clock, ids)
    care_store = InMemoryCareStore()

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
        clock=clock,
        care_store=care_store,
        care_signals=CareSignals(care_store.entries, care_store.flags, clock, ids, bus),
        visit_notes=VisitNotes(store.calls, care_store.entries, clock),
        family=FamilyService(
            care_store.messages, store.residents, store.calls, care_store.entries, clock, ids
        ),
        preferences=PreferencesService(care_store.preferences, clock),
        memory_guard=MemoryGuard(memory, local_index),
        triage_guard=TriageGuard(),
        reminiscence=ReminiscenceService(_content_feed(settings), memory, store.residents),
        admin=AdminService(store.residents, store.nurses, store.robots, store.calls, clock, ids),
        events=events,
        guarded_notifier=guarded_notifier,
        guarded_gateway=guarded_gateway,
        settings=settings,
    )
    RobotSignals(store.calls, out_gateway, bus)
    if settings.seed_file:
        apply_scenario(load_scenario(settings.seed_file), store, memory, care_store)
    elif settings.seed_demo:
        seed_demo(store, memory)
    return container
