from bellhop.labelled.cases import CASES, LabelledCase
from bellhop.labelled.io import from_overrides, load_jsonl, save_jsonl


def test_jsonl_round_trip(tmp_path):
    path = tmp_path / "nested" / "cases.jsonl"
    save_jsonl(CASES, path)
    assert load_jsonl(path) == list(CASES)
    assert len(path.read_text().splitlines()) == len(CASES)


def test_from_overrides_uses_nurse_urgency_as_label():
    examples = [
        {
            "call_id": "c1",
            "transcript": [{"speaker": "resident", "text": "my chest hurts"}],
            "robot_urgency": 2,
            "nurse_urgency": 4,
        }
    ]
    [case] = from_overrides(examples)
    assert isinstance(case, LabelledCase)
    assert case.id == "override-c1"
    assert case.transcript == [("resident", "my chest hurts")]
    assert case.expected_urgency == 4
    assert case.risk_flags == []
    assert "robot scored 2" in case.note
