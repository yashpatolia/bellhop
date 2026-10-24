# Testing

- Runner: `uv run pytest` from `backend/`. `asyncio_mode=auto` is on but the code is sync.
- `tests/unit/`: one module at a time, in-memory adapters, fake clock (`clock` fixture) and sequential ids (`ids` fixture) from `tests/conftest.py`. No sleeping, no network.
- `tests/integration/`: wire the real container with in-memory adapters; drive through services or the HTTP API; assert end-to-end behaviour (bell press to alert).
- Contract tests: any new adapter must pass the same parametrized tests as the in-memory one.
- Assert behaviour, not mocks. Prefer real in-memory adapters over `Mock`.
- Name tests as sentences: `test_urgency_four_alerts_every_nurse_on_shift`.
- Latency budget tests (memory recall under 50 ms) use generous bounds to avoid flakiness.
- Demo scenes from `docs/plan/01-project.md` (tea, hip pain, fall) must exist as integration tests.

## Current state
- 901 passed, 1 skipped (`test_fetchai_agent.py` skips without `uagents`); `ruff check src tests` clean. Verification detail: [11-status.md](11-status.md).
- Property tests (`tests/unit/test_properties.py`) use `hypothesis` for the urgency ratchet, state machine and similar invariants.
- Contract drift test (`tests/unit/test_contract.py`): fails when `contracts/openapi.json` or the examples no longer match the app. Regenerate with `cd backend && uv run python scripts/export_contract.py`, then commit `contracts/`.
- Bug records: a known bug is written as a test marked `@pytest.mark.xfail(strict=True, reason="BUG: ...")`. It stays green while the bug exists and fails loudly (XPASS) when someone fixes it, which tells the fixer to delete the marker. See `tests/integration/test_edge_cases_2.py`.
- Triage evaluation: judge it on fresh, independently written phrase batches, not on the labelled set the code was tuned on. Measured keyword-guard recall was 20/24, 19/24 and 11/24 on three fresh batches; scores on tuned data would have looked far better. Write a new batch before trusting any triage change.
- Memory extraction evaluation: `uv run python -m bellhop.labelled.memory_eval --extractor rule|claude` scores stored-fact precision, recall and forbidden facts on 30 labelled conversations (see [15-memory-learning.md](15-memory-learning.md)). Treat the set as a development set; write a fresh batch before trusting a model score.
- CI (`.github/workflows/backend.yml`): lint, format check and the full suite on every push and pull request touching `backend/` or `contracts/`.
