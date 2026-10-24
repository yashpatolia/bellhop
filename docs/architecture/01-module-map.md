# Module map

Paths are under `backend/src/bellhop/`. Tests mirror them under `backend/tests/{unit,integration}/`.
Status: everything below is implemented and green unless marked `later`.

## domain/ (done)
`models.py`: `Urgency`, `CallStatus`, `Call`, `Turn`, `Resident`, `MemoryFact`, `Nurse`, `Robot`, `RobotStatus`, `Alert`, `Visit`, `InvalidTransition`.
`events.py`: `CallRaised`, `CallAssigned`, `CallScored`, `CallResolved`, `AlertRaised` (frozen dataclasses).
Rules: `Call.charge(nurse)` counts a call against a nurse at most once (`Call.nurse_tasks`); `Call.robot_id` is the robot assigned. `Call.transition(to, at)` enforces the state machine; `Call.score(urgency, category)` only ratchets up; `Call.needs_nurse` is urgency >= 3.

## ports/ (done)
`CallRepository`, `ResidentRepository`, `NurseRepository`, `RobotRepository`, `VisitRepository`, `AlertRepository`, `MemoryIndex`, `Notifier`, `RobotGateway`, `EventBus`, `Clock`, `IdGenerator`. See `ports/__init__.py`.

## adapters/ and services/ (grouped by work package)

### WP-A: state, events, calls, dispatch
| File | Public interface |
| --- | --- |
| `adapters/memory_store.py` | `InMemoryStore` is a facade with one repository per aggregate: `.calls`, `.residents`, `.nurses`, `.robots`, `.visits`, `.alerts` (the container passes `store.calls` etc.). `save` is upsert; `get` returns a copy-safe object; `list_open` = calls not in RESOLVED/CLOSED |
| `adapters/event_bus.py` | `InMemoryEventBus`: synchronous, handlers run in subscription order, one failing handler is logged and does not block others |
| `adapters/system.py` | `SystemClock`, `UuidIds` (`new_id("call")` -> `"call_<8 hex>"`) |
| `services/call_service.py` | `CallService(calls, residents, bus, clock, ids, nurses=None)`: `raise_call(room) -> Call` (attaches resident by room if known, publishes `CallRaised`), `add_turn(call_id, speaker, text)`, `score(call_id, urgency, category, summary=None)` (publishes `CallScored`; urgency >= 3 moves the call to ESCALATED; scores on RESOLVED/CLOSED calls are ignored), `mark_in_visit(call_id)`, `resolve(call_id, by_robot=True)` (publishes `CallResolved`; `by_robot` is only true if the call had a robot and no nurse was needed), `ack_by_nurse(call_id, nurse_id)` (unknown nurse raises `LookupError`). Unknown call id raises `CallNotFound` |
| `services/dispatcher.py` | `DispatchPolicy` Protocol: `decide(call, resident, robots, nurses) -> Decision(robot_id, nurse_id)`. `DefaultPolicy`: idle robot with battery >= 0.2 nearest-first (any idle if no positions), nurse added when resident has risk flags or no robot is free; least-loaded on-shift nurse. `Dispatcher(calls, residents, robots, nurses, gateway, policy, bus, clock)` subscribes to `CallRaised`, assigns, transitions to ASSIGNED, calls `gateway.go_to` first, then sets the robot BUSY, charges the assigned nurse, publishes `CallAssigned`. If `go_to` raises, the robot is left untouched and the call falls back to a nurse. No robot and no nurse available: call is ESCALATED |
| `services/workload.py` | `Workload(calls, robots, nurses, bus)` on `CallResolved`: sets the call's robot back to IDLE and releases every nurse charged for the call (`open_tasks` never goes below 0) |

### WP-B: memory and recall
| File | Public interface |
| --- | --- |
| `adapters/local_memory.py` | `LocalMemoryIndex` implements `MemoryIndex`: dependency-free lexical ranking (lowercased tokens, stopwords dropped, overlap weighted by tag matches, recency tiebreak). Default adapter and Moss fallback |
| `adapters/moss_memory.py` | `MossMemoryIndex` implements `MemoryIndex`; imports the Moss SDK lazily; on any failure or missing key falls back to a wrapped `MemoryIndex` |
| `services/memory_service.py` | `MemoryService(index, clock, ids)`: `remember(resident_id, text, tags=())`, `recall(resident_id, utterance, k=3)`, `prompt_context(resident_id, utterance, k=3) -> str` (bulleted facts ready for a system prompt, empty string if none) |
| `seed.py` (shared, WP-B owns memory part) | `seed_demo(store, memory)`: demo residents, nurses, one robot, and facts for the three demo scenes (tea with two sugars, grandson, hip pain history) |

