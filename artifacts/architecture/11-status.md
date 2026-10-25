# Status

Snapshot of 2026-10-24. Single-file handoff: [context.md](../context.md). Read [01-module-map.md](01-module-map.md) for what exists and [09-hardware-interface.md](09-hardware-interface.md) for the Pi contract.

## Numbers (from `cd backend && .venv/bin/python -m pytest -q -p no:warnings`)
| Check | Result |
| --- | --- |
| Tests | 1069 passed, 1 skipped, exit 0 (2026-10-24, full suite) |
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
Admin routes, SSE and research notes are merged on master (eb62be9, with the dashboard).

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

## Dashboard and simulator (2026-10-24)
| Area | State |
| --- | --- |
| Dashboard on the real backend | Done and run in a browser: live calls, alerts, robots, metrics over REST plus SSE, "I'm on my way", "Mark done", review queue, staff notes, offline and empty states. Unit tests cover the wire adapter and the store against `contracts/examples` |
| Simulator | Done: seeds and plays a home through the public routes; tested against the real backend |
| Not done | Staff login, a UI to add residents, SpacetimeDB persistence for memory facts, care data and medical history, nothing yet run with the real robot |

## Known gaps and risks
| Gap | Detail |
| --- | --- |
| Triage keyword guard is weak | Recall on independent fresh batches: 20/24, 19/24, then 11/24 on the paraphrase-heavy batch. Gordon's model is the real safety net; the guard is a backstop (ADR-13) |
| No auth by default | `BELLHOP_API_KEY` is optional; unset means open. CORS default is `*` |
| In-memory default store | State is lost on restart unless `BELLHOP_STORE=spacetimedb` works. With it, calls, residents, memory facts, the review queue, care data and medical history persist (tested against a fake server; the module typechecks, but it has not been published to a real server since these tables were added) |
| `POST /calls` blocks while `go_to` hangs | The Dispatcher runs synchronously in the bell request, so a hung Pi costs up to the 2 s guard timeout (and holds the `CallService` lock). Not fixed: an async dispatch needs its completion to share that lock and reorders `call.assigned` and the LED signal. Details in [09-hardware-interface.md](09-hardware-interface.md) |
| Ghost drive is only mitigated | After a `go_to` timeout the backend sends `/stop` now and once more one guard window later (heuristic). The Pi should reject stale `go_to`; a late `/stop` can also cut a legitimate drive started in that window |
| Other synchronous event handlers | The SSE fan-out is bounded and non-blocking; unrelated synchronous bus handlers can still delay a request |
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
8. Run the real robot against the backend (`scripts/dev.sh empty`) and check the dashboard shows it. The dashboard live mode and the ML merge are done (see artifacts/context.md sections 4 and 5).

## Team handoff
| Person | Owns | Needs from the backend or from them |
| --- | --- | --- |
| Yash | Dashboard; [contracts/](../components/contracts.md) consumer | Use `GET /events` first and poll `GET /calls`, `/alerts`, `/metrics` after reconnect or as fallback; regenerate types when `openapi.json` changes |
| Gordon | Triage model | `POST /calls/{id}/score` with `confidence`; `POST /calls/{id}/triage-failed` on model failure; the labelled set (`python -m bellhop.labelled`, `GET /labelled-examples`) |
| Jeremy | Pi, bell button, LEDs | Everything in [09-hardware-interface.md](09-hardware-interface.md) |
