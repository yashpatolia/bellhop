from bellhop.labelled.__main__ import main
from bellhop.labelled.cases import CASES
from bellhop.labelled.io import load_jsonl


def test_cli_writes_file_and_prints_summary(tmp_path, capsys):
    out = tmp_path / "labelled_cases.jsonl"
    assert main([str(out)]) == 0
    assert load_jsonl(out) == list(CASES)
    assert f"{len(CASES)} cases" in capsys.readouterr().out
