"""The running home: random bell presses, robot heartbeats and named scenes."""

from __future__ import annotations

import logging
import random
import threading
import time
from datetime import datetime

from bellhop_sim import data
from bellhop_sim.client import Backend, BackendError
from bellhop_sim.fleet import Fleet, SimRobot
from bellhop_sim.seeding import ROBOTS
from bellhop_sim.visit import DEFAULT_OPTS, Pace, VisitOptions, attend, play_call

log = logging.getLogger("bellhop_sim")

HEARTBEAT_S = 2.0
LEVEL_WEIGHTS = {1: 55, 2: 20, 3: 20, 4: 5}  # how often each urgency level rings

# Named bursts. Each entry is (category, resident id, how many seconds after the start).
SCENES: dict[str, list[tuple[str, str, float]]] = {
    "busy": [
        ("breathing", "r104", 0),
        ("pain", "r101", 3),
        ("medication", "r106", 6),
        ("chat", "r105", 9),
        ("toileting", "r108", 12),
    ],
    "emergency": [("fall", "r103", 0)],
    "quiet": [],
}


def pick_scenario(rng: random.Random, category: str | None = None) -> data.Scenario:
    if category:
        options = data.scenarios_for(category)
        if not options:
            raise ValueError(f"no scenario for category {category!r}")
        return rng.choice(options)
    scenarios = data.scenarios()
    weights = [
        LEVEL_WEIGHTS[s.urgency] / sum(1 for x in scenarios if x.urgency == s.urgency)
        for s in scenarios
    ]
    return rng.choices(scenarios, weights)[0]


def new_fleet() -> Fleet:
    return Fleet([SimRobot(rid, battery, room) for rid, battery, room in ROBOTS])


class Home:
    def __init__(
        self,
        api: Backend,
        pace: Pace,
        rng: random.Random,
        fleet: Fleet | None = None,
        opts: VisitOptions = DEFAULT_OPTS,
    ) -> None:
        self.api, self.pace, self.rng, self.opts = api, pace, rng, opts
        self.fleet = fleet or new_fleet()
        self._busy: set[str] = set()  # residents with a call in progress
        self._played: set[str] = set()  # calls this simulator rang or has taken over
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.threads: list[threading.Thread] = []
        self._heartbeat: threading.Thread | None = None

    # -- robots ---------------------------------------------------------------------------
    def heartbeat(self) -> None:
        """Report every robot to the backend once, then let batteries move."""
        for r in self.fleet.snapshot():
            try:
                self.api.put(
                    f"/robots/{r.id}",
                    {"status": r.status, "battery": r.battery, "room": r.room},
                )
            except BackendError as exc:
                log.warning("heartbeat for %s failed: %s", r.id, exc)
        self.fleet.tick()

    def start(self) -> None:
        """Begin reporting the robots every couple of seconds."""
        if self._heartbeat is None:
            self._heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self._heartbeat.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            self.heartbeat()
            try:
                self.adopt()
            except BackendError as exc:
                log.warning("could not look for new calls: %s", exc)
            self._stop.wait(HEARTBEAT_S)

    # -- calls ----------------------------------------------------------------------------
    def press(self, resident: dict, scenario: data.Scenario) -> bool:
        """Ring one resident's bell on a background thread. False if they are already mid call."""
        with self._lock:
            if resident["id"] in self._busy:
                return False
            self._busy.add(resident["id"])

        def run() -> None:
            try:
                play_call(
                    self.api,
                    self.fleet,
                    self.pace,
                    self.rng,
                    resident,
                    scenario,
                    self.opts,
                    self._remember,
                )
            except Exception:
                log.exception("call for %s failed", resident["id"])
            finally:
                with self._lock:
                    self._busy.discard(resident["id"])

        t = threading.Thread(target=run, daemon=True)
        t.start()
        self.threads.append(t)
        return True

    def _remember(self, call_id: str) -> None:
        with self._lock:
            self._played.add(call_id)

    def adopt(self, min_age_s: float = 3.0) -> int:
        """Play the visit for calls somebody else rang (the dashboard's "send a robot") when a
        simulated robot was sent. Returns how many were taken."""
        ids = {r.id for r in self.fleet.snapshot()}
        taken = 0
        now = time.time()
        for call in self.api.get("/calls", params={"limit": 50}):
            if (
                call["status"] not in ("assigned", "robot_en_route")
                or call.get("robot_id") not in ids
            ):
                continue
            with self._lock:
                if call["id"] in self._played:
                    continue
                age = now - datetime.fromisoformat(call["created_at"]).timestamp()
                if age < min_age_s:
                    continue  # still being played by the thread that rang it
                self._played.add(call["id"])
            resident = next(
                (r for r in data.residents() if r["id"] == call.get("resident_id")), None
            )
            if resident is None:
                resident = {"id": "", "room": call["room"], "name": "", "flags": []}
            scenario = pick_scenario(self.rng, "chat" if self.rng.random() < 0.5 else None)
            t = threading.Thread(target=self._attend, args=(call, resident, scenario), daemon=True)
            t.start()
            self.threads.append(t)
            taken += 1
        return taken

    def _attend(self, call: dict, resident: dict, scenario: data.Scenario) -> None:
        try:
            attend(self.api, self.fleet, self.pace, self.rng, call, resident, scenario, self.opts)
        except Exception:
            log.exception("call %s failed", call["id"])

    def resident(self, resident_id: str | None = None) -> dict:
        people = data.residents()
        if resident_id:
            return next(r for r in people if r["id"] == resident_id or r["room"] == resident_id)
        with self._lock:
            free = [r for r in people if r["id"] not in self._busy]
        return self.rng.choice(free or people)

    def scene(self, name: str) -> None:
        """Start a named burst of calls (the timings are scaled by the pace)."""
        if name not in SCENES:
            raise ValueError(f"unknown scene {name!r}; choose from {', '.join(SCENES)}")
        start = time.monotonic()
        for category, resident_id, at in SCENES[name]:
            self.pace.wait(max(0.0, at - (time.monotonic() - start) * max(self.pace.speed, 1)))
            self.press(self.resident(resident_id), pick_scenario(self.rng, category))

    # -- the loop -------------------------------------------------------------------------
    def run(self, rate_per_min: float = 1.5, duration_s: float | None = None) -> None:
        """Ring bells at random (Poisson) until stopped, with the robots reporting in."""
        self.start()
        deadline = None if duration_s is None else time.monotonic() + duration_s
        try:
            while not self._stop.is_set() and (deadline is None or time.monotonic() < deadline):
                if rate_per_min > 0:
                    self.pace.wait(self.rng.expovariate(rate_per_min / 60.0))
                    self.press(self.resident(), pick_scenario(self.rng))
                else:
                    self._stop.wait(1.0)
        except KeyboardInterrupt:
            log.info("stopping")
        finally:
            self._stop.set()

    def stop(self) -> None:
        self._stop.set()

    def join(self, timeout: float = 5.0) -> None:
        for t in self.threads:
            t.join(timeout)
