import importlib.util
import json
from pathlib import Path

import httpx
import pytest

SPEC = importlib.util.spec_from_file_location(
    "eval_triage", Path(__file__).resolve().parents[1] / "dev" / "eval_triage.py"
)
eval_triage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(eval_triage)

EXAMPLES = [
    {
        "call_id": "c1",
        "transcript": [{"speaker": "resident", "text": "my chest hurts"}],
        "robot_urgency": 2,
        "nurse_urgency": 4,
        "category": "cardiac",
    },
    {"call_id": "c2", "transcript": [], "robot_urgency": 2, "nurse_urgency": 2},
]


def test_default_input_does_not_point_at_a_sibling_worktree():
    for path in eval_triage.HARD_CASES, *eval_triage.DEFAULT_FILES:
        assert "calhacks-13" not in str(path)
        assert path.is_file()


def test_examples_become_cases_with_the_nurse_urgency_as_label():
    cases = eval_triage.cases_from_examples(EXAMPLES)
    assert cases[0] == {
        "id": "override-c1",
        "transcript": [["resident", "my chest hurts"]],
        "risk_flags": [],
        "expected_urgency": 4,
        "expected_category": "cardiac",
    }
    assert cases[1]["expected_category"] == "ambiguous"


def test_fetch_labelled_sends_the_api_key():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=EXAMPLES)

    got = eval_triage.fetch_labelled(
        "http://api.test", "secret", transport=httpx.MockTransport(handler)
    )
    assert got == EXAMPLES
    assert seen[0].url.path == "/labelled-examples"
    assert seen[0].headers["X-API-Key"] == "secret"


def test_fetch_labelled_failure_is_an_error():
    transport = httpx.MockTransport(lambda request: httpx.Response(500))
    with pytest.raises(eval_triage.CaseError):
        eval_triage.fetch_labelled("http://api.test", "", transport=transport)


def test_jsonl_file_mode(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text(json.dumps({"id": "a"}) + "\n\n" + json.dumps({"id": "b"}) + "\n")
    assert [c["id"] for c in eval_triage.load_cases([path])] == ["a", "b"]
    with pytest.raises(eval_triage.CaseError):
        eval_triage.load_cases([tmp_path / "missing.jsonl"])


def test_mock_mode_uses_local_cases_and_no_network(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("network used")

    monkeypatch.setattr(eval_triage, "fetch_labelled", no_network)
    cases = eval_triage.resolve_cases(paths=[], mock=True)
    assert cases and all("expected_urgency" in c for c in cases)


def test_files_mode_skips_the_api(monkeypatch, tmp_path):
    monkeypatch.setattr(eval_triage, "fetch_labelled", lambda *a, **k: 1 / 0)
    path = tmp_path / "c.jsonl"
    path.write_text(json.dumps({"id": "a"}) + "\n")
    assert eval_triage.resolve_cases(paths=[path], mock=False) == [{"id": "a"}]


def test_default_mode_fetches_the_api_and_adds_hard_cases(monkeypatch):
    monkeypatch.setattr(eval_triage, "fetch_labelled", lambda url, key, **k: EXAMPLES)
    cases = eval_triage.resolve_cases(paths=[], mock=False)
    assert cases[0]["id"] == "override-c1"
    assert any(c["id"].startswith("h4-") for c in cases)


def test_mock_triager_is_deterministic_and_escalates():
    transcript = [("resident", "Quick, she's hit the deck and not getting up")]
    first = eval_triage.mock_triage(transcript, [])
    assert first == eval_triage.mock_triage(transcript, [])
    assert first.urgency == 4
    assert eval_triage.mock_triage([("resident", "hello there")], []).urgency == 3


def test_main_mock_runs_offline_and_writes_predictions(monkeypatch, tmp_path, capsys):
    from rover import config

    monkeypatch.setattr(config, "RUNS_DIR", tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert eval_triage.main(["--mock"]) == 0
    assert "UNDER-ESCALATIONS: 0" in capsys.readouterr().out
    assert (tmp_path / "predictions.json").is_file()
