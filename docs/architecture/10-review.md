# Backend review: over-engineering and prototype security

Snapshot review of `backend/src/bellhop` and `spacetimedb/`. `container.py` and `api/app.py` were being edited during the read, so their line numbers may drift. Demo data only. Severity: HIGH fix before a public demo or it is a real bug, MED fix if time allows, LOW cosmetic or note.

## Verdict

The hexagonal core (domain, ports, services, in-memory store) is proportionate and tested. The weight is in the reliability layer (`guards.py`), speculative config, and several pieces with no caller. The security posture is "trusted LAN": nothing on the HTTP surface is authenticated, and the data store and agent are readable by anyone who finds them.

## 1. Over-engineering and vanity

| # | Sev | Where | Finding | Verdict and one-line fix |
| --- | --- | --- | --- | --- |
| V1 | HIGH | `guards.py:83-117`, `container.py:177-185` | `GuardedNotifier` and `GuardedRobotGateway` guard things that cannot hang. The only notifier is `RecordingNotifier` (list append, `notifiers.py:17`). `HttpRobotGateway` already has an httpx timeout (`http_robot_gateway.py:12`, same 2 s), so the pool hop adds a second timeout and a thread per call. `retry_failed` and `failed_alerts` have no caller outside tests. | Delete both wrappers, `retry_failed`, `Container.guarded_notifier` and `guarded_gateway`. Re-add when a real notifier exists. |
| V2 | HIGH | `guards.py:151-171`, `container.py:185` | `SerializedSubscriptions` is a bus decorator used for exactly one handler. It is installed only when guards are on, but the check-then-act race in `Dispatcher._on_call_raised` (`dispatcher.py:82`) exists regardless, because FastAPI runs sync handlers concurrently. It also holds the lock across a 2 s gateway timeout, so one hung robot serialises every bell press. It is an `RLock` with no re-entry. | Replace with a plain `threading.Lock` inside `Dispatcher`, always on, held only around pick-and-reserve (mark the robot BUSY before the gateway call, roll back on failure). |
| V3 | MED | `container.py:62-65`, `from_env` `:73-86` | Speculative config: `notifier_timeout`, `gateway_timeout`, `memory_budget_ms` are never read from env and `memory_budget_ms` has no test. `guard_timeouts` toggles three unrelated behaviours. | Delete the three fields (keep literals); keep one `BELLHOP_GUARDS` flag only if `GuardedMemoryIndex` survives. |
| V4 | MED | `container.py:89-113` | 22 `Container` fields. `dispatcher`, `liaison`, `feedback`, `workload` are held only because their constructors subscribe to the bus; no route reads them. `RobotSignals` is not stored at all (`:225`), so the pattern is inconsistent. | Do not store subscribers. Build them in `build_container` as locals and keep only fields the API or tests read. |
| V5 | MED | `feedback.py:47-58`, `analytics.py:41`, `labelled/io.py:32`, `memory_service.py:30` | No route calls `FeedbackService.rate`, `nurse_override`, `Analytics.labelled_examples`, `from_overrides` or `MemoryService.prompt_context`. The "learn from nurse overrides" loop is unreachable over HTTP. | Either add one `POST /calls/{id}/override` route (10 min) or delete the chain. Do not demo it as working. |
| V6 | MED | `apify_content.py:42-54` vs `wikipedia_content.py:122-134` | Third `ContentFeed` that does the same job slower (about 12 s against 1 s), costs money, and duplicates the cache-then-fallback-then-slice logic. It also parses one year where Wikipedia samples three, so results differ by backend. | Keep only if the Apify prize track is being shown; otherwise delete (79 lines + test). Do not refactor into a base class. |
| V7 | MED | `triage_guard.py` (303 lines), `01-module-map.md` limits | Keyword floor with measured recall of 3 of 15 on a fresh batch. It is more code than `dispatcher.py` plus `call_service.py` combined and invites over-trust in a safety path. | Keep the ratchet and the model-failure default (3). Cut the rule table to the obvious fall and chest-pain phrases; label the rest "demo heuristic" in the API docs. |
| V8 | LOW | `moss_memory.py:30,38,55` | `MossMemoryIndex._facts` duplicates the fallback's store, builds a new `MossClient` on every call (`:68,:71`, inside a 50 ms budget), and the SDK shape is marked "unverified". See S3 for the bug this causes. | Keep behind the flag but verify once against the real SDK, or delete before the demo. |
| V9 | LOW | `local_memory.py`, `deletable_memory.py:3` | `LocalMemoryIndex` and `DeletableLocalMemoryIndex`: only the subclass is ever constructed, and it imports a private `_ResidentIndex`. `MemoryGuard._Index` is a Protocol with one implementation. | Merge into one class with `remove` and `facts`. |
| V10 | LOW | `dispatcher.py:32-60` | `DispatchPolicy` Protocol with one implementation (`DefaultPolicy`) and no test of the protocol. | Keep: 6 lines, and a policy seam is plausible for judges. No action. |
| V11 | LOW | `notifiers.py:23`, `models.py` `ROBOT_EN_ROUTE`, `CLOSED` | `CompositeNotifier` unused in src. `CallStatus.ROBOT_EN_ROUTE` is never entered by any code. `call_with_timeout(default=)` unused. `spacetimedb/src/index.ts:97-106,221` `memory_fact` table and `save_memory_fact` reducer have no Python caller. | Delete `CompositeNotifier`, the `default` parameter, and the memory_fact table and reducer (or wire it). |
| V12 | LOW | `http_robot_gateway.py:21-25`, `call_service.py:13`, `feedback.py:29` | Accepted-but-ignored or redundant params: `robot_id` ignored in both gateway methods (documented); `CallService(nurses=None)` optional though always passed; `record_resolution(robot_id)` duplicates `call.robot_id`. | Make `nurses` required; drop `robot_id` from `record_resolution`. Gateway note is fine. |
| V13 | LOW | `fetchai/` (190 lines) | Three small modules, pure `answers.py`, one lazy sponsor import. Proportionate, and the only external client of the API. | Keep. Drop the public `wants_alerts`/`wants_metrics` names (underscore them). |
| V14 | LOW | `spacetimedb_store.py:226-298` | Client, Writer, queue, `_Through`, 12 converter helpers, 384 lines for six upserts. The bounded queue and in-order retry are justified, but a store that is optional and read-only mirrored is the biggest module in the repo. | Keep. Memory, care data and medical history now persist through `spacetimedb_data.py` (ADR-25). |

