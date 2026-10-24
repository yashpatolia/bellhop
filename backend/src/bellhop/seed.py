"""Demo data: a thin wrapper that applies `scenarios/demo.json` (see `bellhop.scenarios`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bellhop.scenarios import apply_scenario, load_scenario
from bellhop.services.memory_service import MemoryService

DEMO_SCENARIO = Path(__file__).resolve().parents[2] / "scenarios" / "demo.json"


def seed_demo(store: Any, memory: MemoryService) -> None:
    """`store` exposes `residents`, `nurses` and `robots` repositories (e.g. InMemoryStore)."""
    apply_scenario(load_scenario(DEMO_SCENARIO), store, memory, None)
