"""Adversarial HTTP-level edge cases, round two.

Known bugs found here are fixed; new bugs are recorded as xfail(strict=True) until fixed.
"""

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container
from bellhop.domain import CallStatus, RobotStatus, Urgency
from bellhop.domain.care import CareEntry, EntryKind

RES = "/residents/res_margaret"
OTHER = "/residents/res_arthur"


@pytest.fixture
def container():
    return build_container(Settings(seed_demo=True, guard_timeouts=False))


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container), raise_server_exceptions=False)


def _care(client, kind, res=RES, **kw):
    return client.post(f"{res}/care", json={"kind": kind, **kw})


def _seed_pain(container, days_back, value=3, res="res_margaret"):
    at = datetime.now(UTC) - timedelta(days=days_back)
    container.care_store.entries.add(
        CareEntry(
            id=f"seed_{res}_{days_back}_{value}",
            resident_id=res,
            kind=EntryKind.PAIN,
            value=value,
            at=at,
        )
    )


def _pain_flags(client, res="res_margaret"):
    flags = client.get("/flags", params={"resident_id": res}).json()
    return [f for f in flags if f["type"] == "pain"]


# --- (a) care API ----------------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 6, -1, -0.01, 5.01, 1e9])
@pytest.mark.parametrize("kind", ["mood", "pain"])
def test_care_value_out_of_range_rejected(client, kind, value):
    assert _care(client, kind, value=value).status_code == 422


@pytest.mark.parametrize("value", [1, 5, 3.5])
def test_care_value_boundaries_accepted(client, value):
    assert _care(client, "mood", value=value).status_code == 201


@pytest.mark.parametrize("raw", ['{"kind":"mood","value":NaN}', '{"kind":"pain","value":Infinity}'])
def test_care_nan_and_infinity_never_500(client, raw):
    r = client.post(f"{RES}/care", content=raw, headers={"content-type": "application/json"})
    assert 400 <= r.status_code < 500


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"value": 3},
        {"kind": None},
        {"kind": "MOOD", "value": 3},
        {"kind": "mood", "value": "high"},
        {"kind": "mood", "value": None},
        {"kind": "pain", "value": None},
        {"kind": ["mood"], "value": 3},
        {"kind": "mood", "value": 3, "note": None},
    ],
)
def test_care_bad_bodies_are_422(client, body):
    assert client.post(f"{RES}/care", json=body).status_code == 422


def test_care_unknown_resident_never_500(client):
    for kind, kw in [("mood", {"value": 3}), ("pain", {"value": 3}), ("drink", {}),
                     ("repeat_question", {})]:  # fmt: skip
        r = _care(client, kind, res="/residents/ghost", **kw)
        assert r.status_code == 404
    assert client.get("/residents/ghost/care/summary").status_code == 404


def test_care_with_unknown_call_id_is_not_500(client):
    r = _care(client, "drink", call_id="call_ghost")
    assert r.status_code < 500


def test_care_with_unknown_call_id_rejected(client):
    assert _care(client, "drink", call_id="call_ghost").status_code in (404, 422)


def test_drink_and_repeat_ignore_value_field(client):
    assert _care(client, "drink", value=None).status_code == 201
    assert _care(client, "repeat_question", value=None).status_code == 201


def test_care_summary_for_resident_with_no_data(client):
    assert client.get(f"{OTHER}/care/summary").json() == {
        "pain_streak_days": 0,
        "mood_lower_than_usual": False,
        "drinks_today": 0,
        "repeat_questions_today": 0,
    }


def test_repeat_question_counts_per_resident(client):
    for _ in range(4):
        assert _care(client, "repeat_question").status_code == 201
    _care(client, "repeat_question", res=OTHER)
    assert client.get(f"{RES}/care/summary").json()["repeat_questions_today"] == 4
    assert client.get(f"{OTHER}/care/summary").json()["repeat_questions_today"] == 1


def test_repeat_questions_never_raise_a_flag(client):
    for _ in range(10):
        _care(client, "repeat_question")
    assert client.get("/flags").json() == []


def test_pain_below_threshold_never_counts(client, container):
    for back in (2, 1):
        _seed_pain(container, back, value=1)
    _care(client, "pain", value=1)
    assert client.get(f"{RES}/care/summary").json()["pain_streak_days"] == 0
    assert _pain_flags(client) == []


def test_three_day_pain_streak_flags_once_even_with_more_entries(client, container):
    for back in (2, 1):
        _seed_pain(container, back)
    for _ in range(4):
        assert _care(client, "pain", value=4).status_code == 201
    assert len(_pain_flags(client)) == 1
    assert client.get(f"{RES}/care/summary").json()["pain_streak_days"] == 3


def test_pain_gap_breaks_the_streak(client, container):
    _seed_pain(container, 3)
    _seed_pain(container, 1)  # gap at day 2
    _care(client, "pain", value=3)
    assert client.get(f"{RES}/care/summary").json()["pain_streak_days"] == 2
    assert _pain_flags(client) == []


def test_pain_streak_only_counts_the_resident_in_question(client, container):
    _seed_pain(container, 2)
    _seed_pain(container, 1, res="res_arthur")
    _care(client, "pain", value=3)
    assert client.get(f"{RES}/care/summary").json()["pain_streak_days"] == 1
    assert _pain_flags(client) == []


def test_pain_streak_across_utc_midnight(container):
    cs = container.care_store
    base = datetime(2026, 3, 10, 0, 0, 30, tzinfo=UTC)
    # 23:59:59 two nights back, 00:00:01 the next day, then just after midnight today.
    for i, at in enumerate(
        [
            datetime(2026, 3, 8, 23, 59, 59, tzinfo=UTC),
            datetime(2026, 3, 9, 0, 0, 1, tzinfo=UTC),
            datetime(2026, 3, 10, 0, 0, 1, tzinfo=UTC),
        ]
    ):
        cs.entries.add(
            CareEntry(id=f"b{i}", resident_id="res_margaret", kind=EntryKind.PAIN, value=3, at=at)
        )
    assert container.care_signals.pain_streak("res_margaret", base).days == 3


