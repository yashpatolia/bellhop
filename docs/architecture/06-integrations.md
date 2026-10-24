# Integrations: SpacetimeDB, Moss, Fetch.ai

Research for the backend owner who wires sponsor services behind our ports. Verified against official docs on 2026-10-23. Nothing here changes `domain/` or `ports/`. Every sponsor adapter is optional and must fall back to the in-memory/local one (see `00-overview.md`, `01-module-map.md`).

| Sponsor | Port(s) it backs | Settings flag | Fallback |
| --- | --- | --- | --- |
| SpacetimeDB | `Call/Resident/Nurse/Robot/Visit/AlertRepository` (+ live dashboard feed) | `BELLHOP_STORE=spacetimedb` | `InMemoryStore` |
| Moss | `MemoryIndex` | `BELLHOP_MEMORY=moss` | `LocalMemoryIndex` |
| Fetch.ai | none (a client of our HTTP API) | `BELLHOP_UAGENTS=1` (new, optional) | not started |

---

## 1. SpacetimeDB

### Facts (current docs are v2.x; npm `spacetimedb` is 2.13.0)

| Question | Answer |
| --- | --- |
| Module (server logic) languages | Rust, C#, TypeScript, C++. **No Python modules.** |
| Client SDKs (official) | Rust, C#, TypeScript, Unreal. **No usable Python SDK.** `spacetimedb-sdk` 0.7.0 on PyPI exists (Clockwork Labs) but is unmaintained, targets the old API generation (`module_address`, generated `module_bindings`) and the v2 client docs cover only Rust/C#/TypeScript/Unreal. Do not use it; use the HTTP API with `httpx`. |
| Python access | HTTP API (`/v1/database/...`): call reducers, run SQL. Docs say it is for "management, debugging and interactive developer use" and is not as optimized as the WebSocket API. Fine at hackathon scale. |
| Live subscriptions | WebSocket via the TypeScript SDK (`DbConnection`, `subscriptionBuilder().subscribe(...)`, `onInsert/onUpdate/onDelete`). |
| License | BSL 1.1 (source-available), self-hostable. |

### Verified (2026-10-23: docs v2.0.0 pages, plus a live local server running CLI/server 2.13.0)

Live check: module published, reducer calls and `SELECT * FROM <table>` over HTTP round-tripped through `SpacetimeDBStore` (no token). Token auth and Maincloud not exercised.

- Reducer call: `POST {host}/v1/database/{name_or_identity}/call/{reducer}`, body = JSON array of positional args, optional `Authorization: Bearer <token>`, optional `?confirmed=true|false` (default true, waits for durability). Anonymous callers are allowed and reach the reducer with their own identity.
- SQL: `POST {host}/v1/database/{name_or_identity}/sql`, body = raw SQL text (`;` separated). Response is a JSON array, one `{"schema": ProductType, "rows": [[...]]}` per statement; column names are in `schema.elements[i].name.some`. No token means public tables only.
- Identity: `POST {host}/v1/identity` returns `{"identity","token"}`. Database name is the first argument to `spacetime publish`; the HTTP path accepts either that name or the identity hex.
- v2 TypeScript module: `schema({ call, ... })` with `table({ name, public }, columns)`; the schema key is the accessor and the SQL name is verbatim. Docs call the HTTP API "not optimized" vs WebSocket; fine here because reads come from the memory mirror.
- Environment variables used by Bellhop: `BELLHOP_STORE=spacetimedb`, `BELLHOP_STDB_URL` (default `http://127.0.0.1:3000`), `BELLHOP_STDB_DB` (default `bellhop`), `BELLHOP_STDB_TOKEN` (optional; never commit).

### Recommendation

1. **Write the module in TypeScript.** The team is Python-centric, but Rust and C# add toolchains; TypeScript shares a language with the React dashboard and the template (`spacetime dev --template react-ts`) generates client bindings for free. The module is about 100 lines of declarations plus trivial reducers. Keep business rules in Python (`domain/`); reducers only validate shape and write rows.
2. **Python backend talks to it over the HTTP API** (sync `httpx`, already fits our synchronous ports). The Python adapter is a write-through store: reducer calls for writes, SQL for reads.
3. **The React dashboard subscribes directly** over WebSocket with the generated TypeScript bindings. This is the only place live push is needed.
4. Keep the call state machine in `domain/models.py`; the adapter persists the resulting `Call` snapshot via an upsert reducer.

