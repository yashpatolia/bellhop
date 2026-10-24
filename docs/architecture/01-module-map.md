# Module map

Paths are under `backend/src/bellhop/`. Tests mirror them under `backend/tests/{unit,integration}/`.
Status: everything below is implemented and green unless marked `later`.

## domain/ (done)
`models.py`: `Urgency`, `CallStatus`, `Call`, `Turn`, `Resident`, `MemoryFact`, `Nurse`, `Robot`, `RobotStatus`, `LedState`, `Alert`, `Visit`, `InvalidTransition`.
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
| `domain/learning.py`, `ports/learning.py` | `FactKind`, `Subject`, `CandidateFact`, `ExtractedFacts`; the `FactExtractor` port (`extract(transcript, known_facts) -> list[CandidateFact]`) |
| `services/scrub.py` | `scrub(text, resident_name)`: masks the resident's name, phones, emails and long digit runs before text reaches a model |
| `services/memory_learner.py` | `MemoryLearner(extractor, guard).learn(resident_id, transcript, resident_name, known_facts) -> LearnReport(stored, pending, dropped)`: scrubs, extracts, gates (quote grounding, subject, confidence), then proposes through `MemoryGuard`. Exposed as `Container.memory_learner`. See [15-memory-learning.md](15-memory-learning.md) |
| `services/learn_on_resolve.py` | `LearnOnResolve(calls, residents, memory, learner, bus)`: on `CallResolved`, runs the learner on the call transcript in a background thread; never raises |
| `adapters/claude_extractor.py`, `adapters/rule_extractor.py` | `ClaudeFactExtractor` (structured output, model from `BELLHOP_EXTRACTOR_MODEL`) and `RuleFactExtractor` (offline phrase patterns, the baseline to beat) |
| `labelled/memory_cases.py`, `labelled/memory_eval.py` | 30 labelled conversations and the scorer: `python -m bellhop.labelled.memory_eval --extractor rule|claude` |
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
| `container.py` | `build_container(settings=None, *, stdb_client=None) -> Container` wiring everything; `Settings.from_env()` reads the variables in the table in [backend/README.md](../../backend/README.md#configuration) (`BELLHOP_MEMORY`, `BELLHOP_LEARNING`, `BELLHOP_STORE`, `BELLHOP_SEED_DEMO`, `BELLHOP_STDB_URL/DB/TOKEN`, `MOSS_PROJECT_ID/KEY`, `BELLHOP_GUARDS`, `BELLHOP_ROBOT_URL`, `BELLHOP_CONTENT`, `APIFY_TOKEN`, `BELLHOP_API_KEY`, `BELLHOP_CORS_ORIGINS`, `BELLHOP_ALLOW_NEW_ROBOTS`). `Settings` also has `notifier_timeout`, `gateway_timeout`, `memory_budget_ms` (not env-driven). Robot and SpacetimeDB URLs must be http(s). Unreachable SpacetimeDB at build time logs and falls back to memory |
| `api/app.py` | `create_app(container) -> FastAPI`. 46 operations, listed once in [HTTP routes](#http-routes) below. Optional `X-API-Key` auth on every route but `/health` (`BELLHOP_API_KEY`), 1 MB body limit, field length limits, `?limit=` on `/calls` and `/alerts` |
| `api/events.py` | `EventStream(bus, store, max_clients=20, queue_size=100, heartbeat=15)`: subscribes to `CallRaised/Assigned/Scored/Resolved`, `AlertRaised`; `emit(name, ids)` is thread-safe and non-blocking (bounded deque per client, oldest dropped, `call_soon_threadsafe` wake); `connect()` raises `TooManyClients` (route: 503); `frames(client)` yields SSE text (`retry:`, `id/event/data` with the full object read from the store, `: ping`). `Container.events`, `app.state.events` |
| `api/deps.py` | Helpers the routes use: `get_call`, `ack_alert`, `require_resident`, `triage_score` (runs `TriageGuard.decide`, then `CallService.score`), `AlertNotFound`, `ResidentNotFound` |
| `api/main.py` | ASGI entry: `app = create_app(build_container(Settings.from_env()))`; run `uv run uvicorn bellhop.api.main:app` |
| `scripts/demo_scenes.py` | Plays the three demo scenes against a running server over HTTP (`--base-url`, `--scene`, `--pace`, `--room`) |
| `scripts/export_contract.py` | Regenerates `contracts/openapi.json` and the example payloads; `tests/unit/test_contract.py` fails on drift |

### Robot interface
| File | Public interface |
| --- | --- |
| `adapters/robot_gateway.py` | `RecordingRobotGateway`: default `RobotGateway`; `go_to` and `set_led` append to `.commands` (a `BoundedLog` of the last 1000 `(kind, robot_id, arg)`). `BoundedLog` lives in `adapters/notifiers.py` |
| `adapters/http_robot_gateway.py` | `HttpRobotGateway(base_url, timeout=2.0)`: `go_to` POSTs `/go_to {room}`, `set_led` POSTs `/led {state}`; non-2xx or transport error raises |
| `services/robot_signals.py` | `RobotSignals(calls, gateway, bus)`: urgency 4 -> `emergency`, 3 -> `nurse_on_way`, assigned -> `listening`, resolved -> `idle`, only for the call's `robot_id`; gateway errors are logged, never raised |

### Reminiscence content (Wikipedia direct; Apify optional)
Select with `BELLHOP_CONTENT=local|wikipedia|apify` (default `local`; `apify` also needs `APIFY_TOKEN`). Unknown value raises at startup.

| File | Public interface |
| --- | --- |
| `ports/content.py` | `ContentItem(id, kind song|film|news|event, year, title, blurb)`, `ContentFeed.for_era(birth_year, limit=5)` (items from ages 15-25) |
| `adapters/local_content.py` | `LocalContentFeed()`: about 30 canned 1940s-1970s items, deterministic, works offline |
| `adapters/era_parser.py` | Pure. `parse_era(markdown, year, id_prefix="era")` turns a Wikipedia "{year} in music" page into `ContentItem`s: list items under Events, hit singles, albums, film, musical theatre and classical sections; skips navigation, references, births, deaths and anything negative or morbid; strips links; dedupes; blurb at most 200 chars; sections interleaved so the first few items are varied. `html_to_markdown(html)` prepares API HTML |
| `adapters/wikipedia_content.py` | `WikipediaContentFeed(fallback, timeout=3.0, transport=None, user_agent=...)`: fetches `{year}_in_music` from the MediaWiki action API (`action=parse&prop=text`, about 0.5 s per page, 3 sampled years aged 20, 17, 23, so about 1.7 s cold), caches per year (failures too), stops after the first failed year, falls back on any error or empty parse. The User-Agent must name a contact: Wikimedia returns 403 otherwise |
| `adapters/apify_content.py` | OPTIONAL, ingest-time (pre-warm) only, never in the voice loop. `ApifyContentFeed(fallback, token, actor=..., timeout=60.0)`: runs the crawler via `run-sync-get-dataset-items` (about 12 s per page), parses the single item's `markdown` with `era_parser`, caches per birth year, falls back on missing token, error, timeout or empty parse. Set `APIFY_TOKEN` in the environment only; never commit it |
| `services/reminiscence.py` | `ReminiscenceService(feed, memory, residents)`: `items(resident_id, k)`, `prompt_context(resident_id, k=3)` (bulleted era items) and `ingest(resident_id)` (stores `MemoryFact`s tagged `reminiscence`). Needs `Resident.birth_year` (Margaret is seeded as 1938). Exposed as `Container.reminiscence` |

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
| `spacetimedb/src/index.ts` (repo root) | TypeScript module (tables `call call_turn resident nurse robot alert visit memory_fact`, reducers `save_*` upserts, `append_turn`); build and run steps in `spacetimedb/README.md` |

### Research
- `06-integrations.md`: SpacetimeDB (TypeScript module, Python via HTTP), Moss (async SDK bridged with a 50 ms timeout), Fetch.ai (one Liaison uAgent). All three adapters are written; verification state is in [11-status.md](11-status.md).
- `07-tech-scout.md`: bottlenecks, library verdicts, pipelines. Adopted so far: `httpx` (runtime), `hypothesis`, `pytest-cov`.

## Ownership across the team
| Interface | Other side | Contract |
| --- | --- | --- |
| Call record | Yash (dashboard) | `Call` JSON from the API |
| Robot commands | Jeremy | `RobotGateway.go_to`, `set_led`; status written to `RobotRepository` |
| Triage call | Gordon | Posts to `POST /calls/{id}/score` |
| Memory call | Yash / Companion | `MemoryService.recall`, under 50 ms |

## HTTP routes
Schemas and examples: [contracts/openapi.json](../../contracts/openapi.json) and [contracts/README.md](../../contracts/README.md). Auth: every route except `GET /health` needs `X-API-Key` when `BELLHOP_API_KEY` is set (401), open otherwise. Errors: unknown id 404, illegal state change 409, bad body 422, body over 1 MB 413. CORS from `BELLHOP_CORS_ORIGINS` (default all).

| Area | Method and path | Purpose |
| --- | --- | --- |
| Health | `GET /health` | Liveness; the only unauthenticated route |
| Calls | `POST /calls` | Bell press `{room}`; assigns robot and nurse |
| | `GET /calls`, `GET /calls/{id}` | List (newest first, `?limit=`) and one call |
| | `POST /calls/{id}/turns` | Add transcript turn |
| | `POST /calls/{id}/score` | Triage result through `TriageGuard` |
| | `POST /calls/{id}/triage-failed` | Model failed: urgency 3 default |
| | `GET /calls/{id}/note` | One-line visit note |
| | `POST /calls/{id}/in-visit` | Robot arrived |
| | `POST /calls/{id}/resolve` | Finish call (optional `{by_robot}`) |
| | `POST /calls/{id}/override` | Nurse corrects urgency (409 before resolution) |
| | `GET /labelled-examples` | Calls with a nurse override |
| Alerts | `GET /alerts` | Newest first, read from the store, `?limit=` |
| | `POST /alerts/{id}/ack` | Nurse acks `{nurse_id}`; call becomes `nurse_acked` |
| Memory | `GET`, `POST /residents/{id}/memory` | Recall (`?q=&k=`) / add through `MemoryGuard` (201, 202 pending, 422) |
| | `DELETE /residents/{id}/memory`, `DELETE .../memory/{fact_id}` | Forget all / one |
| | `GET .../memory/pending`, `POST .../pending/{pid}/approve`, `.../reject` | Nurse review queue |
| Reminiscence | `PUT /residents/{id}` | Set `birth_year` |
| | `GET /residents/{id}/reminiscence` | Era items (`?k=`) |
| | `POST /residents/{id}/reminiscence/ingest` | Store items as memory facts |
| Care | `POST /residents/{id}/care`, `GET .../care/summary` | Record entry / trends |
| | `GET /flags`, `POST /flags/{id}/resolve` | Care flags |
| Preferences | `GET`, `PUT /residents/{id}/preferences`; `GET .../speech-settings` | Preferences and derived speech settings |
| Family | `POST`, `GET /residents/{id}/family/messages`; `POST .../family/replies`; `GET .../postcard` | Voice notes, replies, positive-only postcard |
| Robots | `GET /robots`, `PUT /robots/{id}` | Fleet; Pi status report (idle ignored while a call is open); emits `robot.updated` |
| Admin | `POST /residents` (201), `GET /residents`, `GET`, `PATCH /residents/{id}` | Create and edit residents (`PUT /residents/{id}` still sets `birth_year`) |
| | `POST /nurses` (201), `GET /nurses`, `PATCH /nurses/{id}` | Create and edit nurses |
| Live | `GET /events` | Server-Sent Events: `call.raised/assigned/scored/resolved`, `alert.raised`, `robot.updated`; key via `X-API-Key` or `?api_key=` (this route only) |
| Metrics | `GET /metrics` | Savings counter and breakdowns |

## Care, visit notes, family, memory guard, triage guard
All wired in `container.py` (`care_store`, `care_signals`, `visit_notes`, `family`, `preferences`, `memory_guard`, `triage_guard`) and exposed by `api/app.py`; endpoints are in `contracts/README.md`.
- **Care** (`domain/care.py`, `ports/care.py`, `adapters/care_store.py`, `services/care_signals.py`): mood/pain/drink/repeat-question entries, trends (pain streak, mood lower than usual, hydration) and flags. Three days of pain in a row raises one open PAIN flag with a reason. Observations only, no diagnosis.
- **Visit notes** (`services/visit_notes.py`): one-line note per call built from care entries and urgency.
- **Family** (`services/family.py`): voice notes to the resident, replies, and a daily postcard built only from fixed templates and allowlisted drink names (care notes are never echoed).
- **Preferences** (`services/preferences_service.py`): hearing, quiet, night mode, favourite drink; `speech_settings` derives rate, volume, captions, tone.
- **Memory guard** (`services/memory_guard.py`, `adapters/deletable_memory.py`): `POST .../memory` goes through it. Rejects too short/long, clinical claims and duplicates; low-confidence non-staff facts wait in a pending queue for nurse approval (approving re-runs the rules: 409 if now a duplicate, 422 if unsafe). Check-and-store is atomic under one lock; unknown resident 404. Forget one or all facts. It shares one `DeletableLocalMemoryIndex` with `MemoryService`; the Moss index wraps that local index, so with Moss on, a forgotten fact is removed locally only (Moss copy not deleted yet).
- **Triage guard** (`services/triage_guard.py`): `POST /calls/{id}/score` computes the final urgency as max(model, keyword floor), with +1 for confidence under 0.6, then the existing ratchet applies. `POST /calls/{id}/triage-failed` is the explicit model-failure path (defaults to urgency 3). The reason is appended to the call summary when the guard raised urgency.
  - Known limits: the keyword floor is a backstop behind the model, never a replacement for it. Measured recall on unseen paraphrases was roughly 20/24 and 19/24 in two independent fresh batches before fixes, and a further blind set of 17 escalating phrasings missed 10 before fixes. It leans toward over-escalation, handles negation and hedging by a short look-back window, and cannot understand context beyond a clause. Expect misses on novel wording; the model, low-confidence bump and nurse review remain the primary defence.
  - **Measured, do not over-trust:** a fourth independent batch of 24 paraphrase-heavy phrasings (idioms, euphemisms, indirect descriptions) was written after the guard had been tuned on three earlier batches. It caught only 3 of 15 escalating phrasings (12 under-escalations, 1 false trigger in 9 benign phrases). Phrase lists do not generalise. The real safety net must be the model plus an LLM second opinion on low-confidence or no-keyword calls, and the default when the model is unavailable stays nurse-soon (3). Judge the whole pipeline on Gordon's model with the labelled set, not on this guard alone.

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

## Scenarios and admin
- `scenarios.py` (`Scenario`, `load_scenario`, `apply_scenario`, `ScenarioError`) loads a JSON setup (format in `backend/scenarios/README.md`). `seed.py` is a thin wrapper over `scenarios/demo.json`. `BELLHOP_SEED_FILE` (`Settings.seed_file`) applies any scenario at startup and beats `BELLHOP_SEED_DEMO`; a bad file fails startup.
- `services/admin.py` (`AdminService`, exposed as `Container.admin`): `create_resident`, `update_resident`, `list_residents`, `get_resident`, `create_nurse`, `update_nurse`, `list_nurses`. Errors: `ResidentNotFound` / `NurseNotFound` (`LookupError`, API maps to 404) and `Conflict` (`ValueError`: duplicate id or a room another resident occupies).

### Admin routes
Wired in `api/app.py` (`Conflict` maps to 409, pydantic errors to 422). Resident JSON: `{id, name, room, risk_flags: [str], birth_year: int|null}`. Nurse JSON: `{id, name, on_shift, open_tasks}`.

| Route | Request body | Success | Errors |
| --- | --- | --- | --- |
| `POST /residents` | `{id?: str, name, room, risk_flags?: [str], birth_year?: int}` | 201, resident | 409 duplicate id or room taken, 422 invalid |
| `GET /residents` | none | 200, `[resident]` | none |
| `GET /residents/{id}` | none | 200, resident | 404 unknown |
| `PATCH /residents/{id}` | any of `name`, `room`, `risk_flags`, `birth_year` (unknown keys 422) | 200, resident | 404 unknown, 409 room taken, 422 invalid |
| `POST /nurses` | `{id?: str, name, on_shift?: bool = true}` | 201, nurse | 409 duplicate id, 422 invalid |
| `GET /nurses` | none | 200, `[nurse]` | none |
| `PATCH /nurses/{id}` | any of `name`, `on_shift` | 200, nurse | 404 unknown, 422 invalid |

Routes call `container.admin.<method>`; `create_*` take `id` (None generates one). Going off shift never changes `open_tasks`. `PUT /residents/{id}` (`birth_year` only, unknown id 404) is kept for backward compatibility. Guide: [08-scenarios-and-admin.md](08-scenarios-and-admin.md).
