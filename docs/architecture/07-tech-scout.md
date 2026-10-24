# 07 Tech Scout

Scope: libraries, pipelines, bottlenecks. No dependency here is adopted until the manager runs the `uv add` line. Versions and licences checked on PyPI on 2026-10-23; all support Python 3.12. Sponsor SDKs (SpacetimeDB, Moss, Fetch.ai) are covered in `06-integrations.md`, not here.

## 1. Bottleneck analysis

Reading of the code: ports are sync, event bus is in-process and sync (ADR-2, ADR-5), `LocalMemoryIndex` is an inverted index (microseconds), `CompositeNotifier` isolates channel failures. The cost is in the network hops, not our code.

| Area | Where it bites | Budget / evidence | Mitigation |
| --- | --- | --- | --- |
| Voice loop turn time | STT end-of-turn, then LLM first token, then TTS first audio, all serial. Our code (memory, state) is under 5 ms of it; Claude time-to-first-token and TTS dominate | Target under 1.2 s from end of speech to first audio. Rough split: STT final 150-300 ms, Claude TTFT 400-700 ms, TTS first byte 100-200 ms | Stream everything: stream Claude tokens into Cartesia sentence by sentence, start TTS at the first clause. Use the smallest Claude model for chat turns and keep the system prompt stable (prompt caching) with memory facts appended last. Cap replies to 2 sentences. Log per-stage ms (see section 2) so the budget is measured, not guessed. Pre-render filler ("One moment...") only if TTFT exceeds 1 s |
| Memory recall | Not a bottleneck: lexical recall is sub-ms. Risk is quality (no synonyms: "grandkid" misses "grandson") not speed | Existing test bound 50 ms | Keep local index in the voice path. Add tag synonyms in `seed_demo` for the 3 demo scenes (free). Embeddings only if a demo utterance misses (section 2) |
| Triage call | A second LLM round-trip before the nurse alert; Jev or Claude failure silently leaves a call unscored | Needs under 2 s, and urgent cases must never wait | Run triage in parallel with the companion reply, not before it. Hard timeout 1.5 s via httpx; on timeout or error score as urgency 3 (rule 5: uncertain means more urgent) and flag `triage_fallback=true`. Keyword pre-filter ("fall", "can't breathe", "chest") forces 4 before any model call |
| Sync event bus on the request path | `POST /calls` runs Dispatcher (robot `go_to` HTTP) and Liaison (phone push) inline, so one slow robot or push blocks the bell press response | One 5 s socket hang equals a visibly dead demo | Every outbound call gets a timeout of 2 s or less. Slow handlers (push, SpacetimeDB write) go to FastAPI `BackgroundTasks` or a bounded `ThreadPoolExecutor`; keep dispatch and the urgency-4 broadcast synchronous but timeout-bounded. Handlers are already required idempotent, so retry is safe |
| Handler failure is only logged | A failed Liaison handler for urgency 4 is a log line nobody sees | Safety path | On handler exception for `CallScored` with urgency >= 3, publish a `DeliveryFailed` alert to the dashboard and retry once (tenacity, section 2). Dashboard shows "unacknowledged for N s" in red |
| Network drops (venue wifi) | Robot to cloud, dashboard to SpacetimeDB, STT/TTS streams all die together | Hackathon wifi is the top demo killer | Hotspot from a phone as a second uplink; robot talks to backend over LAN where possible. Local fallbacks already designed: Piper TTS, in-memory store, local memory. Add a `/health` that reports each dependency (store, memory, tts, llm) so a 10 s pre-demo check shows red and green |
| SpacetimeDB sync | Reconnect gaps lose events; dashboard shows stale queue | Subscription drops are silent in many clients | Dashboard re-fetches full queue on reconnect, shows a "live" dot tied to last-event age (over 10 s turns amber). Backend keeps the in-memory store as the source for the demo and mirrors to SpacetimeDB through an adapter that swallows and counts failures |
| Rate limits and cost | Anthropic, Cartesia and Apify limits during repeated rehearsals | Unknown per key | One shared `httpx.Client` per service with a per-minute counter in the log; cache scripted demo triage results by transcript hash during rehearsal only |
| Demo-day failure modes | Wrong triage on stage, API key missing, robot brown-out, wifi | Plan risk table covers hardware | A `BELLHOP_DEMO=scripted` switch: canned STT text and canned triage for the 3 scenes, everything else real. Pre-seed with `seed_demo`, run the three integration scenes as a pre-flight command (`uv run pytest tests/integration -q`) 10 min before judging. Record a 60 s screen capture as the last fallback |

