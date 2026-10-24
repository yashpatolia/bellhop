"""API hardening: optional shared-secret auth, input limits, caps, nurse override."""

import pytest
from fastapi.testclient import TestClient

from bellhop.api.app import create_app
from bellhop.container import Settings, build_container


def make_client(**kw) -> TestClient:
    settings = Settings(seed_demo=True, guard_timeouts=False, **kw)
    return TestClient(create_app(build_container(settings)))


@pytest.fixture
def client():
    return make_client()


@pytest.fixture
def secured():
    return make_client(api_key="s3cret")


KEY = {"X-API-Key": "s3cret"}


# ---- auth ----------------------------------------------------------------------------


def test_no_key_configured_means_open(client):
    assert client.get("/calls").status_code == 200


def test_key_required_on_reads_and_writes(secured):
    assert secured.get("/calls").status_code == 401
    assert secured.get("/residents/res_margaret/care/summary").status_code == 401
    assert secured.post("/calls", json={"room": "12"}).status_code == 401
    assert secured.delete("/residents/res_margaret/memory").status_code == 401
    assert secured.get("/labelled-examples").status_code == 401


def test_wrong_key_rejected_right_key_accepted(secured):
    assert secured.get("/calls", headers={"X-API-Key": "nope"}).status_code == 401
    assert secured.get("/calls", headers=KEY).status_code == 200
    assert secured.post("/calls", json={"room": "12"}, headers=KEY).status_code == 201


def test_health_and_preflight_stay_open(secured):
    assert secured.get("/health").status_code == 200
    r = secured.options(
        "/calls",
        headers={"Origin": "http://x.test", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 200


def test_unauthorised_response_carries_cors_header(secured):
    r = secured.get("/calls", headers={"Origin": "http://x.test"})
    assert r.status_code == 401
    assert r.headers["access-control-allow-origin"] == "*"


def test_openapi_always_declares_api_key_scheme(client):
    spec = client.get("/openapi.json").json()
    scheme = spec["components"]["securitySchemes"]["ApiKeyAuth"]
    assert scheme == {"type": "apiKey", "in": "header", "name": "X-API-Key"}
    assert {"ApiKeyAuth": []} in spec["paths"]["/calls"]["get"]["security"]
    assert "security" not in spec["paths"]["/health"]["get"]


def test_openapi_is_identical_with_and_without_key(client, secured):
    assert client.get("/openapi.json").json() == secured.get("/openapi.json").json()


def test_settings_repr_hides_secrets():
    s = Settings(api_key="k1", apify_token="k2", moss_project_key="k3", spacetimedb_token="k4")
    text = repr(s)
    assert not any(k in text for k in ("k1", "k2", "k3", "k4"))


def test_settings_from_env_reads_new_vars(monkeypatch):
    monkeypatch.setenv("BELLHOP_API_KEY", "abc")
    monkeypatch.setenv("BELLHOP_CORS_ORIGINS", "http://a.test, http://b.test")
    monkeypatch.setenv("BELLHOP_ALLOW_NEW_ROBOTS", "0")
    s = Settings.from_env()
    assert s.api_key == "abc"
    assert s.cors_origins == ("http://a.test", "http://b.test")
    assert s.allow_new_robots is False


def test_settings_defaults(monkeypatch):
    for v in ("BELLHOP_API_KEY", "BELLHOP_CORS_ORIGINS", "BELLHOP_ALLOW_NEW_ROBOTS"):
        monkeypatch.delenv(v, raising=False)
    s = Settings.from_env()
    assert s.api_key is None and s.cors_origins == ("*",) and s.allow_new_robots is True


# ---- CORS ----------------------------------------------------------------------------


def test_cors_origin_restricted_by_setting():
    c = make_client(cors_origins=("http://dash.test",))
    ok = c.get("/health", headers={"Origin": "http://dash.test"})
    bad = c.get("/health", headers={"Origin": "http://evil.test"})
    assert ok.headers["access-control-allow-origin"] == "http://dash.test"
    assert "access-control-allow-origin" not in bad.headers


# ---- URL scheme checks ---------------------------------------------------------------


@pytest.mark.parametrize("kw", [{"robot_url": "file:///etc/passwd"}, {"robot_url": "ftp://h"}])
def test_robot_url_scheme_checked(kw):
    with pytest.raises(ValueError, match="BELLHOP_ROBOT_URL"):
        build_container(Settings(**kw))


def test_stdb_url_scheme_checked():
    with pytest.raises(ValueError, match="BELLHOP_STDB_URL"):
        build_container(Settings(store="spacetimedb", spacetimedb_url="ws://h:3000"))


# ---- input limits --------------------------------------------------------------------


def _call(client) -> str:
    return client.post("/calls", json={"room": "12"}).json()["id"]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/calls", {"room": "r" * 33}),
        ("/calls/{c}/turns", {"speaker": "s" * 33, "text": "hi"}),
        ("/calls/{c}/turns", {"speaker": "resident", "text": "t" * 2001}),
        ("/calls/{c}/score", {"urgency": 1, "category": "c" * 65}),
        ("/calls/{c}/score", {"urgency": 1, "category": "c", "summary": "s" * 501}),
        ("/alerts/a1/ack", {"nurse_id": "n" * 65}),
        ("/residents/res_margaret/memory", {"text": "x" * 2001}),
        ("/residents/res_margaret/memory", {"text": "ok fact", "tags": ["t"] * 11}),
        ("/residents/res_margaret/memory", {"text": "ok fact", "tags": ["t" * 33]}),
        ("/residents/res_margaret/memory", {"text": "ok fact", "source": "s" * 33}),
        ("/residents/res_margaret/care", {"kind": "drink", "note": "n" * 501}),
        ("/residents/res_margaret/care", {"kind": "drink", "call_id": "c" * 65}),
    ],
)
def test_oversized_fields_are_422(client, path, body):
    r = client.post(path.format(c=_call(client)), json=body)
    assert r.status_code == 422