### WP-C: alerts, feedback, analytics
| File | Public interface |
| --- | --- |
| `adapters/notifiers.py` | `RecordingNotifier` (keeps sent alerts; used by dashboard feed and tests), `CompositeNotifier(*notifiers)` (one failing channel does not stop others) |
| `services/liaison.py` | `Liaison(calls, nurses, alerts, notifier, bus, clock, ids)` subscribes to `CallScored`. Urgency 3: one alert to the nurse already on the call, else the least-loaded on-shift nurse, with a short summary. Urgency 4: one broadcast alert (`nurse_id=None`) immediately. Urgency 1-2: nothing. Re-scoring to the same level does not duplicate alerts; raising 3 to 4 sends the 4 alert. Publishes `AlertRaised` |
| `services/feedback.py` | `FeedbackService(visits, calls, bus, ids)`: `record_resolution(call_id, robot_id)` on `CallResolved` creates the `Visit`; `rate(call_id, rating, mood=None)`; `nurse_override(call_id, urgency)` |
| `services/analytics.py` | `Analytics(calls, visits)`: `resolved_without_nurse()`, `minutes_saved(minutes_per_call=4.0)`, `share_answered_within(seconds=600)`, `calls_by(key)` with key in `hour|room|category`, `labelled_examples()` (calls where a nurse override exists, as dicts of transcript, robot urgency, nurse urgency) |

### WP-D: composition and HTTP
| File | Public interface |
| --- | --- |
| `container.py` | `build_container(settings) -> Container` wiring everything; `Settings.from_env()` (`BELLHOP_MEMORY=local|moss`, `BELLHOP_STORE=memory`, `BELLHOP_SEED_DEMO=1`, `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY`). `BELLHOP_STORE=spacetimedb` with `BELLHOP_STDB_URL`, `BELLHOP_STDB_DB`, `BELLHOP_STDB_TOKEN` (see below); unreachable server at build time logs and falls back to memory |
| `api/app.py` | `create_app(container) -> FastAPI`. Routes: `POST /calls {room}`, `GET /calls`, `GET /calls/{id}`, `POST /calls/{id}/turns`, `POST /calls/{id}/score`, `POST /calls/{id}/resolve`, `POST /alerts/{id}/ack`, `GET /residents/{id}/memory?q=&k=`, `POST /residents/{id}/memory`, `GET /metrics`, `GET /health` |

### Reminiscence content (optional, Apify)
| File | Public interface |
| --- | --- |
| `ports/content.py` | `ContentItem(id, kind song|film|news|event, year, title, blurb)`, `ContentFeed.for_era(birth_year, limit=5)` (items from ages 15-25) |
| `adapters/local_content.py` | `LocalContentFeed()`: about 30 canned 1940s-1970s items, deterministic, works offline |
| `adapters/apify_content.py` | `ApifyContentFeed(fallback, token, actor=..., timeout=5.0)`: runs the actor via `run-sync-get-dataset-items`, caches per birth year, falls back on missing token, HTTP error, timeout or empty result. `map_item` isolates dataset mapping. Set `APIFY_TOKEN` in the environment only; never commit it |
| `services/reminiscence.py` | `ReminiscenceService(feed, memory, residents)`: `prompt_context(resident_id, k=3)` (bulleted era items) and `ingest(resident_id)` (stores `MemoryFact`s tagged `reminiscence`). Needs `Resident.birth_year` |

### Fetch.ai Liaison (`src/bellhop/fetchai/`)
| File | Public interface |
| --- | --- |
| `answers.py` | `answer_question(question, calls, alerts, metrics) -> str`: pure, room history / open alerts / metrics / help fallback |
| `client.py` | `BellhopApi(base_url, timeout=2.0)` with `calls()`, `alerts()`, `metrics()`; raises `BellhopApiError` |
| `agent.py` | `reply_for(question, api)` (never raises on backend failure), `build_agent()`, `main()`; lazy-imports `uagents` (extra `fetch`, needs `BELLHOP_AGENT_SEED`) |
| `__main__.py` | `python -m bellhop.fetchai` starts the agent. Not imported by the API or container |