### Install and run (local standalone)

```bash
curl -sSf https://install.spacetimedb.com | sh      # installs the `spacetime` CLI (macOS/Linux; WSL ok)
spacetime version list                              # confirm install
spacetime start                                     # local server, default http://127.0.0.1:3000
# or: docker run --rm --pull always -p 3000:3000 clockworklabs/spacetime start

# scaffold module + React client + bindings in one go (starts server, publishes, generates):
spacetime dev --template react-ts                   # module in spacetimedb/src/index.ts, client in src/

# manual loop (flags per CLI reference; verify with `spacetime publish --help`):
spacetime publish bellhop --module-path spacetimedb # publish/update module as database "bellhop"
spacetime generate --lang typescript --out-dir dashboard/src/module_bindings --module-path spacetimedb

# smoke tests from the CLI
spacetime call bellhop save_resident '["r1","Edna Park","12",["falls"]]'
spacetime sql bellhop "SELECT * FROM resident"
spacetime logs bellhop
```

Use local (not hosted Maincloud) for the demo to avoid venue Wi-Fi risk.

### Domain to tables and reducers

Rules: SQL names are verbatim (no pluralization). Use `string`/`u32`/`bool`/`f64` only on the Python-facing path (enum/option/timestamp/array JSON encodings not verified). Timestamps are ISO-8601 strings from our `Clock`. Row ids come from our `IdGenerator`, never `autoInc`.

| Domain | Table (public) | Primary key | Notes | Reducer(s) |
| --- | --- | --- | --- | --- |
| `Call` | `call` | `id` | `transcript` is NOT a column; see `call_turn`. `urgency` `u32` with sentinel `0` = unscored. `assigned_to` as comma-joined string. Index `status`, `room` | `save_call` (upsert) |
| `Call.transcript` | `call_turn` | `id` (`"{call_id}:{n}"`) | `call_id`, `seq`, `speaker`, `text`, `at`. Index `call_id` | `append_turn` |
| `Resident` | `resident` | `id` | `risk_flags` comma-joined. Index `room` (unique) | `save_resident` |
| `Nurse` | `nurse` | `id` | `on_shift` bool, `open_tasks` u32 | `save_nurse` |
| `Robot` | `robot` | `id` | `status` string, `battery` f64, `room` string (`""` = none) | `save_robot` |
| `Alert` | `alert` | `id` | `nurse_id` `""` = broadcast, `acked_at` `""` = open. Index `call_id` | `save_alert` |
| `Visit` | `visit` | `id` | `call_id` unique; `rating` `0` = none; `nurse_urgency_override` `0` = none | `save_visit` |
| `MemoryFact` | `memory_fact` | `id` | `tags` comma-joined. Source of truth for facts; Moss is a derived index. Index `resident_id` | `save_memory_fact` |

Dashboard subscribes to `call`, `alert`, `robot`, `nurse`, `call_turn`. All tables `public: true` for the demo (no auth).

### Minimal schema sketch (TypeScript module, `spacetimedb/src/index.ts`)

Syntax follows the v2 docs. Starting point, not final code.

```ts
import { schema, table, t } from 'spacetimedb/server';

const call = table({ name: 'call', public: true }, {
  id: t.string().primaryKey(),
  room: t.string().index('btree'),
  resident_id: t.string(),          // "" = unknown
  urgency: t.u32(),                 // 0 = unscored, 1..4 = Urgency
  category: t.string(),
  status: t.string().index('btree'),
  summary: t.string(),
  assigned_to: t.string(),          // comma-joined ids
  created_at: t.string(),           // ISO-8601 from Python Clock
  assigned_at: t.string(),
  first_response_at: t.string(),
  resolved_at: t.string(),
});

const call_turn = table({ name: 'call_turn', public: true }, {
  id: t.string().primaryKey(),      // "{call_id}:{seq}"
  call_id: t.string().index('btree'),
  seq: t.u32(),
  speaker: t.string(),
  text: t.string(),
  at: t.string(),
});

const robot = table({ name: 'robot', public: true }, {
  id: t.string().primaryKey(), status: t.string(),
  battery: t.f64(), room: t.string(),
});

const alert = table({ name: 'alert', public: true }, {
  id: t.string().primaryKey(), call_id: t.string().index('btree'),
  nurse_id: t.string(), level: t.u32(), message: t.string(),
  created_at: t.string(), acked_at: t.string(),
});

// resident, nurse, visit, memory_fact follow the same pattern (columns per the table above).
const spacetimedb = schema({ call, call_turn, robot, alert /* , resident, nurse, visit, memory_fact */ });
export default spacetimedb;

// Upsert reducer pattern; repeat for the other tables (all take full-row args).
export const save_robot = spacetimedb.reducer(
  { id: t.string(), status: t.string(), battery: t.f64(), room: t.string() },
  (ctx, row) => {
    if (ctx.db.robot.id.find(row.id)) ctx.db.robot.id.update(row);
    else ctx.db.robot.insert(row);
  }
);
```