def test_recall_and_reminiscence_limits(client):
    base = "/residents/res_margaret"
    assert client.get(f"{base}/memory", params={"q": "q" * 501}).status_code == 422
    assert client.get(f"{base}/memory", params={"k": 0}).status_code == 422
    assert client.get(f"{base}/memory", params={"k": 21}).status_code == 422
    assert client.get(f"{base}/memory", params={"k": 20}).status_code == 200
    assert client.get(f"{base}/reminiscence", params={"k": 0}).status_code == 422
    assert client.get(f"{base}/reminiscence", params={"k": 21}).status_code == 422


def test_body_over_1mb_is_413(client):
    r = client.post(
        "/calls", content=b"x" * (1024 * 1024 + 1), headers={"content-type": "application/json"}
    )
    assert r.status_code == 413


def test_body_over_1mb_without_content_length_is_413(client):
    def chunks():
        for _ in range(3):
            yield b"x" * (512 * 1024)

    r = client.post("/calls", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413


# ---- caps ----------------------------------------------------------------------------


def test_calls_limit_newest_first(client):
    ids = [_call(client) for _ in range(5)]
    got = client.get("/calls", params={"limit": 2}).json()
    assert [c["id"] for c in got] == ids[::-1][:2]
    assert client.get("/calls", params={"limit": 0}).status_code == 422
    assert client.get("/calls", params={"limit": 1001}).status_code == 422


def test_alerts_limit(client):
    for _ in range(3):
        cid = _call(client)
        client.post(f"/calls/{cid}/score", json={"urgency": 3, "category": "pain"})
    assert len(client.get("/alerts").json()) == 3
    assert len(client.get("/alerts", params={"limit": 2}).json()) == 2
    assert client.get("/alerts", params={"limit": 1001}).status_code == 422


def test_recorders_are_bounded():
    from bellhop.adapters.notifiers import RecordingNotifier
    from bellhop.adapters.robot_gateway import RecordingRobotGateway

    g = RecordingRobotGateway()
    for i in range(1500):
        g.go_to("r", str(i))
    assert len(g.commands) == 1000
    assert g.commands[-1] == ("go_to", "r", "1499")
    n = RecordingNotifier()
    assert n.sent == []
    for _ in range(1500):
        n.send(object())  # type: ignore[arg-type]
    assert len(n.sent) == 1000


def test_unknown_robot_created_by_default(client):
    r = client.put("/robots/pi_new", json={"status": "idle", "battery": 0.5})
    assert r.status_code == 200


def test_unknown_robot_rejected_when_registration_off():
    c = make_client(allow_new_robots=False)
    assert c.put("/robots/pi_new", json={"status": "idle", "battery": 0.5}).status_code == 404
    assert c.put("/robots/robot_1", json={"status": "idle", "battery": 0.5}).status_code == 200


# ---- nurse override ------------------------------------------------------------------


def _resolved_call(client) -> str:
    cid = _call(client)
    client.post(f"/calls/{cid}/turns", json={"speaker": "resident", "text": "my tea is cold"})
    client.post(f"/calls/{cid}/score", json={"urgency": 1, "category": "social"})
    client.post(f"/calls/{cid}/resolve", json={})
    return cid


def test_override_feeds_labelled_examples(client):
    assert client.get("/labelled-examples").json() == []
    cid = _resolved_call(client)
    r = client.post(f"/calls/{cid}/override", json={"urgency": 3, "nurse_id": "nurse_priya"})
    assert r.status_code == 200
    (ex,) = client.get("/labelled-examples").json()
    assert ex["call_id"] == cid
    assert ex["robot_urgency"] == 1
    assert ex["nurse_urgency"] == 3
    assert ex["transcript"] == [{"speaker": "resident", "text": "my tea is cold"}]


def test_override_unknown_call_is_404(client):
    assert client.post("/calls/nope/override", json={"urgency": 2}).status_code == 404


def test_override_before_visit_is_409(client):
    cid = _call(client)
    r = client.post(f"/calls/{cid}/override", json={"urgency": 2})
    assert r.status_code == 409
    assert "resolve" in r.json()["detail"]


@pytest.mark.parametrize("urgency", [0, 5])
def test_override_urgency_range(client, urgency):
    cid = _resolved_call(client)
    assert client.post(f"/calls/{cid}/override", json={"urgency": urgency}).status_code == 422
