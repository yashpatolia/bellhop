import importlib.util
import json
import sys
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "devtail", Path(__file__).resolve().parents[1] / "dev" / "tail.py"
)
devtail = importlib.util.module_from_spec(SPEC)
sys.modules["devtail"] = devtail
SPEC.loader.exec_module(devtail)


def write(path, rows, junk=()):
    lines = [json.dumps(r) for r in rows] + list(junk)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def logs(tmp_path):
    drive = write(
        tmp_path / "drive.jsonl",
        [
            {"t": 10.0, "component": "drive", "event": "drive.go_to", "room": "12"},
            {"t": 12.5, "component": "drive", "event": "drive.arrived", "room": "12"},
        ],
    )
    speech = write(
        tmp_path / "speech.jsonl",
        [
            {
                "t": 11.0,
                "component": "speech",
                "event": "backend.request",
                "call_id": "c1",
                "status": 200,
            },
            {"t": 13.0, "component": "speech", "event": "visit.end", "call_id": "c2"},
            {"t": 9.0, "component": "speech", "event": "status.report", "status": "idle"},
        ],
        junk=["not json", '{"no_time": 1}', '{"t": "x"}'],
    )
    return [drive, speech]


def test_merges_by_time_and_skips_bad_lines(tmp_path):
    rows = devtail.merge(logs(tmp_path))
    assert [r["t"] for r in rows] == [9.0, 10.0, 11.0, 12.5, 13.0]


def test_filters(tmp_path):
    paths = logs(tmp_path)
    assert [r["t"] for r in devtail.merge(paths, call="c1")] == [11.0]
    assert [r["t"] for r in devtail.merge(paths, components={"drive"})] == [10.0, 12.5]
    assert [r["event"] for r in devtail.merge(paths, event="arrived")] == ["drive.arrived"]
    assert [r["t"] for r in devtail.merge(paths, since=12.0)] == [12.5, 13.0]


def test_missing_file_is_reported_not_fatal(tmp_path, capsys):
    paths = [*logs(tmp_path), tmp_path / "nope.jsonl"]
    assert len(devtail.merge(paths)) == 5
    assert "cannot read" in capsys.readouterr().err


def test_format_and_cli(tmp_path, capsys):
    paths = logs(tmp_path)
    assert devtail.main([*map(str, paths), "--call", "c1"]) == 0
    out = capsys.readouterr().out
    assert "speech" in out and "backend.request" in out and "status=200" in out
    assert "call_id=c1" in out and "drive.go_to" not in out
    devtail.main([*map(str, paths), "--component", "drive", "--json"])
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line)["event"] for line in lines] == ["drive.go_to", "drive.arrived"]


def test_since_parses_clock_time_and_epoch():
    assert devtail.parse_since("123.5") == 123.5
    assert devtail.parse_since("12:00:00") < devtail.parse_since("12:00:01")


def test_follow_picks_up_new_and_half_written_lines(tmp_path):
    path = tmp_path / "a.jsonl"
    path.write_text(
        json.dumps({"t": 1.0, "event": "one"}) + "\n" + '{"t": 2.0, "ev', encoding="utf-8"
    )
    stream = devtail.follow([path], call=None, components=None, event=None, since=None)
    assert next(stream)["event"] == "one"
    with path.open("a", encoding="utf-8") as handle:
        handle.write('ent": "two"}\n')
    assert next(stream)["event"] == "two"