Unverified in this sketch: the exact unique/primary-key accessor API (`ctx.db.robot.id.find/update`); confirm against the TypeScript module reference (`spacetime dev` generates a working template to copy from).

### Python HTTP wire format (from `/docs/http/database`)

| Need | Call |
| --- | --- |
| Get an identity token (once, store in env) | `POST {host}/v1/identity` returns `{"identity": "...", "token": "..."}` |
| Call a reducer | `POST {host}/v1/database/bellhop/call/save_robot` with header `Authorization: Bearer <token>` and body = **JSON array of positional args**: `["rob1","idle",0.9,""]` |
| Query | `POST {host}/v1/database/bellhop/sql`, body = raw SQL text (`;` separated). Returns `[{"schema": ProductType, "rows": [[...positional...]]}]` |
| Schema/column order | `GET {host}/v1/database/bellhop/schema?version=9` (column order = declaration order; map rows to models by schema element names) |

### Adapter (implemented: `adapters/spacetimedb_store.py`)

Built as `SpacetimeDBStore`, a single facade with the same shape as `InMemoryStore` (no separate `WriteThroughStore`/`SpacetimeClient` classes). Module in `spacetimedb/` (see its README). Extra columns beyond the table above: `call.robot_id`, `call.nurse_tasks`, `resident.birth_year`, `visit.resolved_by_robot/mood`. `append_turn(call_id, seq, speaker, text, at)` derives the turn id. Failed writes are logged and queued (500 max, oldest dropped, retried in order on the next save); `hydrate()` raises if the server is down and `build_container` then falls back to memory. Original plan notes follow.

### Adapter plan (original)

- One `SpacetimeClient` helper (httpx, timeout 2 s) with `call(reducer, *args)` and `sql(query) -> list[dict]` (zip schema names with row values).
- `SpacetimeCallRepository` etc. implement the existing Protocols one-to-one: `save` = flatten model to args then call `save_call` plus `append_turn` for new turns only (track `len(transcript)` already sent); `get/list_*` = `SELECT` then rebuild pydantic models (split comma strings, parse ISO, map `0`/`""` sentinels back to `None`). SQL values must be escaped (single quotes doubled); ids are ours so low risk.
- **Write-through, memory-first**: `container.py` builds `InMemoryStore` as the read path and wraps it in a `WriteThroughStore(primary=memory, mirror=spacetime)` that mirrors every `save` and swallows/logs mirror failures. Reads never touch the network, so the voice loop stays fast and the demo survives a dead SpacetimeDB. On startup, if the DB is reachable, hydrate memory from SQL; otherwise run empty plus `seed_demo`.
- Selected only by `BELLHOP_STORE=spacetimedb`; default stays `memory`. Services and domain are untouched.
- Contract tests: run the same repository test-suite parametrized over `InMemoryStore` and a fake `SpacetimeClient` (no network in CI).

### Recommended MVP sequence

1. `spacetime dev --template react-ts`; replace the template module with the schema above; confirm `spacetime sql` shows rows after `spacetime call`.
2. Dashboard: subscribe to `call`, `alert`, `robot` with generated bindings; render live (works even before Python is wired by calling reducers from the CLI).
3. Python `SpacetimeClient` + `WriteThroughStore` mirroring `save` only (no reads from DB).
4. Add hydrate-on-start and `call_turn` mirroring only if time remains.

**Confidence and gaps:** High on languages, no official Python SDK, install and HTTP endpoints, TS schema syntax, subscription API. Medium on the exact TS primary-key accessor names and `spacetime publish/generate` flag spellings (copy from the generated template). Not verified: JSON encoding of enums/timestamps (avoided by design), row-level security, Maincloud limits.

