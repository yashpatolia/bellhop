"""HTTP API: thin routes, each delegating to one service method."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from bellhop.api.deps import (
    ack_alert,
    get_call,
    require_resident,
    triage_score,
)
from bellhop.container import Container
from bellhop.domain import (
    Alert,
    Call,
    InvalidTransition,
    MemoryFact,
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
from bellhop.services.memory_guard import Accepted, PendingFact


class RaiseCall(BaseModel):
    room: str


class TurnIn(BaseModel):
    speaker: str
    text: str


class ScoreIn(BaseModel):
    urgency: int = Field(ge=1, le=4)
    category: str
    summary: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class ResolveIn(BaseModel):
    by_robot: bool = True


class RobotReport(BaseModel):
    status: RobotStatus
    battery: float = Field(ge=0, le=1)
    room: str | None = None


class AckIn(BaseModel):
    nurse_id: str


class MemoryIn(BaseModel):
    text: str
    tags: list[str] = Field(default_factory=list)
    source: str = "conversation"
    confidence: float = Field(default=1.0, ge=0, le=1)


class CareIn(BaseModel):
    kind: EntryKind
    value: float | None = Field(default=None, ge=1, le=5)
    note: str = ""
    call_id: str | None = None


class PreferencesIn(BaseModel):
    model_config = {"extra": "forbid"}
    hard_of_hearing: bool | None = None
    quiet_mode: bool | None = None
    night_mode: bool | None = None
    favourite_drink: str | None = None


class ResidentIn(BaseModel):
    birth_year: int = Field(ge=1880, le=2015)


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


def _error(status: int):
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return handler


def create_app(container: Container) -> FastAPI:
    app = FastAPI(title="Bellhop")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.add_exception_handler(LookupError, _error(404))  # unknown call/alert/resident/flag/...
    app.add_exception_handler(InvalidTransition, _error(409))
    calls = container.call_service

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/calls", status_code=201)
    def create_call(body: RaiseCall) -> Call:
        call = calls.raise_call(body.room)
        return get_call(container, call.id)

    @app.get("/calls")
    def list_calls() -> list[Call]:
        return sorted(container.store.calls.list_all(), key=lambda c: c.created_at, reverse=True)

    @app.get("/calls/{call_id}")
    def read_call(call_id: str) -> Call:
        return get_call(container, call_id)

    @app.post("/calls/{call_id}/turns")
    def add_turn(call_id: str, body: TurnIn) -> Call:
        calls.add_turn(call_id, body.speaker, body.text)
        return get_call(container, call_id)

    @app.post("/calls/{call_id}/score")
    def score(call_id: str, body: ScoreIn) -> Call:
        triage_score(
            container, call_id, Urgency(body.urgency), body.category, body.summary, body.confidence
        )
        return get_call(container, call_id)

    @app.post("/calls/{call_id}/triage-failed")
    def triage_failed(call_id: str) -> Call:
        triage_score(container, call_id, None, "unknown", None, None)
        return get_call(container, call_id)

    @app.get("/calls/{call_id}/note")
    def visit_note(call_id: str) -> dict[str, Any]:
        get_call(container, call_id)
        note = container.visit_notes.build(call_id)
        return {
            "text": note.text,
            "resident_id": note.resident_id,
            "room": note.room,
            "at": note.at,
        }

    @app.post("/calls/{call_id}/in-visit")
    def in_visit(call_id: str) -> Call:
        calls.mark_in_visit(call_id)
        return get_call(container, call_id)

    @app.post("/calls/{call_id}/resolve")
    def resolve(call_id: str, body: ResolveIn | None = None) -> Call:
        calls.resolve(call_id, by_robot=body.by_robot if body else True)
        return get_call(container, call_id)

    @app.post("/alerts/{alert_id}/ack")
    def ack(alert_id: str, body: AckIn) -> Alert:
        return ack_alert(container, alert_id, body.nurse_id)

    @app.get("/alerts")
    def list_alerts() -> list[Alert]:
        alerts = container.store.alerts.list_all()
        return sorted(alerts, key=lambda a: a.created_at, reverse=True)

    @app.get("/residents/{resident_id}/memory")
    def recall(resident_id: str, q: str = "", k: int = 3) -> list[MemoryFact]:
        return container.memory.recall(resident_id, q, k)

    @app.post("/residents/{resident_id}/memory", status_code=201)
    def remember(resident_id: str, body: MemoryIn) -> Response:
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

    @app.get("/residents/{resident_id}/memory/pending")
    def pending_memory(resident_id: str) -> list[PendingFact]:
        return container.memory_guard.pending(resident_id)

    @app.post("/residents/{resident_id}/memory/pending/{pending_id}/approve")
    def approve_memory(resident_id: str, pending_id: str) -> MemoryFact:
        return container.memory_guard.approve(pending_id, resident_id).fact

    @app.post("/residents/{resident_id}/memory/pending/{pending_id}/reject", status_code=200)
    def reject_memory(resident_id: str, pending_id: str) -> dict[str, str]:
        container.memory_guard.reject(pending_id, resident_id)
        return {"status": "rejected"}

    @app.delete("/residents/{resident_id}/memory/{fact_id}", status_code=204)
    def forget_fact(resident_id: str, fact_id: str) -> Response:
        if not container.memory_guard.forget(resident_id, fact_id):
            raise LookupError(fact_id)
        return Response(status_code=204)

    @app.delete("/residents/{resident_id}/memory")
    def forget_all(resident_id: str) -> dict[str, int]:
        return {"removed": container.memory_guard.forget_all(resident_id)}

    @app.post("/residents/{resident_id}/care", status_code=201)
    def record_care(resident_id: str, body: CareIn) -> CareEntry:
        require_resident(container, resident_id)
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

    @app.get("/residents/{resident_id}/care/summary")
    def care_summary(resident_id: str) -> dict[str, Any]:
        require_resident(container, resident_id)
        cs, now = container.care_signals, container.clock.now()
        return {
            "pain_streak_days": cs.pain_streak(resident_id, now).days,
            "mood_lower_than_usual": cs.mood_changed_from_usual(resident_id, now).changed,
            "drinks_today": cs.hydration_today(resident_id, now).drinks,
            "repeat_questions_today": cs.repeat_question_count(resident_id, now).count,
        }

    @app.get("/flags")
    def list_flags(resident_id: str | None = None, open_only: bool = True) -> list[Flag]:
        return container.care_store.flags.list(resident_id, open_only)

    @app.post("/flags/{flag_id}/resolve")
    def resolve_flag(flag_id: str) -> Flag:
        return container.care_signals.resolve_flag(flag_id)

    @app.put("/residents/{resident_id}")
    def update_resident(resident_id: str, body: ResidentIn) -> Resident:
        resident = container.store.residents.get(resident_id)
        if resident is None:
            raise LookupError(resident_id)
        resident.birth_year = body.birth_year
        container.store.residents.save(resident)
        return resident

    @app.get("/residents/{resident_id}/reminiscence")
    def reminiscence(resident_id: str, k: int = Query(3, ge=0, le=20)) -> list[ContentItem]:
        require_resident(container, resident_id)
        return container.reminiscence.items(resident_id, k)

    @app.post("/residents/{resident_id}/reminiscence/ingest", status_code=201)
    def ingest_reminiscence(resident_id: str, k: int = Query(5, ge=0, le=20)) -> list[MemoryFact]:
        require_resident(container, resident_id)
        return container.reminiscence.ingest(resident_id, k)

    @app.get("/residents/{resident_id}/preferences")
    def get_preferences(resident_id: str) -> Preferences:
        return container.preferences.get(require_resident(container, resident_id))

    @app.put("/residents/{resident_id}/preferences")
    def put_preferences(resident_id: str, body: PreferencesIn) -> Preferences:
        require_resident(container, resident_id)
        return container.preferences.update(resident_id, **body.model_dump(exclude_unset=True))

    @app.get("/residents/{resident_id}/speech-settings")
    def speech_settings(resident_id: str) -> dict[str, Any]:
        return container.preferences.speech_settings(require_resident(container, resident_id))

    @app.post("/residents/{resident_id}/family/messages", status_code=201)
    def leave_voice_note(resident_id: str, body: TextIn) -> FamilyMessage:
        return container.family.leave_voice_note(
            require_resident(container, resident_id), body.text
        )

    @app.post("/residents/{resident_id}/family/replies", status_code=201)
    def record_reply(resident_id: str, body: TextIn) -> FamilyMessage:
        return container.family.record_reply(require_resident(container, resident_id), body.text)

    @app.get("/residents/{resident_id}/family/messages")
    def family_messages(resident_id: str) -> list[FamilyMessage]:
        require_resident(container, resident_id)
        return container.care_store.messages.list(resident_id)

    @app.get("/residents/{resident_id}/postcard")
    def postcard(resident_id: str) -> dict[str, list[str]]:
        require_resident(container, resident_id)
        return {"lines": container.family.daily_postcard(resident_id, container.clock.now())}

    @app.get("/robots")
    def list_robots() -> list[Robot]:
        return container.store.robots.list_all()

    @app.put("/robots/{robot_id}")
    def report_robot(robot_id: str, body: RobotReport) -> Robot:
        robots = container.store.robots
        robot = robots.get(robot_id) or Robot(id=robot_id)
        holds_call = any(c.robot_id == robot_id for c in container.store.calls.list_open())
        # A robot with an open call stays busy: only a resolved call frees it (safer than
        # trusting a stale "idle" report). Battery and room are still applied.
        if not (holds_call and body.status is RobotStatus.IDLE):
            robot.status = body.status
        robot.battery, robot.room = body.battery, body.room
        robots.save(robot)
        return robot

    @app.get("/metrics")
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

    return app
