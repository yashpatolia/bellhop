from datetime import UTC, datetime, timedelta

import pytest


class FakeClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 10, 24, 9, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._now

    def advance(self, **kw: float) -> None:
        self._now += timedelta(**kw)


class SeqIds:
    def __init__(self) -> None:
        self._n = 0

    def new_id(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n}"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def ids() -> SeqIds:
    return SeqIds()