def test_two_entries_inside_one_utc_day_count_once(container):
    for i, hour in enumerate((0, 23)):
        container.care_store.entries.add(
            CareEntry(
                id=f"d{i}",
                resident_id="res_margaret",
                kind=EntryKind.PAIN,
                value=4,
                at=datetime(2026, 3, 10, hour, 0, tzinfo=UTC),
            )
        )
    now = datetime(2026, 3, 10, 23, 59, tzinfo=UTC)
    assert container.care_signals.pain_streak("res_margaret", now).days == 1


def test_pain_yesterday_but_not_today_is_streak_zero(container):
    for i, d in enumerate((8, 9)):
        container.care_store.entries.add(
            CareEntry(
                id=f"y{i}",
                resident_id="res_margaret",
                kind=EntryKind.PAIN,
                value=3,
                at=datetime(2026, 3, d, 12, tzinfo=UTC),
            )
        )
    now = datetime(2026, 3, 10, 9, tzinfo=UTC)
    assert container.care_signals.pain_streak("res_margaret", now).days == 0


def test_resolve_flag_twice_keeps_first_resolution_time(client, container):
    for back in (2, 1):
        _seed_pain(container, back)
    _care(client, "pain", value=3)
    fid = _pain_flags(client)[0]["id"]
    first = client.post(f"/flags/{fid}/resolve")
    second = client.post(f"/flags/{fid}/resolve")
    assert first.status_code == second.status_code == 200
    assert first.json()["resolved_at"] == second.json()["resolved_at"] is not None
    assert _pain_flags(client) == []


def test_new_pain_after_resolve_raises_a_fresh_flag(client, container):
    for back in (2, 1):
        _seed_pain(container, back)
    _care(client, "pain", value=3)
    fid = _pain_flags(client)[0]["id"]
    client.post(f"/flags/{fid}/resolve")
    _care(client, "pain", value=3)
    assert len(_pain_flags(client)) == 1
    assert _pain_flags(client)[0]["id"] != fid


def test_resolve_unknown_flag_404(client):
    assert client.post("/flags/nope/resolve").status_code == 404


def test_flags_filters_for_unknown_resident_empty(client):
    assert client.get("/flags", params={"resident_id": "ghost"}).json() == []


def test_flags_bad_query_bool_is_422(client):
    assert client.get("/flags", params={"open_only": "maybe"}).status_code == 422


def test_mood_drop_flag_not_duplicated(client, container):
    now = datetime.now(UTC)
    for i in range(4):
        container.care_store.entries.add(
            CareEntry(
                id=f"m{i}",
                resident_id="res_margaret",
                kind=EntryKind.MOOD,
                value=5,
                at=now - timedelta(days=6 + i),
            )
        )
    for _ in range(3):
        _care(client, "mood", value=1)
    flags = [f for f in client.get("/flags").json() if f["type"] == "distress"]
    assert len(flags) == 1
    assert flags[0]["reason"].strip()


# --- (b) memory API --------------------------------------------------------------------


def _remember(client, text, res=RES, **kw):
    return client.post(f"{res}/memory", json={"text": text, **kw})


def test_memory_unicode_and_emoji_accepted(client):
    r = _remember(client, "Loves café au lait and crème brûlée 🍵")
    assert r.status_code == 201
    assert r.json()["text"] == "Loves café au lait and crème brûlée 🍵"


def test_memory_length_boundaries(client):
    assert _remember(client, "a" * 7).status_code == 422
    assert _remember(client, "abcdefgh").status_code == 201
    assert _remember(client, "x " * 139 + "y").status_code == 201  # 279 chars
    assert _remember(client, "q" * 280, res=OTHER).status_code == 201
    r = _remember(client, "q" * 281, res=OTHER)
    assert r.status_code == 422 and r.json()["detail"] == "too_long"


def test_memory_length_counted_after_strip(client):
    assert _remember(client, "   short   ").status_code == 422
    assert _remember(client, "  " + "z" * 280 + "  ").status_code == 201


def test_memory_very_long_text_rejected_not_500(client):
    r = _remember(client, "lorem " * 200_000)  # over 1 MB
    assert r.status_code == 413
    assert _remember(client, "lorem " * 400).status_code == 422  # 2400 chars: over-length field


@pytest.mark.parametrize("text", ["", " ", "\n\t  \n", "         "])
def test_memory_whitespace_only_rejected(client, text):
    assert _remember(client, text).status_code == 422


@pytest.mark.parametrize(
    "text",
    [
        "She was DIAGNOSED WITH something",
        "Takes 20MG every morning",
        "PRESCRIBED a new thing",
        "You Have Diabetes",
        "the Dosage changed",
        "Prescription ran out",
        "She takes 5 ml at night",
    ],
)
def test_memory_clinical_claims_rejected_in_any_case(client, text):
    r = _remember(client, text)
    assert r.status_code == 422 and r.json()["detail"] == "clinical_claim"


def test_memory_clinical_check_precedes_pending_review(client):
    r = _remember(client, "Was diagnosed with arthritis", confidence=0.1)
    assert r.status_code == 422
    assert client.get(f"{RES}/memory/pending").json() == []


def test_memory_staff_source_bypasses_low_confidence_but_not_clinical(client):
    assert (
        _remember(client, "Likes the window open", source="staff", confidence=0.0).status_code
        == 201
    )
    assert _remember(client, "prescribed 10 mg daily", source="staff").status_code == 422


@pytest.mark.parametrize("conf", [-0.1, 1.1])
def test_memory_confidence_out_of_range_422(client, conf):
    assert _remember(client, "Likes warm milk at night", confidence=conf).status_code == 422


def test_memory_confidence_exact_threshold_accepted(client):
    assert _remember(client, "Likes warm milk at night", confidence=0.6).status_code == 201
    assert _remember(client, "Enjoys the garden roses", confidence=0.5999).status_code == 202


def test_memory_near_duplicate_boundaries(client):
    assert _remember(client, "Her granddaughter Emma visits every Sunday").status_code == 201
    same = _remember(client, "  her GRANDDAUGHTER emma visits every sunday!  ")
    assert same.status_code == 422 and same.json()["detail"] == "duplicate"
    different = _remember(client, "Her grandson Oliver phones every Friday")
    assert different.status_code == 201


def test_memory_duplicate_is_per_resident(client):
    assert _remember(client, "Loves listening to Glenn Miller records").status_code == 201
    assert (
        _remember(client, "Loves listening to Glenn Miller records", res=OTHER).status_code == 201
    )