## 2. Library recommendations

Verdict rule: ADOPT NOW only if it removes a named risk this week at under 1 hour of integration.

| Need | Recommended | `uv add` | Why | Alternative | Verdict |
| --- | --- | --- | --- | --- | --- |
| HTTP client | httpx 0.28.1 (BSD-3). Already a dev dependency | `uv add httpx` (move to runtime) | Sync and async, per-request timeouts, `httpx.MockTransport` for tests, used by FastAPI TestClient already | requests, aiohttp | ADOPT NOW (promote dev to runtime) |
| Settings | pydantic-settings 2.16.1 (MIT, py>=3.11) | `uv add pydantic-settings` | Container needs `Settings` from env (`BELLHOP_MEMORY`, `BELLHOP_STORE`, API keys as `SecretStr`); same pydantic v2 already in use; reads `.env` | plain `os.environ` dataclass (about 15 lines) | ADOPT NOW. Typed secrets avoid leaking keys into logs |
| Retries | tenacity 9.2.1 (Apache-2.0) | `uv add tenacity` | Decorator retry with stop-after-delay and wait-exponential-jitter; works sync and async. Use only on idempotent sponsor calls | stamina 26.1.0 (opinionated wrapper over tenacity, nicer defaults) | ADOPT NOW, max 2 retries and a 3 s total deadline |
| Circuit breaker | pybreaker 1.4.1 | `uv add pybreaker` | Opens after N failures so a dead sponsor stops costing 2 s per turn; pairs with the existing fallback adapters (Moss to local) | hand-rolled counter (10 lines, in the adapter) | LATER. Hand-roll "skip Moss for 30 s after 3 failures" inside `MossMemoryIndex` first |
| Structured logging | structlog 26.1.0 (MIT or Apache-2.0) | `uv add structlog` | JSON lines with bound `call_id`, `resident_id`, `stage`, `ms`; contextvars bind once per request. Doubles as the event log in section 3 | stdlib `logging` with a JSON formatter; loguru 0.7.3 (stale since 2024-12) | ADOPT NOW. Smallest tool that makes per-stage latency visible |
| Tracing | OpenTelemetry SDK | n/a | Heavy for 48 h; a context-manager timer logging `ms` through structlog covers the voice budget | logfire, langfuse | SKIP |
| Semantic memory | fastembed 0.9.0 (Apache-2.0, ONNX, no torch). Model `BAAI/bge-small-en-v1.5` (about 130 MB, a few ms per short text on CPU) | `uv add fastembed` | Fixes synonym misses ("grandkid"). Embed facts at `remember()`, cosine over a numpy matrix for under 1000 facts, no vector DB needed. Blend with existing lexical score (0.5/0.5) | sqlite-vec 0.1.9 (MIT/Apache; only worth it past 10k facts); lancedb 0.40.0 (overkill); rank-bm25 0.2.2 (unmaintained since 2022, our inverted index already does lexical) | LATER. Trigger: a demo utterance misses in rehearsal. Implement as a new `HybridMemoryIndex` adapter behind the port, passing the same contract tests. Model download needs network, so bake it into the image or warm the cache the night before |
| Dashboard push | sse-starlette 3.5.0 (BSD-3) on FastAPI | `uv add sse-starlette` | One-way server push of `CallRaised`/`AlertRaised` to a React `EventSource` with auto-reconnect; simpler than websockets. Needed only if the dashboard reads from our API instead of SpacetimeDB subscriptions | websockets 17.3, FastAPI native `WebSocket` (no extra dependency) | LATER. If SpacetimeDB drives the dashboard, skip. Otherwise add a `GET /events` stream fed by an event-bus handler |
| Data validation | pydantic v2 (already a dependency) | none | Domain, API and settings already use it. Add `model_config = ConfigDict(extra="forbid")` on API request models to catch typos | msgspec, attrs | ADOPT NOW (no new dependency). Do not add another validation library |
| Property tests | hypothesis 6.170.9 (MPL-2.0) | `uv add --dev hypothesis` | Two cheap high-value properties: (1) any sequence of `score()` calls never lowers `Call.urgency`; (2) random transition sequences either raise or land in a legal state and never close an unresolved call. A `RuleBasedStateMachine` over `Call` is about 40 lines | hand-written parametrized cases | ADOPT NOW (dev only). The ratchet is the project's central invariant |
| Coverage | pytest-cov 7.1.0 (MIT) | `uv add --dev pytest-cov` | `uv run pytest --cov=bellhop --cov-report=term-missing` shows untested adapters fast | `coverage` directly | ADOPT NOW (dev only) |
| Time control | none needed: `clock` fixture already exists | none | Ports inject time, so time-machine 3.5.1 / freezegun 1.5.5 add nothing. Use only if a third-party SDK reads wall time | time-machine (faster, C-based), freezegun | SKIP |
| HTTP mocking | respx 0.23.1 (BSD-3) | `uv add --dev respx` | Contract-test the Moss, Cartesia and robot-gateway adapters against canned responses and timeouts without network | `httpx.MockTransport` (built in, no dependency) | SKIP for now; `MockTransport` is enough |
| Shift digests | stdlib `threading.Timer` or FastAPI lifespan task; APScheduler 3.11.3 (MIT; 4.x is a rewrite, pin `<4`) | `uv add "apscheduler<4"` | Digest is `Analytics` output at shift change. Demo triggers it by `POST /digest`; a scheduler adds state and failure modes | Creao (sponsor, stretch), cron | SKIP for MVP. LATER: APScheduler `BackgroundScheduler` with one cron job per shift |
| Fast JSON | orjson 3.13.0 | `uv add orjson` | Not a bottleneck at this traffic | stdlib json | SKIP |

