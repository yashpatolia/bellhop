"""The simulated robots: what each one reports to the backend, and how its battery moves."""

from __future__ import annotations

import threading
from dataclasses import dataclass

LOW_BATTERY = 0.25  # heads for the dock below this
FULL_BATTERY = 0.95
DRAIN_PER_CALL = 0.03
CHARGE_PER_TICK = 0.02


@dataclass
class SimRobot:
    id: str
    battery: float
    room: str = "dock"
    status: str = "idle"  # idle | busy | charging | fault


class Fleet:
    def __init__(self, robots: list[SimRobot]) -> None:
        self._robots = {r.id: r for r in robots}
        self._lock = threading.Lock()

    def snapshot(self) -> list[SimRobot]:
        with self._lock:
            return [SimRobot(r.id, r.battery, r.room, r.status) for r in self._robots.values()]

    def set(self, robot_id: str, *, status: str | None = None, room: str | None = None) -> None:
        with self._lock:
            r = self._robots[robot_id]
            r.status = status or r.status
            r.room = room or r.room

    def finish_call(self, robot_id: str) -> None:
        """The robot is done with a resident: it uses some battery and stands by (or docks)."""
        with self._lock:
            r = self._robots[robot_id]
            r.battery = max(0.0, round(r.battery - DRAIN_PER_CALL, 3))
            r.status = "charging" if r.battery < LOW_BATTERY else "idle"
            r.room = "dock" if r.status == "charging" else r.room

    def tick(self) -> None:
        """One heartbeat of battery physics: charging robots fill up and go back on duty."""
        with self._lock:
            for r in self._robots.values():
                if r.status == "charging":
                    r.battery = min(1.0, round(r.battery + CHARGE_PER_TICK, 3))
                    if r.battery >= FULL_BATTERY:
                        r.status = "idle"
