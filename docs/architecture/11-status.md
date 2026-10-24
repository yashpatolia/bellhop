# Status

Snapshot of 2026-10-23. Read [01-module-map.md](01-module-map.md) for what exists and [09-hardware-interface.md](09-hardware-interface.md) for the Pi contract.

## Numbers (from `cd backend && .venv/bin/python -m pytest -q -p no:warnings`)
| Check | Result |
| --- | --- |
| Tests | Re-run before quoting: HTTP integration tests are temporarily blocked by the lockfile's Starlette 1.9.0 test-client dependency issue (it expects `httpx2`, which is not locked). The last reported green snapshot before the SSE/admin work was 1,002 passed, 1 skipped. |
| Lint | `ruff check src tests` clean |
| Strict xfail | Known-bug records live in `tests/integration/test_edge_cases_2.py` (see [05-testing.md](05-testing.md)) |

Other agents were editing tests while this was written: an earlier run in the same session showed 9 to 12 failures that were gone minutes later. Re-run before quoting these numbers.

Commits (`git log --oneline`):
```
25db187 Add adversarial API regression tests (care, memory, triage, hardening)
49987ca Harden API, add scenario-driven setup, privacy fixes, docs and status
c40cfad Broaden triage keyword floor by pattern; document measured limits
7177682 Wire care signals, visit notes, family, memory guard and triage guard
58dc187 Add robot status routes, Pi gateway and LED signals; care data contract
74585be Add Bellhop backend, architecture docs and frontend contract
6dd6ed4 Add Bellhop plan, research and polished HTML artifacts
```
The working tree contains the pending admin/SSE release and research notes. Do not call it green until `httpx2` is available and the full suite has run.

## Done and verified
| Area | How verified |
| --- | --- |
| Domain rules: state machine, urgency ratchet, charge once | Unit tests plus property tests (hypothesis) |
| Call, dispatch, workload, alerts, feedback, analytics | Unit tests; integration tests through the real container and HTTP API |
| Three demo scenes (tea, hip pain, fall) | Integration tests (`test_demo_scenes.py`) and `scripts/demo_scenes.py` against a real uvicorn server |
| HTTP API, auth header, body limit, field limits, CORS | Integration tests with `TestClient`; `contracts/openapi.json` drift test |
| Runtime home setup | Scenario files and authenticated admin routes create/list/patch residents and nurses; contract examples generated |
| Dashboard live updates | `GET /events` SSE: call lifecycle, alert and robot events; bounded per-client queues, 20-client cap, heartbeat and EventSource query-key support |
| Care signals, memory guard, family, preferences, visit notes | Unit and integration tests |
| Triage guard behaviour as specified | Unit tests (not a measure of real-world recall, see gaps) |
| Wikipedia reminiscence feed | Unit tests with a fake transport, plus a live MediaWiki fetch (real network) |
| Robot gateway wire format and LED signals | Unit tests against a fake HTTP transport; no real Pi |
| SpacetimeDB module build and local server | Verified against a local standalone server (CLI and server 2.13.0), see [06-integrations.md](06-integrations.md) |

## Done but unverified against the real service
| Piece | State |
| --- | --- |
| Moss memory (`adapters/moss_memory.py`) | SDK calls written from docs and guessed; never run with real keys. Falls back to local on any failure |
| Fetch.ai agent (`fetchai/`) | `uagents` was never installed, so the agent never ran. Answer logic and client are unit-tested; `build_agent` is not |
| Apify feed (`apify_content.py`) | Run once through the CLI: about 12 s, one 45 KB page. Adapter code itself never ran against the live actor |
| SpacetimeDB store | Token auth and Maincloud untried; only local, no token |
| `HttpRobotGateway` | Never pointed at a real Pi |

## Known gaps and risks
| Gap | Detail |
| --- | --- |
| Triage keyword guard is weak | Recall on independent fresh batches: 20/24, 19/24, then 11/24 on the paraphrase-heavy batch. Gordon's model is the real safety net; the guard is a backstop (ADR-13) |
| No auth by default | `BELLHOP_API_KEY` is optional; unset means open. CORS default is `*` |
| In-memory default store | State is lost on restart unless `BELLHOP_STORE=spacetimedb` works |
| Other synchronous event handlers | The SSE fan-out is bounded and non-blocking; unrelated synchronous bus handlers can still delay a request |
| Test-client dependency | Starlette 1.9.0's `TestClient` expects `httpx2`, absent from the lockfile; all HTTP integration tests hang until that dev dependency is restored |
| Forgotten memory with Moss on | Removed from the local index only; the Moss copy stays |
| Labelled set is small | 30 fictional cases, plus nurse overrides once calls resolve |

## Blocked or waiting
| Item | Waiting on |
| --- | --- |
| Pi HTTP server (`POST /go_to`, `/led`, `/stop`), its address, battery reporting | Jeremy |
| Marker-to-room map; room ids undecided between 12/14 (seed) and 204/210 (brief) | Jeremy and team |
| Moss project id and key | Sponsor access |
| `uv sync --extra fetch` to install `uagents`, then first run of the agent | Someone to run it |

## Next (ranked)
1. Settle room ids and run the backend against the real Pi (end-to-end bell press).
2. Gordon's model posting to `/score` with `confidence`, then evaluate on fresh phrasings (see [05-testing.md](05-testing.md)).
3. Install the `fetch` extra and run the agent once; fix whatever breaks.
4. Try Moss with real keys; confirm the SDK calls.
5. Try SpacetimeDB with a token, then Maincloud; decide whether persistence is needed for the demo.
6. Set `BELLHOP_API_KEY` and a narrow `BELLHOP_CORS_ORIGINS` for the demo deployment.
7. On demo hardware, test Tailscale inside WSL plus Pi/Yash devices; run with `--host 0.0.0.0`, seed demo data, phone hotspot and backup hotspot. Confirm the Pi's five-second stop-and-idle watchdog.
8. Restore the missing `httpx2` test dependency, then run the full suite and quote its final count.

## Team handoff
| Person | Owns | Needs from the backend or from them |
| --- | --- | --- |
| Yash | Dashboard; [contracts/](../../contracts/README.md) consumer | Use `GET /events` first and poll `GET /calls`, `/alerts`, `/metrics` after reconnect or as fallback; regenerate types when `openapi.json` changes |
| Gordon | Triage model | `POST /calls/{id}/score` with `confidence`; `POST /calls/{id}/triage-failed` on model failure; the labelled set (`python -m bellhop.labelled`, `GET /labelled-examples`) |
| Jeremy | Pi, bell button, LEDs | Everything in [09-hardware-interface.md](09-hardware-interface.md) |
