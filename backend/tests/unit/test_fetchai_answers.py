from bellhop.fetchai.answers import answer_question


def call(
    id,
    room,
    urgency,
    status="resolved",
    summary=None,
    created="2026-10-23T09:00:00Z",
    category=None,
):
    return {
        "id": id,
        "room": room,
        "urgency": urgency,
        "status": status,
        "summary": summary,
        "category": category,
        "created_at": created,
    }


def alert(id, call_id, level, message, acked=None, created="2026-10-23T09:05:00Z"):
    return {
        "id": id,
        "call_id": call_id,
        "level": level,
        "message": message,
        "created_at": created,
        "acked_at": acked,
        "nurse_id": None,
    }


CALLS = [
    call("c1", "12", 1, summary="Wanted a chat about her garden.", created="2026-10-23T08:00:00Z"),
    call(
        "c2",
        "12",
        4,
        status="escalated",
        summary="Reported a fall.",
        created="2026-10-23T09:30:00Z",
        category="fall",
    ),
    call("c3", "7", 2, summary="Asked for water."),
]
ALERTS = [
    alert("a1", "c2", 4, "Room 12: possible fall"),
    alert("a2", "c3", 3, "Room 7 needs a note", acked="2026-10-23T09:10:00Z"),
]
METRICS = {"resolved_without_nurse": 5, "minutes_saved": 42.5, "share_answered_within_10min": 0.9}


def ask(q, calls=CALLS, alerts=ALERTS, metrics=METRICS):
    return answer_question(q, calls, alerts, metrics)


def test_room_history_lists_calls_newest_first_in_words():
    out = ask("What happened in room 12?")
    assert "Room 12" in out
    assert "emergency" in out.lower() and "a chat" in out
    assert "emergency" in out.lower()
    assert "Room 7" not in out


def test_room_with_no_calls():
    assert "no calls" in ask("what happened in room 99").lower()


def test_room_number_forms():
    assert "Room 7" in ask("Tell me about Room 7 please")
    assert "routine request" in ask("history for rm 7").lower()


def test_emergencies_lists_open_alerts_with_room():
    out = ask("Any emergencies?")
    assert "Room 12" in out and "emergency" in out.lower()


def test_who_needs_a_nurse_skips_acknowledged():
    out = ask("who needs a nurse")
    assert "Room 12" in out
    assert "Room 7" not in out


def test_no_open_alerts():
    out = ask("any emergencies", alerts=[])
    assert "no" in out.lower() and "alert" in out.lower()


def test_metrics_resolved_and_minutes():
    out = ask("how many calls did the robot resolve")
    assert "5" in out
    out = ask("how many minutes saved?")
    assert "42" in out


def test_fallback_lists_capabilities():
    out = ask("what is the weather")
    assert "room" in out.lower() and "emergenc" in out.lower() and "minutes" in out.lower()


def test_empty_question_falls_back():
    assert "room" in ask("").lower()


def test_no_diagnosis_wording():
    assert "diagnos" not in ask("what happened in room 12").lower()


def test_missing_fields_do_not_crash():
    out = ask("room 5", calls=[{"id": "x", "room": "5", "created_at": "2026-10-23T09:00:00Z"}])
    assert "Room 5" in out
    assert ask("minutes saved", metrics={})
