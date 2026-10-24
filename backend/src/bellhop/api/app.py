"""HTTP API: thin routes, each delegating to one service method."""

from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request, Security
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from starlette.background import BackgroundTask
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from bellhop.api.deps import (
    ack_alert,
    get_call,
    require_resident,
    triage_score,
)
from bellhop.api.events import TooManyClients
from bellhop.container import Container
from bellhop.domain import (
    Alert,
    Call,
    InvalidTransition,
    MemoryFact,
    Nurse,
    Resident,
    Robot,
    RobotStatus,
    Urgency,
)
from bellhop.domain.care import (
    CareEntry,
    EntryKind,
    FamilyMessage,
    Flag,
    Preferences,
)
from bellhop.ports.content import ContentItem
from bellhop.services.admin import Conflict
from bellhop.services.memory_guard import Accepted, PendingFact

MAX_BODY_BYTES = 1024 * 1024
MAX_LIST = 1000


class RaiseCall(BaseModel):
    room: str = Field(max_length=32)


class TurnIn(BaseModel):
    speaker: str = Field(max_length=32)
    text: str = Field(max_length=2000)


class ScoreIn(BaseModel):
    urgency: int = Field(ge=1, le=4)
    category: str = Field(max_length=64)
    summary: str | None = Field(default=None, max_length=500)
    confidence: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)


class ResolveIn(BaseModel):
    by_robot: bool = True


class OverrideIn(BaseModel):
    urgency: int = Field(ge=1, le=4)
    nurse_id: str | None = Field(default=None, max_length=64)


class RobotReport(BaseModel):
    status: RobotStatus
    battery: float = Field(ge=0, le=1, allow_inf_nan=False)
    room: str | None = Field(default=None, max_length=32)


class AckIn(BaseModel):
    nurse_id: str = Field(max_length=64)


class MemoryIn(BaseModel):
    text: str = Field(max_length=2000)
    tags: list[Annotated[str, StringConstraints(max_length=32)]] = Field(
        default_factory=list, max_length=10
    )
    source: str = Field(default="conversation", max_length=32)
    confidence: float = Field(default=1.0, ge=0, le=1, allow_inf_nan=False)


class CareIn(BaseModel):
    kind: EntryKind
    value: float | None = Field(default=None, ge=1, le=5, allow_inf_nan=False)
    note: str = Field(default="", max_length=500)
    call_id: str | None = Field(default=None, max_length=64)


class PreferencesIn(BaseModel):
    model_config = {"extra": "forbid"}
    hard_of_hearing: bool | None = None
    quiet_mode: bool | None = None
    night_mode: bool | None = None
    favourite_drink: str | None = Field(default=None, max_length=64)


class ResidentIn(BaseModel):
    birth_year: int = Field(ge=1880, le=2015)


_Flag = Annotated[str, StringConstraints(min_length=1, max_length=32)]
_BirthYear = Annotated[int, Field(ge=1880, le=2015)]