def test_memory_distinct_non_latin_facts_not_duplicates(client):
    assert _remember(client, "我喜欢喝茶和吃饺子").status_code == 201
    assert _remember(client, "她的孙子住在北京城里").status_code == 201


def test_memory_write_for_unknown_resident_rejected(client):
    assert _remember(client, "Likes warm milk at night", res="/residents/ghost").status_code == 404


@pytest.mark.parametrize("k", [-1, -100])
def test_memory_recall_negative_k_rejected(client, k):
    _remember(client, "Likes warm milk at night")
    _remember(client, "Enjoys the garden roses")
    assert client.get(f"{RES}/memory", params={"q": "milk", "k": k}).status_code == 422


def test_memory_recall_k_zero_and_non_int(client):
    _remember(client, "Likes warm milk at night")
    assert client.get(f"{RES}/memory", params={"k": 0}).status_code == 422
    assert client.get(f"{RES}/memory", params={"k": "x"}).status_code == 422


def test_memory_recall_huge_k_and_odd_query_never_500(client):
    _remember(client, "Likes warm milk at night")
    for q in ["", "%", "a" * 50_000, "🍵", "\u0000", "' OR 1=1 --"]:
        assert client.get(f"{RES}/memory", params={"q": q, "k": 10**9}).status_code == 422, q
        expected = 422 if len(q) > 500 else 200  # q is capped at 500 chars
        assert client.get(f"{RES}/memory", params={"q": q, "k": 5}).status_code == expected, q


def test_memory_pending_approve_under_wrong_resident_is_404(client):
    r = _remember(client, "Enjoys the garden roses", confidence=0.3)
    assert r.status_code == 202
    assert client.post(f"{OTHER}/memory/pending/pending-1/approve").status_code == 404
    assert client.post(f"{OTHER}/memory/pending/pending-1/reject").status_code == 404
    # still pending for its real owner, and nothing leaked into either resident's memory
    assert len(client.get(f"{RES}/memory/pending").json()) == 1
    assert client.get(f"{OTHER}/memory", params={"q": "roses"}).json() == []


def test_memory_approve_twice_second_is_404(client):
    _remember(client, "Enjoys the garden roses", confidence=0.3)
    first = client.post(f"{RES}/memory/pending/pending-1/approve")
    assert first.status_code == 200
    assert client.post(f"{RES}/memory/pending/pending-1/approve").status_code == 404
    hits = client.get(f"{RES}/memory", params={"q": "roses"}).json()
    assert len([h for h in hits if "roses" in h["text"]]) == 1


def test_memory_reject_then_approve_is_404(client):
    _remember(client, "Enjoys the garden roses", confidence=0.3)
    assert client.post(f"{RES}/memory/pending/pending-1/reject").status_code == 200
    assert client.post(f"{RES}/memory/pending/pending-1/approve").status_code == 404
    assert client.get(f"{RES}/memory/pending").json() == []


def test_memory_approve_unknown_pending_404(client):
    assert client.post(f"{RES}/memory/pending/pending-999/approve").status_code == 404


def test_memory_approve_pending_that_became_duplicate_not_stored_twice(client):
    _remember(client, "Enjoys the garden roses", confidence=0.3)
    assert _remember(client, "Enjoys the garden roses").status_code == 201
    client.post(f"{RES}/memory/pending/pending-1/approve")
    hits = client.get(f"{RES}/memory", params={"q": "garden roses", "k": 10}).json()
    assert len([h for h in hits if "roses" in h["text"]]) == 1


def test_memory_forget_unknown_fact_404_and_wrong_resident_404(client):
    fact = _remember(client, "Likes warm milk at night").json()
    assert client.delete(f"{RES}/memory/nope").status_code == 404
    assert client.delete(f"{OTHER}/memory/{fact['id']}").status_code == 404
    # fact survived the wrong-resident delete
    assert client.delete(f"{RES}/memory/{fact['id']}").status_code == 204
    assert client.delete(f"{RES}/memory/{fact['id']}").status_code == 404


def test_memory_forget_all_leaves_other_residents_untouched(client):
    _remember(client, "Likes warm milk at night")
    _remember(client, "Enjoys the garden roses", confidence=0.2)  # pending
    _remember(client, "Likes warm milk at night", res=OTHER)
    removed = client.delete(f"{RES}/memory").json()["removed"]
    assert removed >= 1
    assert client.get(f"{RES}/memory", params={"q": "milk garden"}).json() == []
    assert client.get(f"{RES}/memory/pending").json() == []
    assert [f["text"] for f in client.get(f"{OTHER}/memory", params={"q": "milk"}).json()] == [
        "Likes warm milk at night"
    ]
    assert client.delete(f"{RES}/memory").json() == {"removed": 0}


def test_memory_forget_all_then_same_fact_can_be_relearned(client):
    _remember(client, "Likes warm milk at night")
    client.delete(f"{RES}/memory")
    assert _remember(client, "Likes warm milk at night").status_code == 201


def test_memory_concurrent_proposals_of_same_fact_store_it_once(container):
    app = create_app(container)
    for round_ in range(80):
        text = f"Adores the song number {round_} on the gramophone"
        with ThreadPoolExecutor(8) as pool:
            codes = list(
                pool.map(
                    lambda _, text=text: (
                        TestClient(app).post(f"{RES}/memory", json={"text": text}).status_code
                    ),
                    range(8),
                )
            )
        assert codes.count(201) == 1, (round_, codes)


def test_memory_concurrent_pending_ids_are_unique(container):
    app = create_app(container)
    with ThreadPoolExecutor(8) as pool:
        list(
            pool.map(
                lambda i: TestClient(app).post(
                    f"{RES}/memory",
                    json={"text": f"Mentioned hobby number {i} here", "confidence": 0.1},
                ),
                range(16),
            )
        )
    ids = [p["id"] for p in TestClient(app).get(f"{RES}/memory/pending").json()]
    assert len(ids) == len(set(ids)) == 16


def test_memory_bad_bodies_422(client):
    for body in [{}, {"text": None}, {"text": 5}, {"text": "valid text here", "tags": "x"}]:
        assert client.post(f"{RES}/memory", json=body).status_code == 422


# --- (c) family ------------------------------------------------------------------------