### Too thin to be correct

| # | Sev | Where | Finding | One-line fix |
| --- | --- | --- | --- | --- |
| T1 | MED | `spacetimedb_store.py:278-282` | Write-through is synchronous in the request path. With the server down, each `save` first retries the queue head (2 s timeout), then queues. A bell press does several saves, so latency is several seconds, which is the stall `guards.py` was written to prevent, and the store is not guarded. | Fire writes from a single background worker thread fed by the existing deque. |
| T2 | MED | `spacetimedb_store.py:329,355-358,293-296` | `_sent_turns`, the deque and `flush` are unsynchronised across threadpool threads: concurrent flush can reorder or duplicate reducer calls. A full queue silently drops the oldest write (a lost turn), logged only as the reducer name. | One lock around `send` and `flush`, or the worker thread from T1. |
| T3 | MED | `memory_store.py:30`, `local_memory.py:289`, `care_store.py:44` | `list_all` iterates `dict.values()` while another request saves, which can raise `RuntimeError: dictionary changed size`. `GET /calls` racing `POST /calls` can 500. | Iterate over `list(self._items.values())`; copy postings before iterating. |
| T4 | MED | `call_service.py:46`, `liaison.py:46` | Read-modify-write on whole snapshots with no versioning: two concurrent `add_turn` calls lose a turn; `Liaison._claim_nurse` and `Dispatcher._charge_nurse` both bump `open_tasks` and can overwrite each other. | One `RLock` in `CallService` mutators and the nurse-claim paths. |
| T5 | MED | `app.py:314-330` | `PUT /robots/{id}` check-then-act on `list_open` can race the dispatcher and free or double-book a robot. | Take the same dispatch lock as V2. |
| T6 | LOW | `guards.py:39` | `future.cancel()` does nothing to a running call, so a timed-out call keeps its thread. With pool size 8 and a hung robot, the pool exhausts after 8 timeouts. | Documented limit; with V1 applied only memory recall remains. |

