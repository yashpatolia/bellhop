"""Local triage scorer: embeddings + a tiny linear head. Offline, tiny fixtures."""

import numpy as np
import pytest

from rover import config
from rover.triage import local
from rover.triage import triage as triage_module
from rover.triage.triage import TriageResult, triage

TRANSCRIPT = [("resident", "Hello."), ("robot", "Hi!"), ("resident", "my chest hurts so much")]
CLAUDE = TriageResult(2, "request", "Wants water.", 0.9, "claude")


def make_head(path, dim=4, shift=(0, 0, 0, 0), model="fake/model"):
    weights = np.zeros((4, dim), dtype=np.float32)
    for level in range(4):
        weights[level, level] = 5.0 * (level + 1)
    np.savez(
        path,
        weights=weights,
        bias=np.zeros(4, dtype=np.float32),
        shift=np.asarray(shift, dtype=np.float32),
        model=np.asarray(model),
    )
    return weights


def fake_embed(text):
    """Axis 0 for 'water', axis 1 for 'chest', axis 2 otherwise."""
    vec = np.zeros(4, dtype=np.float32)
    vec[0 if "water" in text else 1 if "chest" in text else 2] = 3.0
    return vec


def test_softmax_sums_to_one_and_is_stable_for_large_logits():
    probs = local.softmax(np.array([1000.0, 1001.0, 999.0, 0.0]))
    assert probs.sum() == pytest.approx(1.0)
    assert np.isfinite(probs).all()


def test_head_roundtrip_and_predict(tmp_path):
    make_head(tmp_path / "head.npz")
    head = local.load_head(tmp_path / "head.npz")
    assert head is not None
    assert head.model == "fake/model"
    urgency, confidence = head.predict(np.array([0.0, 1.0, 0.0, 0.0]))
    assert urgency == 2  # axis 1 carries class index 1 -> urgency 2
    assert 0.0 < confidence <= 1.0


def test_shift_tilts_the_decision_toward_a_class(tmp_path):
    make_head(tmp_path / "head.npz", shift=(0, 0, 0, 0))
    plain = local.load_head(tmp_path / "head.npz")
    make_head(tmp_path / "tilted.npz", shift=(0, 0, 0, 100))
    tilted = local.load_head(tmp_path / "tilted.npz")
    vec = np.array([0.0, 1.0, 0.0, 0.0])
    assert plain.predict(vec)[0] == 2
    assert tilted.predict(vec)[0] == 4


def test_embeddings_are_normalised_before_the_head(tmp_path):
    make_head(tmp_path / "head.npz")
    head = local.load_head(tmp_path / "head.npz")
    assert head.predict(np.array([0.0, 7.0, 0.0, 0.0])) == head.predict(
        np.array([0.0, 0.1, 0.0, 0.0])
    )


def test_load_head_missing_or_corrupt_returns_none(tmp_path):
    assert local.load_head(tmp_path / "nope.npz") is None
    (tmp_path / "bad.npz").write_bytes(b"not an npz")
    assert local.load_head(tmp_path / "bad.npz") is None
    np.savez(tmp_path / "short.npz", weights=np.zeros((3, 2)))
    assert local.load_head(tmp_path / "short.npz") is None


def test_load_scorer_degrades_to_none(tmp_path):
    def boom(model, directory):
        raise RuntimeError("model files missing")

    assert local.load_scorer(tmp_path / "nope.npz", tmp_path, lambda m, d: fake_embed) is None
    make_head(tmp_path / "head.npz")
    assert local.load_scorer(tmp_path / "head.npz", tmp_path, boom) is None


def test_scorer_predicts_and_is_none_on_embed_failure(tmp_path):
    make_head(tmp_path / "head.npz")
    scorer = local.load_scorer(tmp_path / "head.npz", tmp_path, lambda m, d: fake_embed)
    assert scorer.predict("my chest hurts")[0] == 2
    assert scorer.predict("   ") is None

    def broken(text):
        raise ValueError("onnx failed")

    bad = local.LocalScorer(scorer.head, broken)
    assert bad.predict("my chest hurts") is None


def test_score_transcript_takes_the_most_urgent_resident_line(tmp_path):
    make_head(tmp_path / "head.npz")
    scorer = local.load_scorer(tmp_path / "head.npz", tmp_path, lambda m, d: fake_embed)
    transcript = [("resident", "water please"), ("robot", "sure"), ("resident", "chest")]
    urgency, _ = local.score_transcript(scorer, transcript)
    assert urgency == 2
    assert local.score_transcript(scorer, [("robot", "hi")]) is None
    assert local.score_transcript(None, transcript) is None


def test_raise_only_merge(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_MIN_CONFIDENCE", 0.5)
    assert triage_module.raise_urgency(CLAUDE, (4, 0.9)).urgency == 4
    assert triage_module.raise_urgency(CLAUDE, (4, 0.9)).source == "claude+local"
    assert triage_module.raise_urgency(CLAUDE, (2, 0.9)) is CLAUDE  # equal: unchanged
    assert triage_module.raise_urgency(CLAUDE, (1, 0.99)) is CLAUDE  # never lowers
    assert triage_module.raise_urgency(CLAUDE, (4, 0.3)) is CLAUDE  # unsure: ignored
    assert triage_module.raise_urgency(CLAUDE, None) is CLAUDE


def test_raise_keeps_summary_and_confidence(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_MIN_CONFIDENCE", 0.5)
    raised = triage_module.raise_urgency(CLAUDE, (3, 0.9))
    assert (raised.summary, raised.confidence, raised.category) == ("Wants water.", 0.9, "request")


def test_no_model_answer_only_a_serious_local_score_is_used(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_MIN_CONFIDENCE", 0.5)
    assert triage_module.raise_urgency(None, (2, 0.99)) is None
    result = triage_module.raise_urgency(None, (4, 0.9), summary='Resident said: "chest"')
    assert result.urgency == 4
    assert result.source == "local"
    assert result.confidence == config.LOCAL_ONLY_CONFIDENCE


def answer(result):
    return lambda transcript, risk_flags: result


def test_triage_raises_with_local_input():
    result = triage(
        TRANSCRIPT,
        [],
        ask_claude=answer(CLAUDE),
        ask_local=lambda transcript: (4, 0.95),
    )
    assert (result.urgency, result.source) == (4, "claude+local")


def test_triage_ignores_a_crashing_or_missing_local():
    def crash(transcript):
        raise RuntimeError("onnx exploded")

    for ask in (crash, lambda transcript: None):
        result = triage(
            TRANSCRIPT, [], ask_claude=answer(CLAUDE), ask_local=ask
        )
        assert result == CLAUDE


def test_triage_local_cannot_lower():
    result = triage(
        TRANSCRIPT,
        [],
        ask_claude=answer(TriageResult(4, "fall", "x", 0.9, "claude")),
        ask_local=lambda transcript: (1, 0.99),
    )
    assert result.urgency == 4


def test_triage_default_local_is_off_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_TRIAGE", False)
    monkeypatch.setattr(local, "get_scorer", lambda: pytest.fail("must not load when disabled"))
    result = triage(TRANSCRIPT, [], ask_claude=answer(CLAUDE))
    assert result == CLAUDE
    assert triage_module._real_ask_local(TRANSCRIPT) is None