Net new runtime dependencies for NOW: `httpx` (promoted), `pydantic-settings`, `tenacity`, `structlog`. Net new dev: `hypothesis`, `pytest-cov`. That is six lines, total install under 10 s.

```
cd backend
uv add httpx pydantic-settings tenacity structlog
uv add --dev hypothesis pytest-cov
uv run pytest --cov=bellhop --cov-report=term-missing
```

## 3. Data pipelines

| Pipeline | Source | Steps | Sink | Library | Hours | When |
| --- | --- | --- | --- | --- | --- | --- |
| Labelled-call dataset for triage thresholds | `Analytics.labelled_examples()` (nurse override vs robot urgency) | 1. Export to JSONL `{transcript, robot_urgency, nurse_urgency, category, ts}`. 2. Compute confusion matrix and per-threshold under-escalation rate. 3. Choose the confidence cut-off that sends zero true-4 cases below 3, accepting extra false alarms (rule 5) | `data/labelled_calls.jsonl`, threshold constant in `Settings` | stdlib `json`, `collections.Counter`; no pandas | 2 | MVP (script `scripts/threshold_report.py`; no change to `backend/src`) |
| Call and visit event log | Event bus (`CallRaised`, `CallScored`, `AlertRaised`, `CallResolved`) | One bus subscriber appends one JSON line per event with ts and ids; structlog output can serve as this log | `data/events.jsonl`, rotated per run | structlog (already adopted) | 1 | MVP. Gives the post-demo story and replay for debugging |
| Analytics queries | `events.jsonl` | `duckdb.sql("select category, count(*) from read_json_auto('data/events.jsonl') group by 1")` | Ad hoc tables and charts for the pitch | duckdb 2.0.0 (MIT, py>=3.11), `uv add --dev duckdb` | 1.5 | LATER. `Analytics` service already serves the live dashboard counters; DuckDB only helps for the slide deck |
| Synthetic labelled calls | Hand-written seed phrases per class, expanded by Claude | 1. Write 6 seed scenes per urgency 1-4 and per category. 2. Prompt Claude for 3 paraphrases each (include hearing-impaired, vague, and distressed phrasings), temperature 1. 3. Hand-review all, label by team, drop any real-sounding personal data. 4. Save with `source: synthetic` | `data/synthetic_calls.jsonl` (about 30 to 60 rows) | anthropic SDK (already needed for the product); Faker 40.43.0 only for room numbers and names, optional | 2.5 | MVP. Also feeds integration tests and the threshold report; never mix with real override data |
| Reminiscence content ingest | Apify output (era songs, headlines, "life in 1955") | 1. Run actor once per decade for the demo residents (birth year plus 20). 2. Keep title, date, 1-2 sentence summary, source URL. 3. `memory.remember(resident_id, text, tags=("era","1955","music"))` with era tags. 4. Cache raw result to `data/apify/*.json` so the demo never calls Apify live | `MemoryIndex` via `MemoryService.remember` | apify-client 3.3.0 (Apache-2.0, py>=3.11), `uv add apify-client` | 3 | LATER (plan marks the Apify feed conditional). Do only after the core flow is demo-ready |

