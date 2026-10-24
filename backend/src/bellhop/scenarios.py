"""Scenario files: the residents, nurses, robots and facts a system starts with.

`load_scenario` validates (unknown keys, duplicate ids and clashing rooms are errors);
`apply_scenario` writes it through the repositories and `MemoryService`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from bellhop.domain import Nurse, Resident, Robot, RobotStatus
from bellhop.domain.care import Preferences
from bellhop.services.admin import Flag, ResidentFields
from bellhop.services.memory_service import MemoryService

_Id = Annotated[str, Field(min_length=1, max_length=64)]
_PREF_FIELDS = frozenset(Preferences.model_fields) - {"resident_id"}


class ScenarioError(ValueError):
    """The scenario is missing, not JSON, or invalid; the message says what to fix."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FactSpec(_Strict):
    text: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)


class ResidentSpec(ResidentFields):
    id: _Id
    risk_flags: Annotated[list[Flag], Field(max_length=10)] = Field(default_factory=list)
    facts: list[FactSpec] = Field(default_factory=list)
    preferences: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _check_preferences(self) -> ResidentSpec:
        if self.preferences is not None:
            unknown = set(self.preferences) - _PREF_FIELDS
            if unknown:
                raise ValueError(f"unknown preferences fields: {sorted(unknown)}")
            Preferences.model_validate({**self.preferences, "resident_id": self.id}, strict=True)
        return self


class NurseSpec(_Strict):
    id: _Id
    name: str = Field(min_length=1, max_length=80)
    on_shift: bool = True


class RobotSpec(_Strict):
    id: _Id
    status: RobotStatus = RobotStatus.IDLE
    battery: float = Field(default=1.0, ge=0, le=1)
    room: str | None = None


class Scenario(_Strict):
    residents: list[ResidentSpec] = Field(default_factory=list)
    nurses: list[NurseSpec] = Field(default_factory=list)
    robots: list[RobotSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique(self) -> Scenario:
        for kind, items in (
            ("resident", self.residents),
            ("nurse", self.nurses),
            ("robot", self.robots),
        ):
            seen: set[str] = set()
            for item in items:
                if item.id in seen:
                    raise ValueError(f"duplicate {kind} id: {item.id}")
                seen.add(item.id)
        rooms: dict[str, str] = {}
        for r in self.residents:
            if r.room in rooms:
                raise ValueError(f"room {r.room} is used by both {rooms[r.room]} and {r.id}")
            rooms[r.room] = r.id
        return self


def _describe(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        where = ".".join(str(p) for p in err["loc"])
        parts.append(f"{where}: {err['msg']}" if where else err["msg"])
    return "; ".join(parts)


def load_scenario(source: str | Path | dict[str, Any]) -> Scenario:
    if isinstance(source, dict):
        data: Any = source
        origin = "scenario"
    else:
        path = Path(source)
        origin = str(path)
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise ScenarioError(f"scenario file not found: {path}") from None
        except OSError as exc:
            raise ScenarioError(f"scenario file unreadable: {path} ({exc.strerror})") from None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ScenarioError(f"{origin} is not valid JSON: {exc}") from None
        if not isinstance(data, dict):
            raise ScenarioError(f"{origin} must be a JSON object at the top level")
    try:
        return Scenario.model_validate(data)
    except ValidationError as exc:
        raise ScenarioError(f"invalid {origin}: {_describe(exc)}") from None


def apply_scenario(scenario: Scenario, store: Any, memory: MemoryService, care_store: Any) -> None:
    """`store` has `residents`, `nurses`, `robots` repositories; `care_store` holds preferences."""
    for spec in scenario.residents:
        store.residents.save(
            Resident(
                id=spec.id,
                name=spec.name,
                room=spec.room,
                risk_flags=set(spec.risk_flags),
                birth_year=spec.birth_year,
            )
        )
    for nurse in scenario.nurses:
        store.nurses.save(Nurse(id=nurse.id, name=nurse.name, on_shift=nurse.on_shift))
    for robot in scenario.robots:
        store.robots.save(Robot(**robot.model_dump()))
    for spec in scenario.residents:
        for fact in spec.facts:
            memory.remember(spec.id, fact.text, tags=fact.tags)
        if spec.preferences is not None:
            if care_store is None:
                raise ScenarioError(f"preferences for {spec.id} need a care store")
            care_store.preferences.save(
                Preferences.model_validate(
                    {**spec.preferences, "resident_id": spec.id}, strict=True
                )
            )
