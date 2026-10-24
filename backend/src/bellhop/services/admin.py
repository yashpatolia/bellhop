"""Create and edit residents and nurses, so a system can be set up without seed data."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from bellhop.domain import Nurse, Resident
from bellhop.ports import (
    CallRepository,
    Clock,
    IdGenerator,
    NurseRepository,
    ResidentRepository,
    RobotRepository,
)

Flag = Annotated[str, Field(min_length=1, max_length=32)]
_Id = Annotated[str, Field(min_length=1, max_length=64)]
_Name = Annotated[str, Field(min_length=1, max_length=80)]
_Room = Annotated[str, Field(min_length=1, max_length=32)]


class ResidentNotFound(LookupError):
    pass


class NurseNotFound(LookupError):
    pass


class Conflict(ValueError):
    """Duplicate id or a room already occupied by another resident."""


class ResidentFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: _Name
    room: _Room
    risk_flags: Annotated[list[Flag], Field(max_length=10)] = Field(default_factory=list)
    birth_year: int | None = None


class NurseFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: _Name
    on_shift: bool = True


class _IdOnly(BaseModel):
    id: _Id


class AdminService:
    def __init__(
        self,
        residents: ResidentRepository,
        nurses: NurseRepository,
        robots: RobotRepository,
        calls: CallRepository,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._residents = residents
        self._nurses = nurses
        self._robots = robots
        self._calls = calls
        self._clock = clock
        self._ids = ids

    # residents
    def create_resident(
        self,
        id: str | None,
        name: str,
        room: str,
        risk_flags: Iterable[str] = (),
        birth_year: int | None = None,
    ) -> Resident:
        fields = ResidentFields(
            name=name, room=room, risk_flags=list(risk_flags), birth_year=birth_year
        )
        rid = _IdOnly(id=id).id if id is not None else self._ids.new_id("res")
        if self._residents.get(rid):
            raise Conflict(f"resident {rid} already exists")
        self._check_room(fields.room, rid)
        resident = Resident(
            id=rid,
            name=fields.name,
            room=fields.room,
            risk_flags=set(fields.risk_flags),
            birth_year=fields.birth_year,
        )
        self._residents.save(resident)
        return resident

    def update_resident(self, id: str, /, **fields: Any) -> Resident:
        resident = self.get_resident(id)
        unknown = set(fields) - set(ResidentFields.model_fields)
        if unknown:
            raise ValueError(f"unknown resident fields: {sorted(unknown)}")
        current = {
            "name": resident.name,
            "room": resident.room,
            "risk_flags": sorted(resident.risk_flags),
            "birth_year": resident.birth_year,
        }
        merged = ResidentFields(**{**current, **fields})
        self._check_room(merged.room, id)
        updated = resident.model_copy(
            update={
                "name": merged.name,
                "room": merged.room,
                "risk_flags": set(merged.risk_flags),
                "birth_year": merged.birth_year,
            }
        )
        self._residents.save(updated)
        return updated

    def list_residents(self) -> list[Resident]:
        return self._residents.list_all()

    def get_resident(self, id: str) -> Resident:
        resident = self._residents.get(id)
        if resident is None:
            raise ResidentNotFound(f"resident {id} not found")
        return resident

    def _check_room(self, room: str, resident_id: str) -> None:
        other = self._residents.by_room(room)
        if other is not None and other.id != resident_id:
            raise Conflict(f"room {room} is already occupied by resident {other.id}")

    # nurses
    def create_nurse(self, id: str | None, name: str, on_shift: bool = True) -> Nurse:
        fields = NurseFields(name=name, on_shift=on_shift)
        nid = _IdOnly(id=id).id if id is not None else self._ids.new_id("nurse")
        if self._nurses.get(nid):
            raise Conflict(f"nurse {nid} already exists")
        nurse = Nurse(id=nid, name=fields.name, on_shift=fields.on_shift)
        self._nurses.save(nurse)
        return nurse

    def update_nurse(self, id: str, name: str | None = None, on_shift: bool | None = None) -> Nurse:
        nurse = self._nurses.get(id)
        if nurse is None:
            raise NurseNotFound(f"nurse {id} not found")
        fields = NurseFields(
            name=nurse.name if name is None else name,
            on_shift=nurse.on_shift if on_shift is None else on_shift,
        )
        updated = nurse.model_copy(update={"name": fields.name, "on_shift": fields.on_shift})
        self._nurses.save(updated)  # open_tasks stays as it was
        return updated

    def list_nurses(self) -> list[Nurse]:
        return self._nurses.list_all()
