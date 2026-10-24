"""Demo data: residents, nurses, one robot and the facts behind the three demo scenes."""

from __future__ import annotations

from typing import Any

from bellhop.domain import Nurse, Resident, Robot
from bellhop.services.memory_service import MemoryService


def seed_demo(store: Any, memory: MemoryService) -> None:
    """`store` exposes `residents`, `nurses` and `robots` repositories (e.g. InMemoryStore)."""
    margaret = Resident(
        id="res_margaret", name="Margaret", room="12", risk_flags={"falls"}, birth_year=1938
    )
    arthur = Resident(id="res_arthur", name="Arthur", room="14")
    for resident in (margaret, arthur):
        store.residents.save(resident)
    for nurse in (Nurse(id="nurse_priya", name="Priya"), Nurse(id="nurse_sam", name="Sam")):
        store.nurses.save(nurse)
    store.robots.save(Robot(id="robot_1", room="lobby"))

    memory.remember(margaret.id, "Takes her tea with two sugars", tags=["tea", "preferences"])
    memory.remember(
        margaret.id,
        "Her grandson Tom is studying to be a vet and visits on Sundays",
        tags=["family", "grandson"],
    )
    memory.remember(
        margaret.id,
        "History of left hip pain since her hip replacement in 2023",
        tags=["health", "hip", "pain"],
    )
    memory.remember(arthur.id, "Likes his coffee black and reads the paper at breakfast")
    memory.remember(arthur.id, "His daughter Ruth phones on Wednesdays", tags=["family"])
