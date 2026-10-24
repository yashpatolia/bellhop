import pytest
from fastapi.testclient import TestClient

from bellhop.adapters.apify_content import ApifyContentFeed
from bellhop.adapters.local_content import LocalContentFeed
from bellhop.adapters.wikipedia_content import WikipediaContentFeed
from bellhop.api.app import create_app
from bellhop.container import Settings, build_container

RES = "/residents/res_margaret"


@pytest.fixture
def container():
    return build_container(Settings(seed_demo=True))


@pytest.fixture
def client(container) -> TestClient:
    return TestClient(create_app(container))


def test_settings_content_defaults_to_local_and_reads_env(monkeypatch):
    monkeypatch.delenv("BELLHOP_CONTENT", raising=False)
    assert Settings.from_env().content == "local"
    monkeypatch.setenv("BELLHOP_CONTENT", "wikipedia")
    monkeypatch.setenv("APIFY_TOKEN", "tok")
    settings = Settings.from_env()
    assert settings.content == "wikipedia" and settings.apify_token == "tok"


def test_container_picks_the_feed_from_settings():
    assert isinstance(build_container(Settings()).reminiscence._feed, LocalContentFeed)
    wiki = build_container(Settings(content="wikipedia")).reminiscence._feed
    assert isinstance(wiki, WikipediaContentFeed)
    apify = build_container(Settings(content="apify", apify_token="t")).reminiscence._feed
    assert isinstance(apify, ApifyContentFeed)
    with pytest.raises(ValueError):
        build_container(Settings(content="nope"))


def test_margaret_is_seeded_with_a_birth_year(container):
    assert container.store.residents.get("res_margaret").birth_year == 1938


def test_get_reminiscence_returns_era_items(client):
    r = client.get(f"{RES}/reminiscence", params={"k": 3})
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 3
    assert all(1953 <= i["year"] <= 1963 for i in items)
    assert {"id", "kind", "year", "title", "blurb"} <= set(items[0])


def test_get_reminiscence_empty_without_birth_year_and_404_for_unknown(client):
    assert client.get("/residents/res_arthur/reminiscence").json() == []
    assert client.get("/residents/nobody/reminiscence").status_code == 404


def test_ingest_stores_tagged_memories_that_recall_finds(client):
    r = client.post(f"{RES}/reminiscence/ingest", params={"k": 2})
    assert r.status_code == 201
    facts = r.json()
    assert len(facts) == 2 and all("reminiscence" in f["tags"] for f in facts)
    assert client.post("/residents/nobody/reminiscence/ingest").status_code == 404


def test_put_resident_sets_birth_year(client):
    r = client.put("/residents/res_arthur", json={"birth_year": 1935})
    assert r.status_code == 200 and r.json()["birth_year"] == 1935
    assert len(client.get("/residents/res_arthur/reminiscence").json()) > 0
    assert client.put("/residents/res_arthur", json={"birth_year": 1700}).status_code == 422
    assert client.put("/residents/nobody", json={"birth_year": 1935}).status_code == 404