_FORBIDDEN = re.compile(r"pain|urgen|nurse|medic|\bmeds?\b|pill|tablet|doctor|emergency", re.I)


def test_postcard_with_no_entries_is_the_quiet_line(client):
    lines = client.get(f"{RES}/postcard").json()["lines"]
    assert len(lines) == 1 and lines[0]


def test_postcard_unknown_resident_404(client):
    assert client.get("/residents/ghost/postcard").status_code == 404


def test_postcard_only_covers_today(client, container):
    container.care_store.entries.add(
        CareEntry(
            id="old",
            resident_id="res_margaret",
            kind=EntryKind.DRINK,
            note="hot chocolate",
            at=datetime.now(UTC) - timedelta(days=1, minutes=1),
        )
    )
    assert "hot chocolate" not in " ".join(client.get(f"{RES}/postcard").json()["lines"])


def test_postcard_is_per_resident(client):
    _care(client, "drink", note="cocoa")
    assert "cocoa" not in " ".join(client.get(f"{OTHER}/postcard").json()["lines"])


@pytest.mark.parametrize(
    "note",
    [
        "in terrible PAIN today",
        "Painful knee",
        "asked for the Nurse",
        "NURSE Joy came by",
        "took her medication late",
        "Medicine mix-up",
        "had her pills",
        "doctor visit",
        "urgent chat",
    ],
)
def test_postcard_never_leaks_clinical_words_from_notes(client, note):
    _care(client, "mood", value=5, note=note)
    _care(client, "drink", note=note)
    text = " ".join(client.get(f"{RES}/postcard").json()["lines"])
    assert not _FORBIDDEN.search(text), text


def test_postcard_ignores_pain_entries_and_their_notes(client):
    _care(client, "pain", value=5, note="chatted with the nurse about her knee")
    _care(client, "mood", value=4)
    text = " ".join(client.get(f"{RES}/postcard").json()["lines"])
    assert not _FORBIDDEN.search(text)


@pytest.mark.parametrize(
    "note", ["Urgency was high today", "forgot her Meds", "two tablets at tea"]
)
def test_postcard_blocklist_covers_word_variants(client, note):
    _care(client, "mood", value=5, note=note)
    text = " ".join(client.get(f"{RES}/postcard").json()["lines"])
    assert not _FORBIDDEN.search(text), text


def test_postcard_low_mood_note_not_shown(client):
    _care(client, "mood", value=2, note="chatted about the garden")
    lines = client.get(f"{RES}/postcard").json()["lines"]
    assert "chatted about the garden" not in " ".join(lines).lower()


def test_postcard_capped_deduped_and_specifics_first(client):
    for note in ["tea", "tea", "coffee", "juice", "water"]:
        _care(client, "drink", note=note)
    _care(client, "mood", value=5)
    lines = client.get(f"{RES}/postcard").json()["lines"]
    assert len(lines) <= 3 and len(lines) == len(set(lines))
    assert lines[-1] != "Was in good spirits" or len(lines) == 1


def test_postcard_whitespace_note_does_not_crash_or_blank_line(client):
    _care(client, "mood", value=5, note="   ")
    _care(client, "drink", note="   ")
    lines = client.get(f"{RES}/postcard").json()["lines"]
    assert all(line.strip() for line in lines)


def test_family_reply_ordering_and_directions(client):
    client.post(f"{RES}/family/messages", json={"text": "Thinking of you"})
    for i in range(5):
        assert client.post(f"{RES}/family/replies", json={"text": f"reply {i}"}).status_code == 201
    msgs = client.get(f"{RES}/family/messages").json()
    replies = [m["text"] for m in msgs if m["direction"] == "from_resident"]
    assert replies == [f"reply {i}" for i in range(5)]
    stamps = [m["created_at"] for m in msgs]
    assert stamps == sorted(stamps)
    assert client.get(f"{OTHER}/family/messages").json() == []


@pytest.mark.parametrize("text", ["", "x" * 501])
def test_family_text_length_limits(client, text):
    assert client.post(f"{RES}/family/messages", json={"text": text}).status_code == 422
    assert client.post(f"{RES}/family/replies", json={"text": text}).status_code == 422


def test_family_text_boundaries_and_unicode(client):
    assert client.post(f"{RES}/family/messages", json={"text": "x" * 500}).status_code == 201
    r = client.post(f"{RES}/family/messages", json={"text": "Bonne nuit, grand-mère 🌙"})
    assert r.json()["text"] == "Bonne nuit, grand-mère 🌙"


def test_family_whitespace_only_message_rejected(client):
    assert client.post(f"{RES}/family/messages", json={"text": "     "}).status_code == 422


def test_family_unknown_resident_404(client):
    for path in ("messages", "replies"):
        r = client.post(f"/residents/ghost/family/{path}", json={"text": "hi"})
        assert r.status_code == 404
    assert client.get("/residents/ghost/family/messages").status_code == 404


def test_family_delivery_marking_is_idempotent(client, container):
    fam = container.family
    client.post(f"{RES}/family/messages", json={"text": "one"})
    client.post(f"{RES}/family/messages", json={"text": "two"})
    assert [m.text for m in fam.pending_for_resident("res_margaret")] == ["one", "two"]
    fam.mark_delivered("res_margaret")
    fam.mark_delivered("res_margaret")
    assert fam.pending_for_resident("res_margaret") == []
    client.post(f"{RES}/family/messages", json={"text": "three"})
    assert [m.text for m in fam.pending_for_resident("res_margaret")] == ["three"]
    fam.mark_delivered("res_margaret")
    assert fam.pending_for_resident("res_margaret") == []
    # the history endpoint is unaffected by delivery marking
    assert len(client.get(f"{RES}/family/messages").json()) == 3


def test_family_replies_are_never_pending_for_resident(client, container):
    client.post(f"{RES}/family/replies", json={"text": "I am fine"})
    assert container.family.pending_for_resident("res_margaret") == []


def test_family_delivery_marking_isolated_per_resident(client, container):
    client.post(f"{RES}/family/messages", json={"text": "for margaret"})
    client.post(f"{OTHER}/family/messages", json={"text": "for arthur"})
    container.family.mark_delivered("res_margaret")
    assert [m.text for m in container.family.pending_for_resident("res_arthur")] == ["for arthur"]


# --- (d) triage ------------------------------------------------------------------------


