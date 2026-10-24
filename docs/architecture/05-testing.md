# Testing

- Runner: `uv run pytest` from `backend/`. `asyncio_mode=auto` is on but the code is sync.
- `tests/unit/`: one module at a time, in-memory adapters, fake clock (`clock` fixture) and sequential ids (`ids` fixture) from `tests/conftest.py`. No sleeping, no network.
- `tests/integration/`: wire the real container with in-memory adapters; drive through services or the HTTP API; assert end-to-end behaviour (bell press to alert).
- Contract tests: any new adapter must pass the same parametrized tests as the in-memory one.
- Assert behaviour, not mocks. Prefer real in-memory adapters over `Mock`.
- Name tests as sentences: `test_urgency_four_alerts_every_nurse_on_shift`.
- Latency budget tests (memory recall under 50 ms) use generous bounds to avoid flakiness.
- Demo scenes from `docs/plan/01-project.md` (tea, hip pain, fall) must exist as integration tests.
