"""One bell press, played end to end the way the real robot would: arrive, talk, score, wait."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from bellhop_sim.client import Backend, BackendError
from bellhop_sim.data import Scenario
from bellhop_sim.fleet import Fleet

log = logging.getLogger("bellhop_sim")


class Pace:
    """Scales every wait: speed 1 is realistic, 10 is ten times faster, 0 never waits."""

    def __init__(self, speed: float = 1.0, sleep: Callable[[float], None] = time.sleep) -> None:
        self.speed = speed
        self._sleep = sleep

    def wait(self, seconds: float) -> None:
        if self.speed > 0 and seconds > 0:
            self._sleep(seconds / self.speed)


@dataclass(frozen=True)
class VisitOptions:
    nurse_delay_s: float = (
        240.0  # a nurse acknowledges after this long; 0 leaves it to the dashboard
    )
    travel_s: tuple[float, float] = (6.0, 12.0)
    turn_gap_s: tuple[float, float] = (3.0, 5.0)
    poll_s: float = 2.0


DEFAULT_OPTS = VisitOptions()


def _nurse_for(api: Backend, call_id: str) -> str | None:
    for alert in api.get("/alerts"):
        if alert["call_id"] == call_id and alert["nurse_id"]:
            return alert["nurse_id"]
    nurses = [n for n in api.get("/nurses") if n["on_shift"]]
    return nurses[0]["id"] if nurses else None


def _alert_ids(api: Backend, call_id: str) -> list[str]:
    return [a["id"] for a in api.get("/alerts") if a["call_id"] == call_id and not a["acked_at"]]


def _wait_for_nurse(api: Backend, call_id: str, pace: Pace, opts: VisitOptions) -> None:
    """Hold with the resident until a nurse acknowledges (or, if configured, one does for us)."""
    waited = 0.0
    while True:
        status = api.get(f"/calls/{call_id}")["status"]
        if status in ("nurse_acked", "resolved", "closed"):
            return
        if opts.nurse_delay_s and waited >= opts.nurse_delay_s:
            nurse = _nurse_for(api, call_id)
            for alert_id in _alert_ids(api, call_id)[:1]:
                if nurse:
                    api.request(
                        "POST", f"/alerts/{alert_id}/ack", ok=(200, 409), json={"nurse_id": nurse}
                    )
            return
        pace.wait(opts.poll_s)
        waited += opts.poll_s


def _nurse_takes_it(
    api: Backend,
    call_id: str,
    scenario: Scenario,
    pace: Pace,
    rng: random.Random,
    opts: VisitOptions,
) -> None:
    """No robot came, so a nurse handled the bell: they say what it was, then close it."""
    try:
        api.post(
            f"/calls/{call_id}/score",
            {
                "urgency": scenario.urgency,
                "category": scenario.category,
                "summary": scenario.summary,
            },
        )
        pace.wait(opts.nurse_delay_s + rng.uniform(0, 30))
        api.request("POST", f"/calls/{call_id}/resolve", ok=(200, 409), json={"by_robot": False})
    except BackendError as exc:
        log.warning("%s: %s", call_id, exc)


def play_call(
    api: Backend,
    fleet: Fleet,
    pace: Pace,
    rng: random.Random,
    resident: dict,
    scenario: Scenario,
    opts: VisitOptions = DEFAULT_OPTS,
    on_ring: Callable[[str], None] | None = None,
) -> str | None:
    """Press the bell, then act as the robot. Returns the call id."""
    call = api.post("/calls", {"room": resident["room"]})
    if on_ring:
        on_ring(call["id"])
    return attend(api, fleet, pace, rng, call, resident, scenario, opts)


def attend(
    api: Backend,
    fleet: Fleet,
    pace: Pace,
    rng: random.Random,
    call: dict,
    resident: dict,
    scenario: Scenario,
    opts: VisitOptions = DEFAULT_OPTS,
) -> str | None:
    """Act as the robot for a call that already exists (a bell, or one rung from the dashboard)."""
    call_id = call["id"]
    robot_id = call.get("robot_id")
    log.info(
        "bell %s room %s (%s, level %d)",
        call_id,
        resident["room"],
        scenario.category,
        scenario.urgency,
    )
    if robot_id is None:
        log.info("%s: no robot free, a nurse owns it", call_id)
        if opts.nurse_delay_s:
            _nurse_takes_it(api, call_id, scenario, pace, rng, opts)
        return call_id

    fleet.set(robot_id, status="busy", room="hall")
    pace.wait(rng.uniform(*opts.travel_s))
    fleet.set(robot_id, room=resident["room"])
    api.request("POST", f"/calls/{call_id}/in-visit", ok=(200, 201))

    scored = False
    for who, text in scenario.turns:
        pace.wait(rng.uniform(*opts.turn_gap_s))
        api.post(f"/calls/{call_id}/turns", {"speaker": who, "text": text})
        if not scored and who == "resident":
            api.post(
                f"/calls/{call_id}/score",
                {
                    "urgency": scenario.urgency,
                    "category": scenario.category,
                    "summary": scenario.summary,
                    "confidence": round(rng.uniform(0.72, 0.97), 2),
                },
            )
            scored = True
    _record_care(api, resident, scenario, call_id, rng)

    try:
        if scenario.urgency >= 3:
            _wait_for_nurse(api, call_id, pace, opts)
            pace.wait(rng.uniform(2, 5))
        api.request(
            "POST",
            f"/calls/{call_id}/resolve",
            ok=(200, 409),
            json={"by_robot": scenario.urgency < 3},
        )
    except BackendError as exc:
        log.warning("%s: %s", call_id, exc)
    fleet.finish_call(robot_id)
    return call_id


def _record_care(
    api: Backend, resident: dict, scenario: Scenario, call_id: str, rng: random.Random
) -> None:
    rid = resident["id"]
    if not rid:
        return  # a place with no resident (the lobby): nothing to record
    if scenario.category in ("pain", "breathing", "fall"):
        api.post(
            f"/residents/{rid}/care",
            {"kind": "pain", "value": rng.choice([3, 4]), "call_id": call_id},
        )
    elif scenario.category == "comfort item":
        api.post(f"/residents/{rid}/care", {"kind": "drink", "call_id": call_id})
    elif scenario.category == "chat":
        api.post(
            f"/residents/{rid}/care",
            {"kind": "mood", "value": rng.choice([3, 4]), "call_id": call_id},
        )
