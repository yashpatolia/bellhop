import importlib.util
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "demo_scenes.py"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("demo_scenes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["demo_scenes"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def client() -> TestClient:
    app = create_app(build_container(Settings(seed_demo=True, guard_timeouts=False)))
    return TestClient(app)


def run(demo, client, *args):
    return demo.main(["--pace", "0", *args], transport=client._transport)


def test_build_steps_covers_each_scene(demo):
    assert {s.scene for s in demo.build_steps("12")} == {1, 2, 3}
    assert {s.scene for s in demo.build_steps("12", scene=2)} == {2}


def test_all_scenes_end_with_expected_metrics_and_alerts(demo, client, capsys):
    assert run(demo, client, "--scene", "all") == 0
    assert "Scene 1" in capsys.readouterr().out
    assert client.get("/metrics").json()["resolved_without_nurse"] >= 1
    alerts = client.get("/alerts").json()
    assert len(alerts) == 2
    by_level = {a["level"]: a for a in alerts}
    assert by_level[3]["nurse_id"] is not None
    assert by_level[4]["nurse_id"] is None


def test_single_scene_runs_alone(demo, client):
    assert run(demo, client, "--scene", "1") == 0
    assert client.get("/alerts").json() == []


def test_unreachable_server_exits_nonzero(demo, capsys):
    def refuse(request):
        raise httpx.ConnectError("refused", request=request)

    code = demo.main(["--pace", "0"], transport=httpx.MockTransport(refuse))
    assert code != 0
    assert "reach" in capsys.readouterr().err.lower()


def test_unexpected_status_exits_nonzero(demo, capsys):
    transport = httpx.MockTransport(lambda request: httpx.Response(500, json={}))
    assert demo.main(["--pace", "0"], transport=transport) != 0
    assert "500" in capsys.readouterr().err
