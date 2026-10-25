"""Robot status reporter: every few seconds PUT /robots/{id} with status, battery, room and target.

The values come from the Pi drive server's GET /snapshot. If that server is down the last known
battery, room and target are repeated, and after FAULT_AFTER_FAILURES misses in a row the robot
reports "fault" so dispatch stops sending it calls. Undervoltage right now (snapshot "power") is
also a fault; weaker power flags only warn in the log. The backend receives the operational state;
power details remain local. Nothing here may crash the visit loop.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import httpx

from rover import config, obslog
from rover.backend import Backend
from rover.power import FLAG_BITS, power_health

FAULT_AFTER_FAILURES = 3  # misses in a row (about 15 s) before reporting fault

Snapshot = dict[str, Any]
SnapshotFetcher = Callable[[], Snapshot | None]


def fetch_snapshot(base_url: str | None = None) -> Snapshot | None:
    """GET /snapshot from the Pi drive server; None when it is down or answers badly."""
    url = (base_url or config.PI_SERVER_URL).rstrip("/") + "/snapshot"
    try:
        response = httpx.get(url, timeout=config.LOCAL_HTTP_TIMEOUT_S)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"status: GET {url} failed: {type(exc).__name__}: {exc}")
        obslog.event("status.snapshot_failed", error=type(exc).__name__)
        return None
    return data if isinstance(data, dict) else None


def _battery(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class StatusReporter:
    def __init__(
        self,
        backend: Backend,
        fetch: SnapshotFetcher = fetch_snapshot,
        robot_id: str = config.ROBOT_ID,
        interval_s: float = config.HEARTBEAT_S,
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        self.backend = backend
        self.fetch = fetch
        self.robot_id = robot_id
        self.interval_s = interval_s
        self.wait = wait  # wait(seconds) -> True when asked to stop; defaults to stop.wait
        self.failures = 0
        self.battery: float | None = None
        self.room: str | None = None
        self.status = "idle"
        self.target: str | None = None
        self.power_health = "ok"

    def _read(self) -> None:
        try:
            snapshot = self.fetch()
        except Exception as exc:  # a bad fetcher counts as a miss
            print(f"status: snapshot crashed: {exc!r}")
            snapshot = None
        if snapshot is None:
            self.failures += 1
            if self.failures >= FAULT_AFTER_FAILURES:
                self.status = "fault"
            return
        self.failures = 0
        self.battery = _battery(snapshot.get("battery"))
        room = snapshot.get("room")
        self.room = room if isinstance(room, str) and room else None
        target = snapshot.get("target")
        self.target = target if isinstance(target, str) and target else None
        if snapshot.get("charging") is True:
            self.status = "charging"
        elif snapshot.get("moving") is True or snapshot.get("following") is True:
            self.status = "busy"
        else:
            self.status = "idle"
        self._check_power(snapshot)

    def _check_power(self, snapshot: Snapshot) -> None:
        """Undervoltage right now is a fault (dispatch must not send a browning-out robot);
        earlier flags only warn. The extra detail goes to the log, never to the backend."""
        power = snapshot.get("power")
        power = power if isinstance(power, dict) else None
        self.power_health = power_health(power)
        if self.power_health == "ok":
            return
        if self.power_health == "fault":
            self.status = "fault"
        obslog.event(
            "status.power",
            robot_id=self.robot_id,
            health=self.power_health,
            flags=[name for name in FLAG_BITS if power and power.get(name)],
            wifi_rssi_dbm=snapshot.get("wifi_rssi_dbm"),
        )

    def report_once(self) -> None:
        try:
            self._read()
            obslog.event(
                "status.report",
                robot_id=self.robot_id,
                status=self.status,
                battery=self.battery,
                room=self.room,
                target=self.target,
                failures=self.failures,
            )
            self.backend.report_robot(
                self.robot_id, self.status, self.battery, self.room, self.target
            )
        except Exception as exc:  # never let a reporting bug reach the visit loop
            print(f"status: report failed: {exc!r}")

    def run(self, stop: threading.Event) -> None:
        wait = self.wait or stop.wait
        while not stop.is_set():
            self.report_once()
            if wait(self.interval_s):
                return

    def start(self, stop: threading.Event) -> threading.Thread:
        thread = threading.Thread(target=self.run, args=(stop,), daemon=True, name="status")
        thread.start()
        return thread