def _new_call(client, room="12"):
    return client.post("/calls", json={"room": room}).json()["id"]


def _turn(client, call_id, text, speaker="resident"):
    return client.post(f"/calls/{call_id}/turns", json={"speaker": speaker, "text": text})


def _score(client, call_id, urgency=2, **kw):
    return client.post(f"/calls/{call_id}/score", json={"urgency": urgency, "category": "x", **kw})


def _alerts(client, call_id):
    return [a for a in client.get("/alerts").json() if a["call_id"] == call_id]


def test_score_and_triage_failed_on_unknown_call_404(client):
    assert _score(client, "nope").status_code == 404
    assert client.post("/calls/nope/triage-failed").status_code == 404
    assert client.get("/alerts").json() == []


@pytest.mark.parametrize("bad", [0, 5, -1, 2.5, "high", None])
def test_score_bad_urgency_422(client, bad):
    cid = _new_call(client)
    assert _score(client, cid, urgency=bad).status_code == 422


@pytest.mark.parametrize("conf", [1.01, -0.01, 7, "very"])
def test_score_confidence_out_of_range_422(client, conf):
    cid = _new_call(client)
    assert _score(client, cid, confidence=conf).status_code == 422
    assert client.get(f"/calls/{cid}").json()["urgency"] is None


@pytest.mark.parametrize("conf", [0, 1, 0.6])
def test_score_confidence_boundaries_accepted(client, conf):
    assert _score(client, _new_call(client), confidence=conf).status_code == 200


def test_score_confidence_none_means_trusted(client):
    cid = _new_call(client)
    body = _score(client, cid, urgency=2, confidence=None).json()
    assert body["urgency"] == 2


def test_score_missing_category_422(client):
    assert client.post(f"/calls/{_new_call(client)}/score", json={"urgency": 2}).status_code == 422


def test_score_on_resolved_call_ignored_and_never_pages(client):
    cid = _new_call(client)
    assert client.post(f"/calls/{cid}/resolve").status_code == 200
    _turn(client, cid, "I fell and cannot get up")
    r = _score(client, cid, urgency=4)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == CallStatus.RESOLVED and body["urgency"] is None
    assert client.post(f"/calls/{cid}/triage-failed").status_code == 200
    assert _alerts(client, cid) == []


def test_clear_emergency_phrase_overrides_model_urgency_one(client):
    cid = _new_call(client)
    _turn(client, cid, "Help, I fell and I cannot get up")
    body = _score(client, cid, urgency=1, confidence=0.99).json()
    assert body["urgency"] == Urgency.EMERGENCY
    alerts = _alerts(client, cid)
    assert len(alerts) == 1
    assert alerts[0]["nurse_id"] is None  # broadcast
    assert alerts[0]["level"] == Urgency.EMERGENCY
    # rescoring the same call does not page again
    _score(client, cid, urgency=1)
    _score(client, cid, urgency=4)
    assert len(_alerts(client, cid)) == 1


def test_only_resident_turns_drive_the_safety_floor(client):
    cid = _new_call(client)
    _turn(client, cid, "Margaret, did you fall?", speaker="robot")
    assert _score(client, cid, urgency=1, confidence=1).json()["urgency"] == 1
    assert _alerts(client, cid) == []


def test_triage_failed_twice_does_not_duplicate_alerts(client):
    cid = _new_call(client)
    first = client.post(f"/calls/{cid}/triage-failed").json()
    client.post(f"/calls/{cid}/triage-failed")
    assert first["urgency"] == Urgency.NURSE_SOON
    assert len(_alerts(client, cid)) == 1


def test_triage_failed_then_emergency_escalates_with_second_alert_only(client):
    cid = _new_call(client)
    client.post(f"/calls/{cid}/triage-failed")
    _turn(client, cid, "I have chest pain")
    client.post(f"/calls/{cid}/triage-failed")
    levels = sorted(a["level"] for a in _alerts(client, cid))
    assert levels == [Urgency.NURSE_SOON, Urgency.EMERGENCY]


def test_urgency_never_lowers_across_mixed_calls(client):
    cid = _new_call(client)
    seen = []
    for urg in (3, 1, 2, 4, 1, 3):
        _score(client, cid, urgency=urg)
        client.post(f"/calls/{cid}/triage-failed")
        seen.append(client.get(f"/calls/{cid}").json()["urgency"])
    assert seen == sorted(seen) and seen[-1] == Urgency.EMERGENCY


def test_low_confidence_is_raised_but_capped_at_emergency(client):
    cid = _new_call(client)
    assert _score(client, cid, urgency=4, confidence=0.1).json()["urgency"] == 4
    cid2 = _new_call(client, "14")
    assert _score(client, cid2, urgency=2, confidence=0.1).json()["urgency"] == 3


def test_score_summary_survives_and_category_kept_on_ratchet(client):
    cid = _new_call(client)
    client.post(f"/calls/{cid}/score", json={"urgency": 4, "category": "fall", "summary": "s"})
    body = _score(client, cid, urgency=1).json()
    assert body["category"] == "fall" and body["urgency"] == 4


def test_score_on_escalated_call_still_ratchets_and_not_500(client):
    cid = _new_call(client)
    _score(client, cid, urgency=3)
    assert client.get(f"/calls/{cid}").json()["status"] == CallStatus.ESCALATED
    assert _score(client, cid, urgency=4).status_code == 200


# --- (e) API hardening ------------------------------------------------------------------


def _routes(app):
    spec = app.openapi()
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            yield method.upper(), path, op


def _fill(path, value="nope"):
    return re.sub(r"\{[^}]+\}", value, path)


def _body_routes(app):
    return [(m, p) for m, p, op in _routes(app) if "requestBody" in op]


def test_every_body_route_rejects_malformed_json(container):
    app = create_app(container)
    client = TestClient(app, raise_server_exceptions=False)
    routes = _body_routes(app)
    assert len(routes) >= 10
    for method, path in routes:
        for raw in (b"{bad json", b"", b"[1,2", b"\xff\xfe", b"null"):
            r = client.request(
                method,
                _fill(path, "res_margaret"),
                content=raw,
                headers={"content-type": "application/json"},
            )
            assert 400 <= r.status_code < 500 or (
                path.endswith("/resolve") and r.status_code < 500
            ), (
                method,
                path,
                raw,
                r.status_code,
            )


