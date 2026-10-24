import pytest

from rover import config


@pytest.fixture(autouse=True)
def local_triage_off(monkeypatch):
    """Tests never load the real embedding model; test_local_triage.py injects fakes."""
    monkeypatch.setattr(config, "LOCAL_TRIAGE", False)


@pytest.fixture(autouse=True)
def no_jev_key(monkeypatch):
    """A real TYPESAFE_API_KEY in the shell must never make a test call Jev."""
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
