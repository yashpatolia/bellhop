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
    container = build_container(Settings(seed_demo=True, guard_timeouts=False))
    app = create_app(container)
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

    c.post(f"/calls/{tea['id']}/override", json={"urgency": 3, "nurse_id": "nurse_priya"})
    dump(ex / "call_override.json", c.get(f"/calls/{tea['id']}").json())
    dump(ex / "labelled_examples.json", c.get("/labelled-examples").json())

    fall = c.post("/calls", json={"room": "12"}).json()
    c.post(f"/calls/{fall['id']}/score", json={"urgency": 4, "category": "fall"})
    dump(ex / "alerts.json", c.get("/alerts").json())
    dump(ex / "metrics.json", c.get("/metrics").json())
    dump(ex / "calls_list.json", c.get("/calls").json())
    dump(ex / "robots.json", c.get("/robots").json())
    margaret = c.get("/residents/res_margaret/memory", params={"q": "tea please"}).json()
    dump(ex / "memory_recall.json", margaret)

    r = "/residents/res_margaret"
    c.post(f"{r}/care", json={"kind": "mood", "value": 5, "note": "enjoyed bingo"})
    c.post(f"{r}/care", json={"kind": "drink", "note": "tea"})
    c.post(f"{r}/care", json={"kind": "pain", "value": 3, "note": "knee"})
    dump(ex / "care_summary.json", c.get(f"{r}/care/summary").json())
    dump(ex / "postcard.json", c.get(f"{r}/postcard").json())
    c.put(f"{r}/preferences", json={"hard_of_hearing": True})
    dump(ex / "speech_settings.json", c.get(f"{r}/speech-settings").json())
    container.care_signals.raise_flag("res_margaret", "pain", "pain mentioned 3 days in a row")
    dump(ex / "flags.json", c.get("/flags").json())
    dump(ex / "reminiscence.json", c.get(f"{r}/reminiscence", params={"k": 3}).json())
    c.post(f"{r}/memory", json={"text": "Has a grandson named Theo", "confidence": 0.3})
    dump(ex / "memory_pending.json", c.get(f"{r}/memory/pending").json())


if __name__ == "__main__":
    main()
