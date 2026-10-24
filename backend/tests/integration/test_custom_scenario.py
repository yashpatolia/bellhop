"""A different home, loaded from a scenario file: the engine works with unseen data."""

import json

from bellhop.container import Settings, build_container
from bellhop.domain import CallStatus, Urgency

HOME = {
    "residents": [
        {
            "id": "res_ines",
            "name": "Ines",
            "room": "301",
            "birth_year": 1945,
            "facts": [{"text": "Loves jasmine tea in the afternoon", "tags": ["tea"]}],
        },
        {"id": "res_omar", "name": "Omar", "room": "302", "risk_flags": ["falls"]},
    ],
    "nurses": [{"id": "nurse_lena", "name": "Lena"}],
    "robots": [{"id": "bot_a", "room": "hall"}, {"id": "bot_b", "room": "hall"}],
}


def test_call_end_to_end_on_custom_scenario(tmp_path):
    path = tmp_path / "home.json"
    path.write_text(json.dumps(HOME))
    app = build_container(Settings(seed_file=str(path)))

    call = app.call_service.raise_call("302")
    stored = app.store.calls.get(call.id)
    assert stored.resident_id == "res_omar"
    assert stored.status is CallStatus.ROBOT_EN_ROUTE
    assert stored.robot_id in {"bot_a", "bot_b"}
    assert [c for c in app.gateway.commands if c[0] == "go_to"] == [
        ("go_to", stored.robot_id, "302")
    ]

    app.call_service.mark_in_visit(call.id)
    app.call_service.score(call.id, Urgency.NURSE_SOON, "pain", summary="Sore knee")
    (alert,) = app.notifier.sent
    assert alert.nurse_id == "nurse_lena"
    assert app.store.calls.get(call.id).status is CallStatus.ESCALATED

    app.call_service.ack_by_nurse(call.id, "nurse_lena")
    app.call_service.resolve(call.id)
    assert app.store.calls.get(call.id).status is CallStatus.RESOLVED
    assert "jasmine" in app.memory.prompt_context("res_ines", "a cup of tea please")
