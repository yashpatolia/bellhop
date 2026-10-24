"""Fill an empty backend with the fictional home, using only its public routes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from bellhop_sim import data
from bellhop_sim.client import Backend, BackendError
from bellhop_sim.history import PastCall, earlier_today, past_calls

log = logging.getLogger("bellhop_sim")

NURSES = [
    ("nurse_okoro", "Nurse Okoro"),
    ("nurse_patel", "Nurse Patel"),
    ("nurse_lindqvist", "Nurse Lindqvist"),
]
ROBOTS = [("bellhop_1", 0.82, "dock"), ("bellhop_2", 0.64, "dock"), ("bellhop_3", 0.91, "dock")]


def iso(at: datetime) -> str:
    return at.astimezone(UTC).isoformat().replace("+00:00", "Z")


def pain_scale(value: float) -> int:
    """The dashboard's 0 to 10 pain into the backend's 1 (none) to 5 (severe)."""
    return max(1, min(5, round(value / 2)))


def seed_staff_and_robots(api: Backend) -> None:
    for nurse_id, name in NURSES:
        _create(api, "/nurses", {"id": nurse_id, "name": name})
    for robot_id, battery, room in ROBOTS:
        api.put(f"/robots/{robot_id}", {"status": "idle", "battery": battery, "room": room})


def _create(api: Backend, path: str, body: dict) -> bool:
    try:
        api.post(path, body)
        return True
    except BackendError as exc:
        if exc.status == 409:  # already there: seeding twice is harmless
            return False
        raise


def seed_resident(api: Backend, r: dict, now: datetime) -> None:
    rid = r["id"]
    created = _create(
        api,
        "/residents",
        {
            "id": rid,
            "name": r["name"],
            "room": r["room"],
            "risk_flags": data.risk_flags(r),
            "birth_year": now.year - r["age"],
        },
    )
    if not created:
        log.info("resident %s exists, leaving it alone", rid)
        return
    if data.hard_of_hearing(r):
        api.put(f"/residents/{rid}/preferences", {"hard_of_hearing": True})
    _seed_care(api, r, now)
    _seed_facts(api, r, now)
    _seed_medical(api, r, now)


def _seed_care(api: Backend, r: dict, now: datetime) -> None:
    """Seven days of mood and pain, one reading a day around 10:00."""
    for back, (mood, pain) in enumerate(zip(reversed(r["mood"]), reversed(r["pain"]), strict=True)):
        at = (now - timedelta(days=back)).replace(hour=10, minute=0, second=0, microsecond=0)
        api.post(f"/residents/{r['id']}/care", {"kind": "mood", "value": mood, "at": iso(at)})
        api.post(
            f"/residents/{r['id']}/care", {"kind": "pain", "value": pain_scale(pain), "at": iso(at)}
        )


def _seed_facts(api: Backend, r: dict, now: datetime) -> None:
    for f in r["facts"]:
        learned = now - timedelta(days=f["learned_days_ago"])
        confirmed = now - timedelta(days=f["confirmed_days_ago"])
        body = {
            "text": f["text"],
            "tags": [f["kind"]],
            "source": f["source"],
            "confidence": f["confidence"],
            "quote": f["quote"],
            "at": iso(learned),
        }
        api.request("POST", f"/residents/{r['id']}/memory", ok=(201, 202), json=body)
        if f["status"] == "pending":
            continue
        # Hearing a fact again counts it: spread the repeats from learned to last confirmed.
        repeats = max(0, f["times_seen"] - 1)
        for i in range(repeats):
            at = (
                confirmed
                if i == repeats - 1
                else learned + (confirmed - learned) * (i + 1) / (repeats)
            )
            api.request(
                "POST", f"/residents/{r['id']}/memory", ok=(201, 422), json={**body, "at": iso(at)}
            )


def _seed_medical(api: Backend, r: dict, now: datetime) -> None:
    m = r["medical"]
    api.put(
        f"/residents/{r['id']}/medical",
        {
            "conditions": m["conditions"],
            "allergies": m["allergies"],
            "medicines": m["medicines"],
            "mobility": m["mobility"],
            "diet": m["diet"],
            "last_review": iso(now - timedelta(days=m["reviewed_days_ago"])),
            "reviewed_by": m["reviewed_by"],
        },
    )


def import_call(api: Backend, c: PastCall) -> None:
    start = c.created_at
    end = start + timedelta(seconds=c.duration_s)
    gap = max(10, c.duration_s // (len(c.turns) + 1))
    first = start + timedelta(seconds=c.first_response_s)
    turns = [
        {"speaker": who, "text": text, "at": iso(first + timedelta(seconds=gap * i))}
        for i, (who, text) in enumerate(c.turns)
    ]
    api.post(
        "/calls/import",
        {
            "room": c.room,
            "resident_id": c.resident_id,
            "urgency": c.urgency,
            "category": c.category,
            "summary": c.summary,
            "robot_id": c.robot_id,
            "by_robot": c.by_robot,
            "created_at": iso(start),
            "first_response_at": iso(first),
            "resolved_at": iso(end),
            "transcript": turns,
        },
    )


def seed_home(api: Backend, now: datetime | None = None, history: bool = True) -> dict[str, int]:
    """Create the staff, robots, residents and (optionally) fourteen days of past calls."""
    now = now or datetime.now(UTC)
    seed_staff_and_robots(api)
    people = data.residents()
    for r in people:
        seed_resident(api, r, now)
    imported = 0
    if history:
        for c in [*past_calls(now), *earlier_today(now)]:
            import_call(api, c)
            imported += 1
    return {"residents": len(people), "calls": imported}
