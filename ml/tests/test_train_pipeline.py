"""Pure functions of the dev/train pipeline (offline, no network, no model downloads)."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dev"))

from train import labels, metrics, textprep  # noqa: E402

# ---- textprep ----


def test_clean_text_strips_urls_handles_emails_phones_and_markdown():
    raw = (
        "**Hi** u/jane_doe and r/AgingParents, see https://example.com/a?b=1 or www.x.org. "
        "Mail me at jane@x.com or call 555-123-4567. &amp; > quoted\n\n[link text](http://q.io)"
    )
    cleaned = textprep.clean_text(raw)
    for bad in ("http", "www", "@", "u/", "r/", "555", "**", "&amp;", "](", ">"):
        assert bad not in cleaned
    assert "Hi" in cleaned and "link text" in cleaned
    assert "  " not in cleaned


def test_clean_text_has_no_dashes_or_odd_whitespace():
    assert textprep.clean_text("a\u2014b \u2013 c\t d") == "a, b, c d"


def test_chunks_split_sentences_and_respect_limits():
    text = "My mum fell today. She is on the floor and cannot get up! Hello. Tea would be lovely?"
    chunks = textprep.to_chunks(text, min_words=3, max_chars=60)
    assert "Hello." not in chunks  # too short
    assert all(len(c) <= 60 for c in chunks)
    assert any("cannot get up" in c for c in chunks)


def test_chunks_drop_long_junk():
    assert textprep.to_chunks("a " * 400, min_words=3, max_chars=100) == []


def test_dedupe_is_case_and_punctuation_insensitive_and_stable():
    rows = [{"text": "My chest hurts!"}, {"text": "my chest hurts"}, {"text": "water please"}]
    kept = textprep.dedupe(rows)
    assert [r["text"] for r in kept] == ["My chest hurts!", "water please"]


def test_near_duplicate_threshold():
    assert textprep.near_duplicate("my chest hurts a lot", "my chest really hurts a lot", 0.7)
    assert not textprep.near_duplicate("my chest hurts", "bring me some tea", 0.7)


def test_drop_leaks_removes_exact_and_near_matches_of_the_eval_set():
    train = [
        {"id": "a", "text": "Feels like there's an elephant sat on my chest"},
        {"id": "b", "text": "the garden looks lovely today"},
        {"id": "c", "text": "feels like there is an elephant sat on my chest, love"},
    ]
    evals = ["Feels like there's an elephant sat on my chest, love."]
    kept = textprep.drop_leaks(train, evals, threshold=0.7)
    assert [r["id"] for r in kept] == ["b"]


def test_stable_bucket_is_deterministic_and_roughly_uniform():
    buckets = [textprep.stable_bucket(f"text {i}", 10) for i in range(2000)]
    assert buckets == [textprep.stable_bucket(f"text {i}", 10) for i in range(2000)]
    assert min(np.bincount(buckets)) > 120


# ---- metrics ----


def test_report_counts_under_and_over_escalation():
    y_true = [1, 2, 3, 4, 4, 3]
    y_pred = [1, 3, 3, 3, 4, 2]
    rep = metrics.report(y_true, y_pred)
    assert rep["n"] == 6
    assert rep["under_escalations"] == 2  # true 4 -> 3 and true 3 -> 2
    assert rep["over_escalation_rate"] == pytest.approx(1 / 6)
    assert rep["recall"][4] == pytest.approx(0.5)
    assert rep["false_alarm_rate"] == pytest.approx(1 / 2)  # true < 3 predicted >= 3: 1 of 2
    assert rep["precision"][3] == pytest.approx(1 / 3)
    assert rep["urgent_recall"] == pytest.approx(3 / 4)  # true >= 3 and predicted >= 3
    assert rep["confusion"][4][3] == 1


def test_report_handles_empty_classes():
    rep = metrics.report([1, 1], [1, 1])
    assert rep["recall"][4] == 0.0 and rep["precision"][4] == 0.0


def test_choose_shift_prefers_fewer_misses_then_fewer_false_alarms():
    # logits for 4 classes; true urgent rows score slightly low on classes 3 and 4
    logits = np.array(
        [
            [2.0, 0.0, 1.8, 0.0],  # true 3, argmax 1 until the shift lifts class 3
            [2.0, 0.0, 0.0, 1.9],  # true 4
            [3.0, 0.0, 0.0, 0.0],  # true 1, firmly 1
            [0.0, 3.0, 0.0, 0.0],  # true 2, firmly 2
        ]
    )
    y = [3, 4, 1, 2]
    shift = metrics.choose_shift(logits, y, grid=[0.0, 0.5, 1.0, 2.0], miss_cost=10.0)
    assert shift[2] > 0 and shift[3] > 0
    predicted = (logits + shift).argmax(axis=1) + 1
    assert list(predicted) == y


def test_choose_shift_without_misses_picks_the_smallest_shift():
    logits = np.array([[3.0, 0.0, 0.0, 0.0], [0.0, 0.0, 3.0, 0.0]])
    shift = metrics.choose_shift(logits, [1, 3], grid=[0.0, 1.0, 2.0], miss_cost=10.0)
    assert list(shift) == [0.0, 0.0, 0.0, 0.0]


# ---- labels ----


def test_parse_label_accepts_digits_and_json_and_rejects_the_rest():
    assert labels.parse_label("3") == 3
    assert labels.parse_label(' {"urgency": 4} ') == 4
    assert labels.parse_label("urgency 2") == 2
    for bad in ("", "5", "0", "maybe", '{"urgency": 9}', None):
        assert labels.parse_label(bad) is None


def test_read_manual_labels_checks_ids_and_range(tmp_path):
    path = tmp_path / "labels.txt"
    path.write_text("a 3\nb 1\n\nc 4 # note\n")
    assert labels.read_manual_labels(path) == {"a": 3, "b": 1, "c": 4}
    path.write_text("a 7\n")
    with pytest.raises(ValueError):
        labels.read_manual_labels(path)


def test_join_labels_drops_unlabelled_and_keeps_source():
    rows = [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}]
    joined = labels.join_labels(rows, {"a": 2}, source="hand")
    assert joined == [{"id": "a", "text": "x", "urgency": 2, "label_source": "hand"}]


def test_system_prompt_uses_the_triage_definitions():
    prompt = labels.system_prompt()
    assert "4 emergency now" in prompt and "Lean toward escalation" in prompt
    assert "\u2014" not in prompt


def test_agreement_reports_exact_and_urgent_agreement():
    stats = labels.agreement([1, 2, 3, 4, 4], [1, 2, 3, 3, 4])
    assert stats["n"] == 5
    assert stats["exact"] == pytest.approx(0.8)
    assert stats["urgent_agree"] == pytest.approx(1.0)  # both sides agree on >= 3 for every row
    assert stats["urgent_disagreements"] == 0


def test_jsonl_roundtrip(tmp_path):
    rows = [{"id": "a", "text": "héllo"}, {"id": "b", "text": "x"}]
    path = tmp_path / "x.jsonl"
    textprep.write_jsonl(path, rows)
    assert textprep.read_jsonl(path) == rows
    assert json.loads(path.read_text().splitlines()[0])["text"] == "héllo"


# ---- collect ----


def test_post_to_rows_keeps_no_identifying_fields():
    from train import collect

    item = {
        "id": "t3_abc",
        "url": "https://www.reddit.com/r/x/comments/abc/",
        "username": "someone_real",
        "parsedCommunityName": "AgingParents",
        "title": "My mum fell today",
        "body": "She is on the floor and cannot get up. Mail jo@x.com or see http://a.b/c.",
    }
    rows = collect.post_to_rows(item, "reddit")
    assert rows and all(set(r) == {"id", "source", "text"} for r in rows)
    blob = json.dumps(rows)
    for bad in ("someone_real", "jo@x.com", "http", "t3_abc"):
        assert bad not in blob
    assert rows[0]["source"] == "reddit:AgingParents"


# ---- train / export ----


def test_exported_head_matches_sklearn_and_loads_on_the_pi_side(tmp_path):
    pytest.importorskip("sklearn")
    from rover.triage import local
    from train import train

    rng = np.random.default_rng(0)
    centres = np.eye(4, 6) * 3
    y = np.repeat([1, 2, 3, 4], 30)
    X = train.l2_normalise(centres[y - 1] + rng.normal(0, 0.3, (120, 6)))
    model = train.fit_head(X, y, c=4.0)
    shift = np.array([0.0, 0.0, 0.5, 0.5])
    train.export_head(tmp_path / "h.npz", model, shift, "fake/model")
    head = local.load_head(tmp_path / "h.npz")
    assert head.model == "fake/model"
    logits = train.full_logits(model, X) + shift
    expected = logits.argmax(axis=1) + 1
    got = np.array([head.predict(x)[0] for x in X])
    assert (got == expected).all()
    assert (tmp_path / "h.npz").stat().st_size < 20_000


def test_export_never_predicts_a_class_absent_from_training(tmp_path):
    pytest.importorskip("sklearn")
    from rover.triage import local
    from train import train

    X = train.l2_normalise(np.random.default_rng(1).normal(size=(60, 5)))
    y = np.repeat([1, 2, 3], 20)
    train.export_head(tmp_path / "h.npz", train.fit_head(X, y), np.zeros(4), "m")
    head = local.load_head(tmp_path / "h.npz")
    assert all(head.predict(x)[0] != 4 for x in X)