### Apify ($205 credit) assessment

Prices below are approximate, from search listings that conflict in places; confirm on each actor's Pricing tab before running. Free-tier compute is roughly $0.20-0.30 per compute unit.

| Use | Actor type | Approx cost | Real value | Recommendation |
| --- | --- | --- | --- | --- |
| Local news for chat topics ("the weather, local news") | A Google News scraper, pay per result, listed from about $1 to $8 per 1,000 results | Under $0.05 for 20 headlines per run | Medium: a fresh topic in a conversation. But Context.dev (sponsor) or a plain RSS feed does the same free | SKIP Apify here unless a sponsor prize needs it. Use RSS via httpx (0 cost, 1 h) |
| Reminiscence by era (music, events, nostalgia) | Website Content Crawler on a few curated pages (Wikipedia "1955 in music", "1960s in the United States"), cost driven by compute at roughly $0.2-5 per 1,000 pages | Under $1 for 50 pages | High for the demo: authentic era facts that make memory recall feel personal | ADOPT LATER as a one-off batch, cache results, 10 runs at most. Wikipedia's own API gives the same facts free and faster, so use Apify only for the sponsor story |
| Supplier prices for the x402 stretch | Product or retailer scraper | $1-3 | Low, last-priority idea | SKIP |

Budget plan: cap spend at $10 total (set a monthly usage limit in the Apify console). The $205 credit will not be the constraint; engineering time is.

## 4. Top 5 prioritized actions

| # | Action | Hours | Detail |
| --- | --- | --- | --- |
| 1 | Timeouts, fallbacks and a hard triage deadline | 2 | httpx timeouts of 2 s or less on every outbound call; tenacity with at most 2 retries on idempotent calls; triage failure scores 3 and flags it; keyword forces 4. Biggest demo-safety gain |
| 2 | Hypothesis state-machine tests for the urgency ratchet and call lifecycle | 1.5 | `uv add --dev hypothesis pytest-cov`; two properties from section 2. Protects rule 5 under every future change |
| 3 | structlog plus per-stage `ms` timers on the voice loop and an event JSONL subscriber | 2 | Makes the 1.2 s budget measurable, gives debugging replay and the post-demo numbers |
| 4 | `Settings` via pydantic-settings and a `/health` that reports each dependency, plus a `BELLHOP_DEMO=scripted` switch | 2 | One pre-demo command shows green or red; scripted mode covers wifi and API outages |
| 5 | Synthetic labelled calls (30) and the threshold report script | 4.5 | Needs a labelled set to pick the triage confidence cut-off honestly; reuse in integration tests |

Deferred, with triggers: fastembed hybrid memory (a rehearsal utterance misses), sse-starlette (dashboard cannot use SpacetimeDB subscriptions), pybreaker (a sponsor flaps during rehearsal), Apify era ingest (core flow demo-ready), DuckDB (slides need charts).
