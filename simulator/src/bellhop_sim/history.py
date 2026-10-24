"""Past calls for the fourteen days before today, with a pattern per resident.

Pure: given a base time and a seed it returns the same list every time, so the tendencies the
dashboard finds (repeated reasons, a regular time window) are the ones written here.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from bellhop_sim import data

DAYS = 14


@dataclass(frozen=True)
class PastCall:
    resident_id: str
    room: str
    category: str
    urgency: int
    summary: str
    turns: tuple[tuple[str, str], ...]
    created_at: datetime
    first_response_s: int
    duration_s: int
    robot_id: str
    by_robot: bool


def _local_hour(day: datetime, hour: int, minute: int) -> datetime:
    return day.replace(hour=hour % 24, minute=minute, second=0, microsecond=0)


def past_calls(now: datetime, seed: int = 7) -> list[PastCall]:
    rng = random.Random(seed)
    homes = {r["id"]: r for r in data.residents()}
    out: list[PastCall] = []
    for idx, (resident_id, plan) in enumerate(sorted(data.patterns().items())):
        resident = homes.get(resident_id)
        if resident is None:
            continue
        for p, (category, count, hour_from, hour_to) in enumerate(plan):
            options = data.scenarios_for(category)
            span = max(1, hour_to - hour_from)
            for k in range(count):
                day = 1 + ((k * 2 + idx + p * 5) % DAYS)
                at = _local_hour(
                    (now - timedelta(days=day)).astimezone(),
                    hour_from + (k * 7) % span,
                    (k * 17 + idx * 11) % 60,
                )
                s = options[k % len(options)]
                out.append(
                    PastCall(
                        resident_id=resident_id,
                        room=resident["room"],
                        category=s.category,
                        urgency=s.urgency,
                        summary=s.summary,
                        turns=s.turns,
                        created_at=at,
                        first_response_s=rng.randint(35, 140),
                        duration_s=rng.randint(2, 9) * 60,
                        robot_id=f"bellhop_{1 + k % 3}",
                        by_robot=s.urgency <= 2,
                    )
                )
    return sorted(out, key=lambda c: c.created_at)


def earlier_today(now: datetime, seed: int = 11) -> list[PastCall]:
    """A couple of hours of calls already resolved today, for the 'earlier today' list."""
    rng = random.Random(seed)
    people = data.residents()
    options = [s for s in data.scenarios() if s.urgency <= 3]
    out: list[PastCall] = []
    for i, minutes in enumerate([11, 24, 38, 55, 71, 96, 118, 142, 170, 201, 233]):
        resident = people[(i * 5) % len(people)]
        s = options[(i * 3 + 1) % len(options)]
        at = now - timedelta(minutes=minutes)
        if at.date() != now.date():
            continue
        out.append(
            PastCall(
                resident_id=resident["id"],
                room=resident["room"],
                category=s.category,
                urgency=s.urgency,
                summary=s.summary,
                turns=s.turns,
                created_at=at,
                first_response_s=rng.randint(35, 140),
                duration_s=rng.randint(2, 9) * 60,
                robot_id=f"bellhop_{1 + i % 3}",
                by_robot=s.urgency <= 2,
            )
        )
    return sorted(out, key=lambda c: c.created_at)