class ResidentCreate(BaseModel):
    model_config = {"extra": "forbid"}
    id: str | None = Field(default=None, min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    room: str = Field(min_length=1, max_length=32)
    risk_flags: list[_Flag] = Field(default_factory=list, max_length=10)
    birth_year: _BirthYear | None = None


class ResidentPatch(BaseModel):
    """Only the given keys change. Defaults are never used (exclude_unset), so an explicit
    null is rejected for every field except birth_year."""

    model_config = {"extra": "forbid"}
    name: str = Field(default=None, min_length=1, max_length=80)  # type: ignore[assignment]
    room: str = Field(default=None, min_length=1, max_length=32)  # type: ignore[assignment]
    risk_flags: list[_Flag] = Field(default=None, max_length=10)  # type: ignore[assignment]
    birth_year: _BirthYear | None = None


class NurseCreate(BaseModel):
    model_config = {"extra": "forbid"}
    id: str | None = Field(default=None, min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    on_shift: bool = True


class NursePatch(BaseModel):
    model_config = {"extra": "forbid"}
    name: str = Field(default=None, min_length=1, max_length=80)  # type: ignore[assignment]
    on_shift: bool = Field(default=None)  # type: ignore[assignment]


class TextIn(BaseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]


class BodyLimit:
    """Reject request bodies over MAX_BODY_BYTES with 413 (declared or streamed)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length", b"0")
        too_big = declared.isdigit() and int(declared) > MAX_BODY_BYTES
        messages: list[Message] = []
        size = 0
        while not too_big:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            size += len(message.get("body", b""))
            if size > MAX_BODY_BYTES:
                too_big = True
            elif not message.get("more_body", False):
                break
        if too_big:
            response = JSONResponse(status_code=413, content={"detail": "request body too large"})
            await response(scope, receive, send)
            return
        replay = iter(messages)

        async def replayed() -> Message:
            return next(replay, None) or await receive()

        await self.app(scope, replayed, send)


def _error(status: int):
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return handler


async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    # Echo only loc/msg/type: the offending input may be NaN/Infinity, which JSON cannot carry.
    detail = [
        {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": detail}))


async def _pydantic_error(_: Request, exc: ValidationError) -> JSONResponse:
    detail = [
        {"loc": e.get("loc"), "msg": e.get("msg"), "type": e.get("type")} for e in exc.errors()
    ]
    return JSONResponse(status_code=422, content=jsonable_encoder({"detail": detail}))


def create_app(container: Container) -> FastAPI:
    app = FastAPI(title="Bellhop")
    settings = container.settings
    app.add_middleware(BodyLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_exception_handler(LookupError, _error(404))  # unknown call/alert/resident/flag/...
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(InvalidTransition, _error(409))
    app.add_exception_handler(Conflict, _error(409))  # duplicate id, room already occupied
    app.add_exception_handler(ValidationError, _pydantic_error)  # type: ignore[arg-type]
    app.state.events = container.events
    calls = container.call_service
    key_header = APIKeyHeader(name="X-API-Key", scheme_name="ApiKeyAuth", auto_error=False)

    def require_key(key: str | None = Security(key_header)) -> None:
        # The scheme is always in the OpenAPI spec; enforcement only when a key is configured.
        expected = settings.api_key
        if expected is not None and not (
            key is not None and hmac.compare_digest(key.encode(), expected.encode())
        ):
            raise HTTPException(status_code=401, detail="missing or invalid X-API-Key")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    def require_event_key(
        key: str | None = Security(key_header),
        api_key: str | None = Query(
            None, max_length=256, description="EventSource cannot send headers: use this instead"
        ),
    ) -> None:
        expected = settings.api_key
        if expected is None:
            return
        given = key if key is not None else api_key
        if given is None or not hmac.compare_digest(given.encode(), expected.encode()):
            raise HTTPException(status_code=401, detail="missing or invalid API key")

    events = APIRouter(dependencies=[Depends(require_event_key)])

    @events.get(
        "/events",
        response_class=StreamingResponse,
        responses={200: {"content": {"text/event-stream": {}}}, 503: {"description": "too many"}},
    )
    async def stream_events() -> StreamingResponse:
        """Server-Sent Events: call.*, alert.raised, robot.updated. See contracts/README.md."""
        try:
            client = container.events.connect()
        except TooManyClients as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        return StreamingResponse(
            container.events.frames(client),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            background=BackgroundTask(container.events.disconnect, client),
        )

    api = APIRouter(dependencies=[Depends(require_key)])

    @api.post("/calls", status_code=201)
    def create_call(body: RaiseCall) -> Call:
        call = calls.raise_call(body.room)
        return get_call(container, call.id)

    @api.get("/calls")
    def list_calls(limit: int = Query(200, ge=1, le=MAX_LIST)) -> list[Call]:
        newest = sorted(container.store.calls.list_all(), key=lambda c: c.created_at, reverse=True)
        return newest[:limit]

    @api.get("/calls/{call_id}")
    def read_call(call_id: str) -> Call:
        return get_call(container, call_id)

    @api.post("/calls/{call_id}/turns")
    def add_turn(call_id: str, body: TurnIn) -> Call:
        calls.add_turn(call_id, body.speaker, body.text)
        return get_call(container, call_id)

    @api.post("/calls/{call_id}/score")
    def score(call_id: str, body: ScoreIn) -> Call:
        triage_score(
            container, call_id, Urgency(body.urgency), body.category, body.summary, body.confidence
        )
        return get_call(container, call_id)

    @api.post("/calls/{call_id}/triage-failed")
    def triage_failed(call_id: str) -> Call:
        triage_score(container, call_id, None, "unknown", None, None)
        return get_call(container, call_id)

    @api.get("/calls/{call_id}/note")
    def visit_note(call_id: str) -> dict[str, Any]:
        get_call(container, call_id)
        note = container.visit_notes.build(call_id)
        return {
            "text": note.text,
            "resident_id": note.resident_id,
            "room": note.room,
            "at": note.at,
        }

    @api.post("/calls/{call_id}/in-visit")
    def in_visit(call_id: str) -> Call:
        calls.mark_in_visit(call_id)
        return get_call(container, call_id)

    @api.post("/calls/{call_id}/resolve")
    def resolve(call_id: str, body: ResolveIn | None = None) -> Call:
        calls.resolve(call_id, by_robot=body.by_robot if body else True)
        return get_call(container, call_id)

    @api.post("/calls/{call_id}/override")
    def override(call_id: str, body: OverrideIn) -> Call:
        """Nurse corrects the robot's urgency; feeds GET /labelled-examples."""
        get_call(container, call_id)
        try:
            container.feedback.nurse_override(call_id, Urgency(body.urgency))
        except LookupError:
            raise InvalidTransition("call has no visit yet: resolve it before overriding") from None
        return get_call(container, call_id)

    @api.get("/labelled-examples")
    def labelled_examples() -> list[dict[str, Any]]:
        return container.analytics.labelled_examples()

    @api.post("/alerts/{alert_id}/ack")
    def ack(alert_id: str, body: AckIn) -> Alert:
        return ack_alert(container, alert_id, body.nurse_id)

    @api.get("/alerts")
    def list_alerts(limit: int = Query(200, ge=1, le=MAX_LIST)) -> list[Alert]:
        alerts = container.store.alerts.list_all()
        return sorted(alerts, key=lambda a: a.created_at, reverse=True)[:limit]

    @api.get("/residents/{resident_id}/memory")
    def recall(
        resident_id: str,
        q: str = Query("", max_length=500),
        k: int = Query(3, ge=1, le=20),
    ) -> list[MemoryFact]:
        require_resident(container, resident_id)
        return container.memory.recall(resident_id, q, k)

    @api.post("/residents/{resident_id}/memory", status_code=201)
    def remember(resident_id: str, body: MemoryIn) -> Response:
        require_resident(container, resident_id)
        result = container.memory_guard.propose(
            resident_id, body.text, body.tags, body.source, body.confidence
        )
        if isinstance(result, Accepted):
            return JSONResponse(status_code=201, content=jsonable_encoder(result.fact))
        if result.reason == "pending_review":
            return JSONResponse(
                status_code=202,
                content={"status": "pending_review", "detail": "queued for nurse review"},
            )
        return JSONResponse(status_code=422, content={"detail": result.reason})

    @api.get("/residents/{resident_id}/memory/pending")
    def pending_memory(resident_id: str) -> list[PendingFact]:
        require_resident(container, resident_id)
        return container.memory_guard.pending(resident_id)

    @api.post("/residents/{resident_id}/memory/pending/{pending_id}/approve")
    def approve_memory(resident_id: str, pending_id: str) -> MemoryFact:
        require_resident(container, resident_id)
        result = container.memory_guard.approve(pending_id, resident_id)
        if isinstance(result, Accepted):
            return result.fact
        # Now a duplicate of stored memory: conflict. Now unsafe or malformed: unprocessable.
        status = 409 if result.reason == "duplicate" else 422
        raise HTTPException(status_code=status, detail=result.reason)

    @api.post("/residents/{resident_id}/memory/pending/{pending_id}/reject", status_code=200)
    def reject_memory(resident_id: str, pending_id: str) -> dict[str, str]:
        container.memory_guard.reject(pending_id, resident_id)
        return {"status": "rejected"}

    @api.delete("/residents/{resident_id}/memory/{fact_id}", status_code=204)
    def forget_fact(resident_id: str, fact_id: str) -> Response:
        if not container.memory_guard.forget(resident_id, fact_id):
            raise LookupError(fact_id)
        return Response(status_code=204)

    @api.delete("/residents/{resident_id}/memory")
    def forget_all(resident_id: str) -> dict[str, int]:
        require_resident(container, resident_id)
        return {"removed": container.memory_guard.forget_all(resident_id)}

    @api.post("/residents/{resident_id}/care", status_code=201)
    def record_care(resident_id: str, body: CareIn) -> CareEntry:
        require_resident(container, resident_id)
        if body.call_id is not None:
            get_call(container, body.call_id)  # unknown call -> 404
        cs = container.care_signals
        if body.kind in (EntryKind.MOOD, EntryKind.PAIN) and body.value is None:
            raise RequestValidationError(
                [{"loc": ("body", "value"), "msg": "value required", "type": "value_error"}]
            )
        if body.kind == EntryKind.MOOD:
            return cs.record_mood(resident_id, body.value, body.call_id, body.note)  # type: ignore[arg-type]
        if body.kind == EntryKind.PAIN:
            return cs.record_pain(resident_id, body.value, body.call_id, body.note)  # type: ignore[arg-type]
        if body.kind == EntryKind.DRINK:
            return cs.record_drink(resident_id, body.call_id, body.note)
        return cs.record_repeat_question(resident_id, body.call_id)

    @api.get("/residents/{resident_id}/care/summary")
    def care_summary(resident_id: str) -> dict[str, Any]:
        require_resident(container, resident_id)
        cs, now = container.care_signals, container.clock.now()
        return {
            "pain_streak_days": cs.pain_streak(resident_id, now).days,
            "mood_lower_than_usual": cs.mood_changed_from_usual(resident_id, now).changed,
            "drinks_today": cs.hydration_today(resident_id, now).drinks,
            "repeat_questions_today": cs.repeat_question_count(resident_id, now).count,
        }

    @api.get("/flags")
    def list_flags(resident_id: str | None = None, open_only: bool = True) -> list[Flag]:
        return container.care_store.flags.list(resident_id, open_only)

    @api.post("/flags/{flag_id}/resolve")
    def resolve_flag(flag_id: str) -> Flag:
        return container.care_signals.resolve_flag(flag_id)

    @api.put("/residents/{resident_id}")
    def update_resident(resident_id: str, body: ResidentIn) -> Resident:
        resident = container.store.residents.get(resident_id)
        if resident is None:
            raise LookupError(resident_id)
        resident.birth_year = body.birth_year
        container.store.residents.save(resident)
        return resident

    @api.post("/residents", status_code=201)
    def create_resident(body: ResidentCreate) -> Resident:
        return container.admin.create_resident(**body.model_dump())

    @api.get("/residents")
    def list_residents() -> list[Resident]:
        return container.admin.list_residents()

    @api.get("/residents/{resident_id}")
    def read_resident(resident_id: str) -> Resident:
        return container.admin.get_resident(resident_id)

    @api.patch("/residents/{resident_id}")
    def patch_resident(resident_id: str, body: ResidentPatch) -> Resident:
        return container.admin.update_resident(resident_id, **body.model_dump(exclude_unset=True))

    @api.post("/nurses", status_code=201)
    def create_nurse(body: NurseCreate) -> Nurse:
        return container.admin.create_nurse(**body.model_dump())

    @api.get("/nurses")
    def list_nurses() -> list[Nurse]:
        return container.admin.list_nurses()

    @api.patch("/nurses/{nurse_id}")
    def patch_nurse(nurse_id: str, body: NursePatch) -> Nurse:
        return container.admin.update_nurse(nurse_id, **body.model_dump(exclude_unset=True))

    @api.get("/residents/{resident_id}/reminiscence")
    def reminiscence(resident_id: str, k: int = Query(3, ge=1, le=20)) -> list[ContentItem]:
        require_resident(container, resident_id)
        return container.reminiscence.items(resident_id, k)

    @api.post("/residents/{resident_id}/reminiscence/ingest", status_code=201)
    def ingest_reminiscence(resident_id: str, k: int = Query(5, ge=1, le=20)) -> list[MemoryFact]:
        require_resident(container, resident_id)
        return container.reminiscence.ingest(resident_id, k)

    @api.get("/residents/{resident_id}/preferences")
    def get_preferences(resident_id: str) -> Preferences:
        return container.preferences.get(require_resident(container, resident_id))

    @api.put("/residents/{resident_id}/preferences")
    def put_preferences(resident_id: str, body: PreferencesIn) -> Preferences:
        require_resident(container, resident_id)
        return container.preferences.update(resident_id, **body.model_dump(exclude_unset=True))

    @api.get("/residents/{resident_id}/speech-settings")
    def speech_settings(resident_id: str) -> dict[str, Any]:
        return container.preferences.speech_settings(require_resident(container, resident_id))

    @api.post("/residents/{resident_id}/family/messages", status_code=201)
    def leave_voice_note(resident_id: str, body: TextIn) -> FamilyMessage:
        return container.family.leave_voice_note(
            require_resident(container, resident_id), body.text
        )

    @api.post("/residents/{resident_id}/family/replies", status_code=201)
    def record_reply(resident_id: str, body: TextIn) -> FamilyMessage:
        return container.family.record_reply(require_resident(container, resident_id), body.text)

    @api.get("/residents/{resident_id}/family/messages")
    def family_messages(resident_id: str) -> list[FamilyMessage]:
        require_resident(container, resident_id)
        return container.care_store.messages.list(resident_id)

    @api.get("/residents/{resident_id}/postcard")
    def postcard(resident_id: str) -> dict[str, list[str]]:
        require_resident(container, resident_id)
        return {"lines": container.family.daily_postcard(resident_id, container.clock.now())}

    @api.get("/robots")
    def list_robots() -> list[Robot]:
        return container.store.robots.list_all()

    @api.put("/robots/{robot_id}")
    def report_robot(robot_id: str, body: RobotReport) -> Robot:
        robots = container.store.robots
        robot = robots.get(robot_id)
        if robot is None:
            if not settings.allow_new_robots:
                raise LookupError(robot_id)
            robot = Robot(id=robot_id)
        holds_call = any(c.robot_id == robot_id for c in container.store.calls.list_open())
        # A robot with an open call stays busy: only a resolved call frees it (safer than
        # trusting a stale "idle" report). Battery and room are still applied.
        if not (holds_call and body.status is RobotStatus.IDLE):
            robot.status = body.status
        robot.battery, robot.room = body.battery, body.room
        robots.save(robot)
        container.events.emit("robot.updated", {"robot_id": robot_id})
        return robot

    @api.get("/metrics")
    def metrics() -> dict[str, Any]:
        a = container.analytics
        return {
            "resolved_without_nurse": a.resolved_without_nurse(),
            "minutes_saved": a.minutes_saved(),
            "share_answered_within_10min": a.share_answered_within(600),
            "calls_by_hour": a.calls_by("hour"),
            "calls_by_room": a.calls_by("room"),
            "calls_by_category": a.calls_by("category"),
        }

    app.include_router(events)
    app.include_router(api)
    return app
