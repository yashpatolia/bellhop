"""HTTP API: thin routes, each delegating to one service method."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from bellhop.api.deps import AlertNotFound, ack_alert, get_call
from bellhop.container import Container
from bellhop.domain import Alert, Call, InvalidTransition, MemoryFact, Robot, RobotStatus, Urgency
from bellhop.services.call_service import CallNotFound


class RaiseCall(BaseModel):
    room: str


class TurnIn(BaseModel):
    speaker: str
    text: str


class ScoreIn(BaseModel):
    urgency: int = Field(ge=1, le=4)
    category: str
    summary: str | None = None


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


def _error(status: int):
    async def handler(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return handler


def create_app(container: Container) -> FastAPI:
    app = FastAPI(title="Bellhop")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    app.add_exception_handler(CallNotFound, _error(404))
    app.add_exception_handler(AlertNotFound, _error(404))
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
        calls.score(call_id, Urgency(body.urgency), body.category, body.summary)
        return get_call(container, call_id)

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
        return list(reversed(container.notifier.sent))

    @app.get("/residents/{resident_id}/memory")
    def recall(resident_id: str, q: str = "", k: int = 3) -> list[MemoryFact]:
        return container.memory.recall(resident_id, q, k)

    @app.post("/residents/{resident_id}/memory", status_code=201)
    def remember(resident_id: str, body: MemoryIn) -> MemoryFact:
        return container.memory.remember(resident_id, body.text, body.tags)

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