## 2. Prototype security and privacy

### Fix before a public demo

| # | Sev | Where | Finding | One-line fix |
| --- | --- | --- | --- | --- |
| S1 | HIGH | `app.py:213,219,254,123,258,314` and all other mutators | No authentication anywhere. Anyone can `DELETE /residents/{id}/memory`, resolve a flag, resolve or create calls, ack alerts as any `nurse_id`, set robot status, change birth year. | One shared-secret dependency (`X-Bellhop-Key` from env) on every non-GET route and on `/alerts`, `/calls` reads: about 20 min. |
| S2 | HIGH | `agent.py:42-55`, `fetchai/answers.py:90-120` | The published agent (`mailbox=True`, `publish_manifest=True`) answers any ASI:One sender with room history, alert text and call summaries. Summaries and alert messages are resident utterances (`liaison.py:269-276`). | Allowlist senders, or answer with room, urgency and status only (no summary text). |
| S3 | HIGH | `moss_memory.py:30,38,55-57`, `memory_guard.py:114` | Bug and privacy: with `BELLHOP_MEMORY=moss`, `forget` removes only the local index. `MossMemoryIndex._facts` and the Moss cloud copy keep the fact, and `_resolve` still returns it, so a "forgotten" fact comes back in recall while `DELETE` returned 204. | Remove from `_facts` on delete (5 min), or refuse `moss` for the demo; note that the cloud copy is not erased. |
| S4 | HIGH | `spacetimedb/src/index.ts:8,28,…` | Every table is `public: true` and reducers take anonymous callers, so on Maincloud anyone with the database name can subscribe to transcripts, names and risk flags and overwrite any row. Token auth was never exercised (`06-integrations.md:27`). | Keep it on localhost for the demo; if hosted, make tables private and check `ctx.sender` in reducers. |
| S5 | MED | `app.py:111-113` | CORS `*` with all methods and headers. Combined with S1, any web page open in a nurse's browser can fire `DELETE`/`POST` at a backend on localhost or the LAN. | `allow_origins=[os.environ["BELLHOP_DASHBOARD_ORIGIN"]]`; 3 min. |
| S6 | MED | `app.py:58`, `call_service.py:76` | `by_robot` is client-asserted and drives `resolved_without_nurse` and `minutes_saved`, the headline pitch metrics. Anyone can inflate them. | Behind S1; ignore the client flag unless the caller holds the key. |
| S7 | MED | `app.py:258,272`, `apify_content.py:42`, `wikipedia_content.py:122` | Unauthenticated `PUT /residents/{id}` plus `POST …/reminiscence/ingest` lets a caller walk birth years 1880-2015 to trigger up to 136 Apify runs (paid, 60 s, one threadpool slot each) or about 400 Wikipedia fetches. | Behind S1; cap Apify to the seeded residents' years. |
| S8 | MED | `app.py:46,72,79,182`, `memory_guard.py:92` | Unbounded inputs. `TurnIn.text`, `speaker`, `RaiseCall.room`, `CareIn.note`, `MemoryIn.tags`, `source` and `recall` `q`/`k` have no limits; the 280-char fact cap runs only after the whole body is parsed. Low-confidence facts fill `_pending` without bound. | `Field(max_length=…)` on every str and list, `k` le 20, and a body-size middleware (1 MB); 15 min. |
| S9 | MED | `notifiers.py:17`, `robot_gateway.py:8`, `guards.py:89`, `app.py:128` | In-memory growth with no cap: `RecordingNotifier.sent`, `RecordingRobotGateway.commands`, `failed_alerts`, care entries, family messages, transcripts. `GET /calls` and `/alerts` return everything, with full transcripts. `PUT /robots/{any id}` creates unbounded robots (each also written through to SpacetimeDB). | `deque(maxlen=1000)` for the recorders; `limit` on `GET /calls`; restrict `report_robot` to known ids. |