def test_every_body_route_rejects_wrong_json_types(container):
    app = create_app(container)
    client = TestClient(app, raise_server_exceptions=False)
    for method, path in _body_routes(app):
        for body in ([], "str", 42, {"unexpected": [1, {"a": None}]}):
            r = client.request(method, _fill(path, "res_margaret"), json=body)
            assert r.status_code < 500, (method, path, body, r.status_code)


def test_every_body_route_rejects_wrong_content_type(container):
    app = create_app(container)
    client = TestClient(app, raise_server_exceptions=False)
    for method, path in _body_routes(app):
        r = client.request(
            method,
            _fill(path, "res_margaret"),
            content=b"room=12",
            headers={"content-type": "text/plain"},
        )
        assert r.status_code < 500, (method, path, r.status_code)


# a valid-looking body for every body route, so unknown ids are what is under test
_VALID = {
    "/calls": {"room": "12"},
    "/calls/{call_id}/turns": {"speaker": "resident", "text": "hello"},
    "/calls/{call_id}/score": {"urgency": 2, "category": "x"},
    "/calls/{call_id}/override": {"urgency": 2},
    "/alerts/{alert_id}/ack": {"nurse_id": "nurse_1"},
    "/residents/{resident_id}/memory": {"text": "Likes warm milk at night"},
    "/residents/{resident_id}/care": {"kind": "drink"},
    "/residents/{resident_id}": {"birth_year": 1940},
    "/residents/{resident_id}/preferences": {"quiet_mode": True},
    "/residents/{resident_id}/family/messages": {"text": "hi"},
    "/residents/{resident_id}/family/replies": {"text": "hi"},
    "/robots/{robot_id}": {"status": "idle", "battery": 0.5},
    "/residents/{resident_id}/medical": {},
    "/residents/{resident_id}/medical/entries": {"category": "allergy", "text": "Penicillin"},
    "/residents/{resident_id}/notes/refine": {"category": "like", "text": "likes tea"},
}

# Routes whose unknown id is a harmless create/no-op rather than a lookup.
_CREATES = {("PUT", "/robots/{robot_id}")}


def _id_routes(app):
    return [(m, p, op) for m, p, op in _routes(app) if "{" in p]


def test_unknown_ids_never_500_on_any_path_param_route(container):
    app = create_app(container)
    client = TestClient(app, raise_server_exceptions=False)
    routes = _id_routes(app)
    assert len(routes) >= 20
    for method, path, op in routes:
        kw = {"json": _VALID.get(path, {})} if "requestBody" in op else {}
        r = client.request(method, _fill(path), **kw)
        assert r.status_code < 500, (method, path, r.status_code, r.text[:200])


def test_unknown_ids_are_404_on_lookup_routes(container):
    app = create_app(container)
    client = TestClient(app, raise_server_exceptions=False)
    bad = []
    for method, path, op in _id_routes(app):
        if (method, path) in _CREATES:
            continue
        if path.startswith("/residents/{resident_id}/reminiscence") and method == "GET":
            pass
        kw = {"json": _VALID.get(path, {})} if "requestBody" in op else {}
        r = client.request(method, _fill(path), **kw)
        if r.status_code != 404:
            bad.append((method, path, r.status_code))
    assert bad == []


def test_memory_reads_for_unknown_resident_404(container):
    client = TestClient(create_app(container))
    assert client.get("/residents/ghost/memory").status_code == 404
    assert client.get("/residents/ghost/memory/pending").status_code == 404
    assert client.delete("/residents/ghost/memory").status_code == 404


def test_known_resident_with_unknown_sub_ids_404(client):
    assert client.post(f"{RES}/memory/pending/nope/approve").status_code == 404
    assert client.post(f"{RES}/memory/pending/nope/reject").status_code == 404
    assert client.delete(f"{RES}/memory/nope").status_code == 404
    assert client.post("/alerts/nope/ack", json={"nurse_id": "nurse_1"}).status_code == 404


def test_ack_alert_with_unknown_nurse_is_404_not_500(client):
    cid = _new_call(client)
    client.post(f"/calls/{cid}/triage-failed")
    aid = _alerts(client, cid)[0]["id"]
    assert client.post(f"/alerts/{aid}/ack", json={"nurse_id": "nurse_ghost"}).status_code == 404


def test_ack_alert_twice_never_500(client):
    cid = _new_call(client)
    client.post(f"/calls/{cid}/triage-failed")
    alert = _alerts(client, cid)[0]
    nurse = alert["nurse_id"] or "nurse_1"
    assert client.post(f"/alerts/{alert['id']}/ack", json={"nurse_id": nurse}).status_code == 200
    assert client.post(f"/alerts/{alert['id']}/ack", json={"nurse_id": nurse}).status_code < 500


def test_invalid_transitions_are_409_not_500(client):
    cid = _new_call(client)
    client.post(f"/calls/{cid}/resolve")
    assert client.post(f"/calls/{cid}/resolve").status_code == 409
    assert client.post(f"/calls/{cid}/in-visit").status_code == 409


def test_wrong_methods_are_405(client):
    assert client.delete("/calls").status_code == 405
    assert client.put("/health").status_code == 405
    assert client.get("/calls/x/score").status_code == 405


def test_unknown_route_404(client):
    assert client.get("/nope").status_code == 404
    assert client.get("/residents//memory").status_code in (404, 307, 200)


def test_path_params_with_odd_characters_never_500(client):
    for ident in ["%00", "..%2f..", "a%20b", "%F0%9F%8D%B5", "x" * 5000, "%2e%2e"]:
        for path in (
            f"/calls/{ident}",
            f"/residents/{ident}/care/summary",
            f"/flags/{ident}/resolve",
        ):
            method = "POST" if path.endswith("resolve") else "GET"
            assert client.request(method, path).status_code < 500, path