### SpacetimeDB store (optional)
| File | Public interface |
| --- | --- |
| `adapters/spacetimedb_store.py` | `SpacetimeDBStore(url, db, token=None, *, client=None, max_queue=500)` with `.calls .residents .nurses .robots .visits .alerts` like `InMemoryStore`. Reads from an in-memory mirror; each `save` also POSTs the reducer (`save_*`, `append_turn` for new turns) with a 2 s timeout. Failures are logged and queued, retried in order on the next save, never raised. `pending`, `flush()`, `hydrate()` (SQL into the mirror; raises `httpx.HTTPError` if unreachable) |
| `../spacetimedb/` | TypeScript module (tables `call call_turn resident nurse robot alert visit memory_fact`, reducers `save_*` upserts); build and run steps in its README |

### Research and `later` work
- `06-integrations.md`: SpacetimeDB (TypeScript module, Python via HTTP), Moss (async SDK bridged with a 50 ms timeout), Fetch.ai (one Liaison uAgent). Moss and Fetch.ai adapters are `later`; the SpacetimeDB store is built.
- `07-tech-scout.md`: bottlenecks, library verdicts, pipelines. Adopted so far: `httpx` (runtime), `hypothesis`, `pytest-cov`.

## Ownership across the team
| Interface | Other side | Contract |
| --- | --- | --- |
| Call record | Yash (dashboard) | `Call` JSON from the API |
| Robot commands | Jeremy | `RobotGateway.go_to`, `set_led`; status written to `RobotRepository` |
| Triage call | Gordon | Posts to `POST /calls/{id}/score` |
| Memory call | Yash / Companion | `MemoryService.recall`, under 50 ms |

## HTTP API
Also served by `api/app.py` beyond the WP-D list: `POST /calls/{id}/in-visit`, `GET /alerts` (newest first), `POST /alerts/{id}/ack {nurse_id}` (sets `acked_at`, moves the call to `nurse_acked`). `POST /calls/{id}/resolve` takes optional `{by_robot}`. Errors: unknown call/alert 404, invalid state transition 409, bad body (urgency outside 1..4) 422. CORS allows all origins. Run with `uv run uvicorn bellhop.api.main:app`.

## Labelled calls pipeline (`src/bellhop/labelled/`)
Stdlib-only package for checking and tuning triage against hand-labelled calls. It imports nothing from services or adapters.
| File | Public interface |
| --- | --- |
| `cases.py` | `LabelledCase(id, transcript, risk_flags, expected_urgency, expected_category, note)` and `CASES`: 30 fictional cases (8/6/9/7 across urgency 1-4) covering the three demo scenes, hedged phrasing, negations and dementia confusion |
| `io.py` | `save_jsonl(cases, path)`, `load_jsonl(path)`, `from_overrides(examples)` converting `Analytics.labelled_examples()` output (nurse urgency becomes the label) |
| `report.py` | `threshold_report(cases, predictions)` with predictions as `{case_id: (urgency, confidence)}`; returns per-urgency precision/recall, confusion matrix, under-escalation ids (reported first in `format()`) and `suggested_threshold`. `suggest_escalation_threshold` gives the lowest confidence cutoff below which predictions are bumped one level so under-escalations are zero, or `None` if one bump is not enough |
| `__main__.py` | `python -m bellhop.labelled [path]` writes `data/labelled_cases.jsonl` (run from `backend/`) and prints a summary |

## Reliability guards (`adapters/guards.py`)
| Symbol | Role |
| --- | --- |
| `call_with_timeout(fn, seconds, *args, default=...)` | Runs fn in a shared pool; raises `GuardTimeout` or returns `default` |
| `CircuitBreaker(failures=3, reset_seconds=30, clock=...)` | `allow`, `record_success`, `record_failure`; half-open probe after the reset window |
| `GuardedNotifier(inner, timeout=2.0)` | Never raises; `failed_alerts` and `retry_failed()` |
| `GuardedRobotGateway(inner, timeout=2.0)` | Raises `GuardTimeout` so the Dispatcher falls back to a nurse |
| `GuardedMemoryIndex(inner, fallback, budget_ms=50)` | Falls back and trips the breaker on slow or failing recall |
Container wiring: `Container.guarded_notifier` / `guarded_gateway` (None when `Settings(guard_timeouts=False)`, env `BELLHOP_GUARDS=0`); the memory index is wrapped only for `moss`. `Container.notifier` and `gateway` remain the recorders.