### Fine for a hackathon prototype

| # | Sev | Where | Finding | Note |
| --- | --- | --- | --- | --- |
| P1 | LOW | `app.py:102-104` | Error bodies echo `str(exc)`: ids and `unknown nurse: x`. No names, transcripts or facts leak. Unhandled errors give a bare 500. | Acceptable. |
| P2 | LOW | logs | Logs carry alert ids, reducer names, exception class names, no transcript text. `container.py:157` logs the SpacetimeDB URL, which would expose userinfo if one were embedded. `event_bus.py` and `guards.py` use `log.exception`, tracebacks only. | Acceptable; log host only. |
| P3 | LOW | `container.py:52-68` | `Settings` is a frozen dataclass holding `apify_token`, `moss_project_key`, `spacetimedb_token`; its `repr` prints them if anyone logs the settings. | `field(repr=False)` on the three secrets; 2 min. |
| P4 | LOW | `.gitignore`, `apify_content.py:67` | Secrets are env-only; `.env*` ignored; `!.env.example` is allowed but the file does not exist. Apify token goes only in the Authorization header. No secret found in the repo. `spacetimedb/dist` has one tracked file. | Add `.env.example` with names only. |
| P5 | LOW | `container.py:173`, `http_robot_gateway.py:12` | `BELLHOP_ROBOT_URL` is operator-set env, not request input, so there is no SSRF from callers. No scheme check; httpx does not follow redirects by default. Wikipedia and Apify URLs interpolate only ints. SQL strings are constants. | Acceptable; assert `http(s)` scheme. |
| P6 | LOW | `wikipedia_content.py:104` | The User-Agent contains a personal GitHub URL (Wikimedia asks for contact). | Fine; swap for a team contact. |
| P7 | LOW | GET routes | Unauthenticated reads expose care notes, memory facts, family messages and postcards by guessable id (`res_margaret`). Demo data only. | Covered by S1 if the key also protects reads. |

Thread-safety summary: single-key dict get and set are atomic under the GIL, so simple routes are safe. Failures are iteration during mutation (T3), lost updates (T4) and check-then-act (V2, T5). All are low probability at demo traffic and cheap to remove with one lock.

## Top 10 actions

| Rank | Action | Fixes | Minutes |
| --- | --- | --- | --- |
| 1 | Shared-secret auth dependency on all mutating routes and on `/alerts` and `/calls`; CORS restricted to the dashboard origin | S1, S5, S6, S7 | 25 |
| 2 | Fix `MossMemoryIndex` delete (drop from `_facts`) or pin `BELLHOP_MEMORY=local` for the demo and say so | S3 | 5 |
| 3 | Agent sender allowlist, or reduce answers to room, urgency and status only | S2 | 15 |
| 4 | `max_length` and size limits on all body fields, `k` cap, 1 MB body middleware | S8 | 15 |
| 5 | Delete `GuardedNotifier`, `GuardedRobotGateway`, `SerializedSubscriptions`, `CompositeNotifier`, `retry_failed` and the two Container fields; move the one dispatch lock into `Dispatcher` | V1, V2, V11, T5 | 30 |
| 6 | Iterate over copies in `list_all`, `LocalMemoryIndex.recall` and `_Flags.list`; add one `RLock` to the `CallService` mutators | T3, T4 | 20 |
| 7 | Cap recorders with `deque(maxlen)`; `limit` on `GET /calls`; restrict `PUT /robots` to known ids | S9 | 15 |
| 8 | Move SpacetimeDB writes to one background worker (or keep localhost-only and document); make tables private if ever hosted | T1, T2, S4 | 30 |
| 9 | Drop dead config and fields (V3, V4, V11 memory_fact), `field(repr=False)` on secrets, add `.env.example` | V3, V4, P3, P4 | 15 |
| 10 | Decide on the unreachable feedback and labelled loop (add one override route or delete) and on Apify (keep for the prize or delete) | V5, V6 | 20 |
