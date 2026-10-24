"""Regenerate the frontend contract: contracts/openapi.json and contracts/examples/*.json.

Run from backend/:  uv run python scripts/export_contract.py
"""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container

OUT = Path(__file__).resolve().parents[2] / "contracts"


def dump(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=False) + "\n")


def main() -> None:
    app = create_app(build_container(Settings(seed_demo=True, guard_timeouts=False)))
    dump(OUT / "openapi.json", json.loads(json.dumps(app.openapi())))

    c = TestClient(app)
    ex = OUT / "examples"

    tea = c.post("/calls", json={"room": "12"}).json()
    c.post(f"/calls/{tea['id']}/score", json={"urgency": 1, "category": "social"})
    c.post(f"/calls/{tea['id']}/resolve", json={})
    dump(ex / "call_resolved_by_robot.json", c.get(f"/calls/{tea['id']}").json())

    hip = c.post("/calls", json={"room": "12"}).json()
    c.post(f"/calls/{hip['id']}/turns", json={"speaker": "resident", "text": "My hip aches"})
    c.post(
        f"/calls/{hip['id']}/score",
        json={"urgency": 3, "category": "pain", "summary": "Hip pain since last night"},
    )
    dump(ex / "call_needs_nurse.json", c.get(f"/calls/{hip['id']}").json())

    fall = c.post("/calls", json={"room": "12"}).json()
    c.post(f"/calls/{fall['id']}/score", json={"urgency": 4, "category": "fall"})
    dump(ex / "alerts.json", c.get("/alerts").json())
    dump(ex / "metrics.json", c.get("/metrics").json())
    dump(ex / "calls_list.json", c.get("/calls").json())
    margaret = c.get("/residents/res_margaret/memory", params={"q": "tea please"}).json()
    dump(ex / "memory_recall.json", margaret)


if __name__ == "__main__":
    main()
