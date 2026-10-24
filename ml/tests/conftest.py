import pytest

from rover import config


@pytest.fixture(autouse=True)
def local_triage_off(monkeypatch):
    """Tests never load the real embedding model; test_local_triage.py injects fakes."""
    monkeypatch.setattr(config, "LOCAL_TRIAGE", False)