Sources: [Clients overview](https://spacetimedb.com/docs/clients), [Tables](https://spacetimedb.com/docs/tables/), [Column types](https://spacetimedb.com/docs/tables/column-types/), [Reducers](https://spacetimedb.com/docs/functions/reducers/), [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/), [HTTP /v1/database](https://spacetimedb.com/docs/http/database), [HTTP /v1/identity](https://spacetimedb.com/docs/http/identity/), [TypeScript quickstart](https://spacetimedb.com/docs/quickstarts/typescript), [React quickstart](https://spacetimedb.com/docs/quickstarts/react), [Install](https://spacetimedb.com/install), [FAQ](https://spacetimedb.com/docs/intro/faq), [PyPI spacetimedb-sdk](https://pypi.org/project/spacetimedb-sdk/).

---

## 2. Moss

### Facts

| Question | Answer |
| --- | --- |
| What it is | Semantic + keyword (hybrid) search runtime from InferEdge/Moss. Rust core, embeddings run locally (default model `moss-minilm`), indexes sync to Moss cloud storage. |
| Python SDK | `pip install moss` (1.21.0, Python >= 3.10). **Async API** (`MossClient`). Same-named TypeScript SDK exists. |
| Auth | Project id + project key from the Moss portal (`portal.usemoss.dev`; PyPI page also cites `platform.inferedge.dev`). Env: `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY`. New projects start with no key; create one under API Keys (shown once). |
| Latency claims | Docs home: "sub-10 ms retrieval"; PyPI: "sub-millisecond" on-device; sessions: local query "~1-10 ms". These are vendor claims; measure ourselves. Cloud calls (create/add) are not in that budget. |
| Telemetry | Always sends usage telemetry (project id, index names, counts, latencies, device id). Never query/document text or embeddings (per PyPI/docs). Document text leaves the device only on cloud create/add/push. |

### Mapping to `MemoryIndex`

Our port is **synchronous** and must answer in under 50 ms; Moss is async. Use a **session index** (local, in-process, no cloud round trip per op) so `add` is immediately queryable.

| Port call | Moss call |
| --- | --- |
| startup (`MossMemoryIndex.__init__`) | start one background asyncio loop thread; `client = MossClient(pid, key)`; `session = await client.session(index_name="bellhop-memory")` (auto-loads the cloud index if it exists, else empty) |
| `add(fact)` | `await session.add_docs([DocumentInfo(id=fact.id, text=fact.text, metadata={"resident_id": fact.resident_id, "tags": ",".join(fact.tags), "created_at": fact.created_at.isoformat()})])` (add or update by id) |
| `recall(resident_id, utterance, k)` | `res = await session.query(utterance, QueryOptions(top_k=k, alpha=0.6, filter={"field": "resident_id", "condition": {"$eq": resident_id}}))`; map `res.docs` (`.id`, `.text`, `.score`, `.metadata`) back to `MemoryFact` via an id-to-fact dict kept by the adapter (the adapter already received the facts in `add`) |
| sync bridge | `asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=0.05)`; on timeout or any exception log and delegate to the wrapped `LocalMemoryIndex` (fallback required by `01-module-map.md`) |
| seeding | `seed_demo` calls `add` per fact; optionally `session.push` or `client.create_index(...)` once to persist (verify the SessionIndex push method name in the SessionIndex class reference) |

Design choices: one shared index filtered by `resident_id` metadata (filter needs a loaded index or session, which we have). Metadata values are strings. Also write every fact to `LocalMemoryIndex` in `add` so the fallback is always warm; `recall` returns Moss results only when the call succeeds within budget and returns at least one hit, otherwise local results.

### Recommended MVP sequence

1. Ship `LocalMemoryIndex` (default). Demo works without Moss.
2. Get keys at the sponsor table; run the snippet above standalone and print `res.docs` and wall-clock ms for a first query and a warm query.
3. Add `MossMemoryIndex` behind the loop-thread bridge with the 50 ms timeout and fallback; toggle with `BELLHOP_MEMORY=moss`.
4. Only if time remains: persist the index to the cloud so a restart reloads without re-embedding.

**Confidence and gaps:** High on install, auth, `create_index/load_index/query/add_docs`, filter syntax, session API (official docs). Medium on exact `QueryOptions` field spelling for `filter` (the PyPI page passes `filter=` to `query()`, the API reference puts it inside `QueryOptions`; check the installed version's signature), the session push method name, and whether first-query model load exceeds 50 ms (likely; warm up at startup). Unknown: free-tier limits and key availability at the event.

Sources: [Moss docs home](https://docs.moss.dev/), [Python SDK overview](https://docs.moss.dev/docs/reference/python/api.md), [Sessions](https://docs.moss.dev/docs/reference/python/sessions.md), [Metadata filtering](https://docs.moss.dev/docs/reference/python/metadata-filtering.md), [Authentication](https://docs.moss.dev/docs/integrate/authentication.md), [Telemetry](https://docs.moss.dev/docs/reference/telemetry), [PyPI moss](https://pypi.org/project/moss/).

---

## 3. Fetch.ai (uAgents, Agentverse, ASI:One)

### Facts

| Term | Meaning |
| --- | --- |
| uAgents | Python agent framework (`pip install uagents`, 0.26.1, Python >= 3.10). Chat models live in `uagents_core.contrib.protocols.chat`. |
| Agentverse | Registry/hosting (agentverse.ai). Agents register in the Almanac; a **mailbox** lets an agent running on our laptop receive messages without a public endpoint. |
| ASI:One | Fetch's LLM chat (asi1.ai). It discovers Agentverse agents that speak the Agent Chat Protocol and forwards user questions to them. |
| Hosted vs local | Hosted agents run on Agentverse and get `ASI1_API_KEY` injected, but cannot reach our `localhost` backend. **Run the agent locally with a mailbox** so it can call our FastAPI. |

Keys and accounts needed:

| Item | Needed for | Where |
| --- | --- | --- |
| Agentverse account | mailbox, agent profile, "Chat with Agent" | agentverse.ai |
| Agent `seed` phrase (any secret string; fixes the agent address) | stable `agent1q...` address | we choose, store in `.env` |
| ASI:One API key (`ASI1_API_KEY`) | only if the agent itself calls the `asi1` LLM; **not needed for the plain lookup below** | asi1.ai/developer |
| Mailbox connection | one-time click in the Agent Inspector link printed at startup (Connect, then Mailbox) | terminal log URL |

### Roles and registration

Register **one agent for ASI:One discoverability: the Liaison** (family-facing "what happened in room 12?"). Dispatcher and Triage are internal roles and already exist as services; do not rebuild them as networked agents. If judges want visible multi-agent presence, give Dispatcher and Triage thin uAgents (own seed, own port, own mailbox, same chat-protocol handler) that each answer a read-only status question from our API. Fetch.ai's criteria score Agentverse registration and ASI:One discoverability, so fill in the agent profile: name, `@handle`, README, keywords.

### Implementation (in `backend/src/bellhop/fetchai/`)

Built as three small modules; only `agent.py` imports `uagents` (lazily). Optional extra: `uv sync --extra fetch`.

| File | Role |
| --- | --- |
| `answers.py` | Pure `answer_question(question, calls, alerts, metrics) -> str` (room history, open alerts, metrics, fallback help) |
| `client.py` | `BellhopApi(base_url, timeout=2.0)`: `calls()`, `alerts()`, `metrics()`; any failure raises `BellhopApiError` |
| `agent.py` | `build_agent()`: `Agent(name, seed=$BELLHOP_AGENT_SEED, port, mailbox=True)`, chat `Protocol(spec=chat_protocol_spec)`, ack then reply, `include(protocol, publish_manifest=True)` |

Handler pattern, `mailbox=True` and `chat_protocol_spec` re-checked against the Agentverse "Enable the Chat Protocol" page (2026-10-23): `ChatMessage(timestamp, msg_id, content=[TextContent(type="text", text=...)])`, `ChatAcknowledgement(timestamp, acknowledged_msg_id)`. The `Agent(...)` kwargs are from the uAgents docs, not that page. Correction to the earlier sketch: `GET /calls` already exists and `GET /alerts`, `GET /metrics` too, and the agent lives inside the backend package behind an optional extra, not in `integrations/`.

Run and register (names of keys only; never commit values):

```bash
cd backend
uv sync --extra fetch
export BELLHOP_AGENT_SEED="a long secret phrase"   # fixes the agent address
export BELLHOP_API=http://127.0.0.1:8000           # optional, this is the default
uv run uvicorn bellhop.api.main:app &              # the backend the agent reads
uv run python -m bellhop.fetchai
# 1. open the "Agent inspector" URL printed in the log, click Connect, choose Mailbox
#    (needs an Agentverse account; a mailbox API key / AGENTVERSE_API_KEY may be requested)
# 2. log should show "Registration on Almanac API successful" and the manifest published
# 3. on agentverse.ai set the agent name/handle/README/keywords, click "Chat with Agent"
# 4. in ASI:One chat, enable the Agents toggle and ask: "what happened in room 12?"
```

Keys: `BELLHOP_AGENT_SEED` (ours), Agentverse account and mailbox connection (via the inspector link). `ASI1_API_KEY` is not needed because the agent does no LLM calls. The agent must be running for ASI:One to reach it.

### Recommended MVP sequence

1. `spacetime dev --template react-ts`; replace the template module with the schema above; confirm `spacetime sql` shows rows after `spacetime call`.
2. Dashboard: subscribe to `call`, `alert`, `robot` with generated bindings; render live (works even before Python is wired by calling reducers from the CLI).
3. Python `SpacetimeClient` + `WriteThroughStore` mirroring `save` only (no reads from DB).
4. Add hydrate-on-start and `call_turn` mirroring only if time remains.

**Confidence and gaps:** High on languages, no official Python SDK, install and HTTP endpoints, TS schema syntax, subscription API. Medium on the exact TS primary-key accessor names and `spacetime publish/generate` flag spellings (copy from the generated template). Not verified: JSON encoding of enums/timestamps (avoided by design), row-level security, Maincloud limits.

Sources: [Clients overview](https://spacetimedb.com/docs/clients), [Tables](https://spacetimedb.com/docs/tables/), [Column types](https://spacetimedb.com/docs/tables/column-types/), [Reducers](https://spacetimedb.com/docs/functions/reducers/), [Subscriptions](https://spacetimedb.com/docs/clients/subscriptions/), [HTTP /v1/database](https://spacetimedb.com/docs/http/database), [HTTP /v1/identity](https://spacetimedb.com/docs/http/identity/), [TypeScript quickstart](https://spacetimedb.com/docs/quickstarts/typescript), [React quickstart](https://spacetimedb.com/docs/quickstarts/react), [Install](https://spacetimedb.com/install), [FAQ](https://spacetimedb.com/docs/intro/faq), [PyPI spacetimedb-sdk](https://pypi.org/project/spacetimedb-sdk/).

---

## 2. Moss

### Facts

| Question | Answer |
| --- | --- |
| What it is | Semantic + keyword (hybrid) search runtime from InferEdge/Moss. Rust core, embeddings run locally (default model `moss-minilm`), indexes sync to Moss cloud storage. |
| Python SDK | `pip install moss` (1.21.0, Python >= 3.10). **Async API** (`MossClient`). Same-named TypeScript SDK exists. |
| Auth | Project id + project key from the Moss portal (`portal.usemoss.dev`; PyPI page also cites `platform.inferedge.dev`). Env: `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY`. New projects start with no key; create one under API Keys (shown once). |
| Latency claims | Docs home: "sub-10 ms retrieval"; PyPI: "sub-millisecond" on-device; sessions: local query "~1-10 ms". These are vendor claims; measure ourselves. Cloud calls (create/add) are not in that budget. |
| Telemetry | Always sends usage telemetry (project id, index names, counts, latencies, device id). Never query/document text or embeddings (per PyPI/docs). Document text leaves the device only on cloud create/add/push. |

### Mapping to `MemoryIndex`

Our port is **synchronous** and must answer in under 50 ms; Moss is async. Use a **session index** (local, in-process, no cloud round trip per op) so `add` is immediately queryable.

| Port call | Moss call |
| --- | --- |
| startup (`MossMemoryIndex.__init__`) | start one background asyncio loop thread; `client = MossClient(pid, key)`; `session = await client.session(index_name="bellhop-memory")` (auto-loads the cloud index if it exists, else empty) |
| `add(fact)` | `await session.add_docs([DocumentInfo(id=fact.id, text=fact.text, metadata={"resident_id": fact.resident_id, "tags": ",".join(fact.tags), "created_at": fact.created_at.isoformat()})])` (add or update by id) |
| `recall(resident_id, utterance, k)` | `res = await session.query(utterance, QueryOptions(top_k=k, alpha=0.6, filter={"field": "resident_id", "condition": {"$eq": resident_id}}))`; map `res.docs` (`.id`, `.text`, `.score`, `.metadata`) back to `MemoryFact` via an id-to-fact dict kept by the adapter (the adapter already received the facts in `add`) |
| sync bridge | `asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=0.05)`; on timeout or any exception log and delegate to the wrapped `LocalMemoryIndex` (fallback required by `01-module-map.md`) |
| seeding | `seed_demo` calls `add` per fact; optionally `session.push` or `client.create_index(...)` once to persist (verify the SessionIndex push method name in the SessionIndex class reference) |

Design choices: one shared index filtered by `resident_id` metadata (filter needs a loaded index or session, which we have). Metadata values are strings. Also write every fact to `LocalMemoryIndex` in `add` so the fallback is always warm; `recall` returns Moss results only when the call succeeds within budget and returns at least one hit, otherwise local results.

### Recommended MVP sequence

1. Ship `LocalMemoryIndex` (default). Demo works without Moss.
2. Get keys at the sponsor table; run the snippet above standalone and print `res.docs` and wall-clock ms for a first query and a warm query.
3. Add `MossMemoryIndex` behind the loop-thread bridge with the 50 ms timeout and fallback; toggle with `BELLHOP_MEMORY=moss`.
4. Only if time remains: persist the index to the cloud so a restart reloads without re-embedding.

**Confidence and gaps:** High on install, auth, `create_index/load_index/query/add_docs`, filter syntax, session API (official docs). Medium on exact `QueryOptions` field spelling for `filter` (the PyPI page passes `filter=` to `query()`, the API reference puts it inside `QueryOptions`; check the installed version's signature), the session push method name, and whether first-query model load exceeds 50 ms (likely; warm up at startup). Unknown: free-tier limits and key availability at the event.

Sources: [Moss docs home](https://docs.moss.dev/), [Python SDK overview](https://docs.moss.dev/docs/reference/python/api.md), [Sessions](https://docs.moss.dev/docs/reference/python/sessions.md), [Metadata filtering](https://docs.moss.dev/docs/reference/python/metadata-filtering.md), [Authentication](https://docs.moss.dev/docs/integrate/authentication.md), [Telemetry](https://docs.moss.dev/docs/reference/telemetry), [PyPI moss](https://pypi.org/project/moss/).

---

## 3. Fetch.ai (uAgents, Agentverse, ASI:One)

### Facts

| Term | Meaning |
| --- | --- |
| uAgents | Python agent framework (`pip install uagents`, 0.26.1, Python >= 3.10). Chat models live in `uagents_core.contrib.protocols.chat`. |
| Agentverse | Registry/hosting (agentverse.ai). Agents register in the Almanac; a **mailbox** lets an agent running on our laptop receive messages without a public endpoint. |
| ASI:One | Fetch's LLM chat (asi1.ai). It discovers Agentverse agents that speak the Agent Chat Protocol and forwards user questions to them. |
| Hosted vs local | Hosted agents run on Agentverse and get `ASI1_API_KEY` injected, but cannot reach our `localhost` backend. **Run the agent locally with a mailbox** so it can call our FastAPI. |

Keys and accounts needed:

| Item | Needed for | Where |
| --- | --- | --- |
| Agentverse account | mailbox, agent profile, "Chat with Agent" | agentverse.ai |
| Agent `seed` phrase (any secret string; fixes the agent address) | stable `agent1q...` address | we choose, store in `.env` |
| ASI:One API key (`ASI1_API_KEY`) | only if the agent itself calls the `asi1` LLM; **not needed for the plain lookup below** | asi1.ai/developer |
| Mailbox connection | one-time click in the Agent Inspector link printed at startup (Connect, then Mailbox) | terminal log URL |

### Roles and registration

Register **one agent for ASI:One discoverability: the Liaison** (family-facing "what happened in room 12?"). Dispatcher and Triage are internal roles and already exist as services; do not rebuild them as networked agents. If judges want visible multi-agent presence, give Dispatcher and Triage thin uAgents (own seed, own port, own mailbox, same chat-protocol handler) that each answer a read-only status question from our API. Fetch.ai's criteria score Agentverse registration and ASI:One discoverability, so fill in the agent profile: name, `@handle`, README, keywords.

### Minimal code (Liaison; local run with mailbox, calls our backend over HTTP)

Imports and handler shape are from the Agentverse chat-protocol guide; `mailbox=True` and the `Agent(...)` kwargs are from the uAgents docs. Put this in `integrations/liaison_agent.py` (outside `backend/src/bellhop` so it adds no backend dependency; `pip install uagents httpx` in its own venv).

```python
import os, re
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement, ChatMessage, TextContent, chat_protocol_spec,
)

BACKEND = os.environ.get("BELLHOP_API", "http://127.0.0.1:8000")
agent = Agent(name="bellhop-liaison", seed=os.environ["LIAISON_SEED"], port=8001, mailbox=True)
protocol = Protocol(spec=chat_protocol_spec)

def answer(question: str) -> str:
    m = re.search(r"room\s*(\d+)", question, re.I)
    if not m:
        return "Ask me about a room, for example: what happened in room 12?"
    calls = httpx.get(f"{BACKEND}/calls", timeout=3).json()
    mine = [c for c in calls if c["room"] == m.group(1)]
    if not mine:
        return f"No calls recorded for room {m.group(1)}."
    c = max(mine, key=lambda c: c["created_at"])
    return f"Room {c['room']}: {c['status']}, urgency {c.get('urgency')}. {c.get('summary') or 'No summary yet.'}"

@protocol.on_message(ChatMessage)
async def on_chat(ctx: Context, sender: str, msg: ChatMessage):
    await ctx.send(sender, ChatAcknowledgement(
        timestamp=datetime.now(timezone.utc), acknowledged_msg_id=msg.msg_id))
    reply = answer(msg.text() or "")
    await ctx.send(sender, ChatMessage(
        timestamp=datetime.now(timezone.utc), msg_id=uuid4(),
        content=[TextContent(type="text", text=reply)]))

@protocol.on_message(ChatAcknowledgement)
async def on_ack(ctx: Context, sender: str, msg: ChatAcknowledgement):
    pass

agent.include(protocol, publish_manifest=True)
if __name__ == "__main__":
    agent.run()
```

Run and register:

```bash
pip install uagents httpx
export LIAISON_SEED="a long secret phrase" BELLHOP_API=http://127.0.0.1:8000
python integrations/liaison_agent.py
# 1. open the "Agent inspector" URL printed in the log, click Connect, choose Mailbox
# 2. log should show "Registration on Almanac API successful" and "Manifest published successfully: AgentChatProtocol"
# 3. on agentverse.ai open the agent profile, set name/handle/README/keywords, click "Chat with Agent"
# 4. in ASI:One chat, enable the Agents toggle and ask: "what happened in room 12?"
```

Notes: the agent must be running for ASI:One to reach it. Verify `ChatMessage` fields against the installed `uagents_core`. Cleaner alternative: add `?room=` to `GET /calls` (WP-D change).

### Recommended MVP sequence

1. Finish the HTTP API (`GET /calls`) first; the agent is a thin client of it.
2. Run the Liaison locally with mailbox; confirm the inspector connect and Almanac registration logs.
3. Test through "Chat with Agent" on Agentverse, then through ASI:One with the Agents toggle on.
4. Polish discoverability (profile, README, keywords). Optional: Dispatcher/Triage stub agents.

**Confidence and gaps:** High on the chat-protocol handler pattern, mailbox flow and ASI:One discovery path (two official guides agree). Medium on kwarg details (`mailbox=True`, port, seed) and `ChatMessage` constructor fields across uAgents versions, and on testnet/funding requirements for Almanac registration (a third-party skills package mentions funding on testnet; the official mailbox guide does not). ASI:One may take time to surface a new agent; ranking factors not verified. Judging criteria were taken from Fetch's other hackathon packs and must be confirmed at the table.

Sources: [Enable the Chat Protocol](https://docs.agentverse.ai/documentation/getting-started/enable-chat-protocol), [ASI:One compatible agent (uAgents)](https://uagents.fetch.ai/docs/examples/asi-1), [Agentverse ASI:One guide](https://docs.agentverse.ai/documentation/advanced-usages/asi-one-compatible-agent), [Agentverse chat-protocol integration](https://docs.agentverse.ai/documentation/launch-agents/connect-your-agents-chat-protocol-integration), [PyPI uagents](https://pypi.org/project/uagents/), [ASI:One API keys](https://asi1.ai/developer).