def test_cors_preflight_allows_any_origin_and_method(client):
    for path in ("/calls", f"{RES}/care", "/robots/robot_1", f"{RES}/memory"):
        r = client.options(
            path,
            headers={
                "Origin": "http://dashboard.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert r.status_code == 200, path
        assert r.headers["access-control-allow-origin"] in ("*", "http://dashboard.example")
        assert "content-type" in r.headers["access-control-allow-headers"].lower()


def test_cors_header_on_simple_response_and_on_errors(client):
    for path in ("/health", "/calls/nope"):
        r = client.get(path, headers={"Origin": "http://x.example"})
        assert r.headers.get("access-control-allow-origin") in ("*", "http://x.example")


def test_very_large_bodies_never_500(client):
    big = "x" * 2_000_000
    assert client.post(f"{RES}/memory", json={"text": big}).status_code == 413
    assert client.post(f"{RES}/family/messages", json={"text": big}).status_code == 413
    assert client.post("/calls", json={"room": big}).status_code == 413
    cid = _new_call(client)
    turn = {"speaker": "robot", "text": big}
    assert client.post(f"/calls/{cid}/turns", json=turn).status_code == 413
    many_tags = {"text": "valid text here", "tags": ["t"] * 100_000}  # under 1 MB, over max_length
    assert client.post(f"{RES}/memory", json=many_tags).status_code == 422
    assert client.post(f"{RES}/care", json={"kind": "drink", "note": big}).status_code == 413


def test_deeply_nested_json_never_500(client):
    nested = "[" * 5000 + "]" * 5000
    r = client.post("/calls", content=nested, headers={"content-type": "application/json"})
    assert 400 <= r.status_code < 500


def test_unbounded_text_fields_are_capped(client):
    big = "x" * 2_000_000
    assert client.post(f"{RES}/care", json={"kind": "drink", "note": big}).status_code == 413
    small = "x" * 501  # under 1 MB but over the 500-char field limit
    assert client.post(f"{RES}/care", json={"kind": "drink", "note": small}).status_code == 422


def test_call_for_unknown_room_is_created_without_resident(client):
    r = client.post("/calls", json={"room": "999"})
    assert r.status_code == 201 and r.json()["resident_id"] is None


def test_resident_update_birth_year_bounds(client):
    assert client.put(RES, json={"birth_year": 1879}).status_code == 422
    assert client.put(RES, json={"birth_year": 2016}).status_code == 422
    assert client.put(RES, json={"birth_year": 1950}).status_code == 200
    assert client.put(RES, json={"birth_year": "1950"}).status_code in (200, 422)


def test_preferences_reject_unknown_fields_and_wrong_types(client):
    assert client.put(f"{RES}/preferences", json={"nonsense": 1}).status_code == 422
    assert client.put(f"{RES}/preferences", json={"quiet_mode": "sometimes"}).status_code == 422
    assert client.put(f"{RES}/preferences", json={"quiet_mode": True}).json()["quiet_mode"] is True


def test_preferences_partial_update_keeps_other_fields_and_is_per_resident(client):
    client.put(f"{RES}/preferences", json={"hard_of_hearing": True, "favourite_drink": "tea"})
    client.put(f"{RES}/preferences", json={"quiet_mode": True})
    prefs = client.get(f"{RES}/preferences").json()
    assert prefs["hard_of_hearing"] and prefs["quiet_mode"] and prefs["favourite_drink"] == "tea"
    assert client.get(f"{OTHER}/preferences").json()["quiet_mode"] is False


# --- (f) robots ------------------------------------------------------------------------


@pytest.mark.parametrize("battery", [1.2, -0.1, 1.0001, 100, "full", None])
def test_robot_battery_out_of_range_422_and_state_untouched(client, battery):
    before = client.get("/robots").json()
    r = client.put("/robots/robot_1", json={"status": "idle", "battery": battery})
    assert r.status_code == 422
    assert client.get("/robots").json() == before


@pytest.mark.parametrize("battery", [0, 1, 0.2])
def test_robot_battery_boundaries_accepted(client, battery):
    r = client.put("/robots/robot_1", json={"status": "idle", "battery": battery})
    assert r.status_code == 200 and r.json()["battery"] == battery


@pytest.mark.parametrize("status", ["flying", "", "IDLE", None, 1])
def test_robot_wrong_status_422(client, status):
    assert client.put("/robots/robot_1", json={"status": status, "battery": 0.5}).status_code == 422


def test_robot_missing_fields_422(client):
    assert client.put("/robots/robot_1", json={"battery": 0.5}).status_code == 422
    assert client.put("/robots/robot_1", json={"status": "idle"}).status_code == 422


def test_idle_report_on_busy_robot_stays_busy_but_updates_battery(client):
    cid = _new_call(client)
    assert client.get("/robots").json()[0]["status"] == RobotStatus.BUSY
    r = client.put("/robots/robot_1", json={"status": "idle", "battery": 0.55, "room": "lobby"})
    assert r.status_code == 200
    body = r.json()
    assert (
        body["status"] == RobotStatus.BUSY and body["battery"] == 0.55 and body["room"] == "lobby"
    )
    # a second call must still not be double-assigned to the (stale-idle) robot
    second = client.post("/calls", json={"room": "14"}).json()
    assert second["robot_id"] is None
    client.post(f"/calls/{cid}/in-visit")
    client.post(f"/calls/{cid}/resolve")
    freed = client.put("/robots/robot_1", json={"status": "idle", "battery": 0.5}).json()
    assert freed["status"] == RobotStatus.IDLE


def test_idle_report_after_call_resolved_is_honoured(client):
    cid = _new_call(client)
    client.post(f"/calls/{cid}/resolve")
    r = client.put("/robots/robot_1", json={"status": "idle", "battery": 0.9})
    assert r.json()["status"] == RobotStatus.IDLE


def test_busy_robot_can_still_report_fault_or_charging(client):
    _new_call(client)
    for status in ("fault", "charging"):
        r = client.put("/robots/robot_1", json={"status": status, "battery": 0.4})
        assert r.json()["status"] == status


def test_new_robot_registered_via_put_and_listed(client):
    r = client.put("/robots/robot_9", json={"status": "idle", "battery": 0.8})
    assert r.status_code == 200
    assert {x["id"] for x in client.get("/robots").json()} == {"robot_1", "robot_9"}


def test_robot_low_battery_report_makes_it_undispatchable(client):
    client.put("/robots/robot_1", json={"status": "idle", "battery": 0.05})
    call = client.post("/calls", json={"room": "12"}).json()
    assert call["robot_id"] is None


# --- regression tests for the round-two fixes --------------------------------------------

_NON_FINITE = ["NaN", "Infinity", "-Infinity"]


@pytest.mark.parametrize("token", _NON_FINITE)
@pytest.mark.parametrize(
    ("method", "path", "template"),
    [
        ("post", f"{RES}/care", '{{"kind":"mood","value":{x}}}'),
        ("post", f"{RES}/memory", '{{"text":"Likes warm milk at night","confidence":{x}}}'),
        ("put", "/robots/robot_1", '{{"status":"idle","battery":{x}}}'),
    ],
)
def test_non_finite_numbers_are_422_on_every_float_route(client, method, path, template, token):
    r = client.request(
        method.upper(),
        path,
        content=template.format(x=token),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], list)


@pytest.mark.parametrize("token", _NON_FINITE)
def test_non_finite_score_confidence_is_422(client, token):
    cid = _new_call(client)
    body = f'{{"urgency":2,"category":"x","confidence":{token}}}'
    r = client.post(
        f"/calls/{cid}/score", content=body, headers={"content-type": "application/json"}
    )
    assert r.status_code == 422


def test_approving_pending_that_became_duplicate_is_409(client):
    _remember(client, "Enjoys the garden roses", confidence=0.3)
    assert _remember(client, "Enjoys the garden roses").status_code == 201
    r = client.post(f"{RES}/memory/pending/pending-1/approve")
    assert r.status_code == 409 and r.json()["detail"] == "duplicate"
    assert client.get(f"{RES}/memory/pending").json() == []  # the stale pending is dropped


def test_approve_reruns_safety_rules(container):
    guard = container.memory_guard
    guard.propose("res_margaret", "Enjoys the garden roses", confidence=0.3)
    guard._pending["pending-1"].text = "prescribed 10 mg daily"  # tampered after queueing
    result = guard.approve("pending-1", "res_margaret")
    assert result.reason == "clinical_claim"
    assert guard.pending("res_margaret") == []


def test_approve_unsafe_pending_is_422_over_http(client, container):
    _remember(client, "Enjoys the garden roses", confidence=0.3)
    container.memory_guard._pending["pending-1"].text = "prescribed 10 mg daily"
    r = client.post(f"{RES}/memory/pending/pending-1/approve")
    assert r.status_code == 422 and r.json()["detail"] == "clinical_claim"


_CLINICAL_WORDS = [
    "pain", "PAIN", "Painful", "painkillers", "urgent", "Urgency", "urgently", "meds", "Meds",
    "medication", "medicine", "medic", "tablet", "tablets", "pills", "pill", "dose", "dosage",
    "10mg", "mg", "nurse", "Nurses", "nurse-call", "alert", "alerts", "emergency", "doctor",
    "paracetamol", "insulin", "hurts", "fell", "dizzy", "p a i n", "pa1n", "Nurse!", "NURSE.",
]  # fmt: skip


@pytest.mark.parametrize("word", _CLINICAL_WORDS)
def test_postcard_never_contains_clinical_wording(client, word):
    for kind in ("mood", "drink"):
        _care(client, kind, value=5, note=f"{word} and some tea") if kind == "mood" else _care(
            client, kind, note=f"{word} and some tea"
        )
    _care(client, "mood", value=4, note=word)
    _care(client, "pain", value=5, note=word)
    _care(client, "repeat_question", note=word)
    lines = client.get(f"{RES}/postcard").json()["lines"]
    text = " ".join(lines).lower()
    assert not _FORBIDDEN.search(text), text
    assert word.lower().strip("!.") not in text or word.lower() in ("tea",), text


def test_postcard_lines_come_only_from_templates_and_allowlisted_drinks(client):
    _care(client, "mood", value=5, note="Margaret sang Danny Boy with the 3pm group")
    _care(client, "drink", note="a lovely cup of Tea from Mrs Jones")
    lines = client.get(f"{RES}/postcard").json()["lines"]
    assert sorted(lines) == ["Enjoyed some tea", "Was in good spirits"]


def test_care_unknown_call_id_is_404_and_nothing_recorded(client):
    assert _care(client, "drink", call_id="call_ghost").status_code == 404
    assert client.get(f"{RES}/care/summary").json()["drinks_today"] == 0
    cid = _new_call(client)
    assert _care(client, "drink", call_id=cid).status_code == 201


@pytest.mark.parametrize("text", ["     ", "\n\t ", "\u00a0\u2003"])
def test_text_in_whitespace_only_is_422_on_messages_and_replies(client, text):
    assert client.post(f"{RES}/family/messages", json={"text": text}).status_code == 422
    assert client.post(f"{RES}/family/replies", json={"text": text}).status_code == 422


def test_text_in_is_stripped_before_storing(client):
    r = client.post(f"{RES}/family/messages", json={"text": "  hello gran  "})
    assert r.status_code == 201 and r.json()["text"] == "hello gran"


def test_non_ascii_facts_are_recallable_and_distinct(client):
    tea = _remember(client, "我喜欢喝茶和吃饺子").json()
    _remember(client, "she loves 🍵🍵🍵 every day")
    assert _remember(client, "我喜欢喝茶和吃饺子").status_code == 422  # identical: duplicate
    assert [f["id"] for f in client.get(f"{RES}/memory", params={"q": "饺子"}).json()] == [
        tea["id"]
    ]
    assert client.get(f"{RES}/memory", params={"q": "🍵"}).json()[0]["text"].startswith("she")


def test_symbol_only_facts_distinct_unless_identical(client):
    assert _remember(client, "!!!!!!!!!!").status_code == 201
    assert _remember(client, "??????????").status_code == 201
    assert _remember(client, "!!!!!!!!!!").status_code == 422


def test_liaison_concurrent_scores_at_urgency_3_raise_exactly_one_alert(container):
    app = create_app(container)
    for _ in range(40):
        cid = TestClient(app).post("/calls", json={"room": "12"}).json()["id"]
        with ThreadPoolExecutor(8) as pool:
            codes = list(
                pool.map(
                    lambda _, cid=cid: (
                        TestClient(app)
                        .post(f"/calls/{cid}/score", json={"urgency": 3, "category": "x"})
                        .status_code
                    ),
                    range(8),
                )
            )
        assert set(codes) == {200}, codes
        alerts = [a for a in TestClient(app).get("/alerts").json() if a["call_id"] == cid]
        assert len(alerts) == 1, (cid, len(alerts))
