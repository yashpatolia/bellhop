# Frontend contract

Source of truth for the dashboard (and anything else that talks to the backend).

| File | What it is |
| --- | --- |
| `openapi.json` | OpenAPI 3 spec generated from the live FastAPI app. A backend test fails if it drifts |
| `examples/*.json` | Real responses from the three demo scenes, the admin routes and `robots.json`. Use them as mock data before the backend runs |
| `examples/events.json` | One sample of each live event (`GET /events`); OpenAPI cannot describe a stream |

## Get typed fast
```
npx openapi-typescript contracts/openapi.json -o src/api/types.ts   # TypeScript types
```
To mock before the backend runs, serve `examples/*.json` (for example with MSW). Do not hand-write types; regenerate when `openapi.json` changes (`git log contracts/`).

## Run the backend with demo data
```
cd backend
uv sync
BELLHOP_SEED_DEMO=1 uv run uvicorn bellhop.api.main:app --port 8000
```
Open http://localhost:8000/docs for interactive docs. CORS allows every origin by default (`BELLHOP_CORS_ORIGINS` narrows it), so a Vite dev server on another port works.
Demo data: residents Margaret (room 12, falls risk) and Arthur (room 14), nurses `nurse_priya` and `nurse_sam`, robot `robot_1`.

## Auth header
When the backend runs with `BELLHOP_API_KEY` set, send `X-API-Key: <key>` on every request except `GET /health`; a missing or wrong key is `401`. The one exception is `GET /events`, which also accepts `?api_key=<key>` (see [Live updates](#live-updates)). When unset (dev) no header is needed. The scheme (`ApiKeyAuth`, header `X-API-Key`) is always in `openapi.json`, so generated clients carry it. Browser origins other than the configured `BELLHOP_CORS_ORIGINS` (default `*`) are blocked by CORS. Limits: bodies over 1 MB are `413`, over-long strings or lists are `422`, `GET /calls` and `GET /alerts` take `?limit=` (default 200, max 1000).

## Endpoints
| Method and path | Use |
| --- | --- |
| `POST /calls {room}` | Bell press (the web-button backup). Returns the `Call`; robot and nurse are assigned immediately |
| `GET /calls` | All calls, newest first. Poll this for the live feed |
| `GET /calls/{id}` | One call with transcript, summary, timestamps |
| `POST /calls/{id}/turns {speaker, text}` | Add to the transcript (`resident`, `robot`, `nurse`) |
| `POST /calls/{id}/score {urgency, category, summary?, confidence?}` | Triage result; urgency 1 to 4, `confidence` 0 to 1. Passed through the triage guard: keyword floor (fall, chest pain, ...) and low confidence (under 0.6, +1) can only raise urgency; the reason is appended to `summary` |
| `POST /calls/{id}/triage-failed` | The model failed: defaults to urgency 3 (nurse soon); a keyword floor may make it 4 |
| `GET /calls/{id}/note` | One-line visit note `{text, resident_id, room, at}` |
| `POST /calls/{id}/in-visit` | Robot reached the resident |
| `POST /calls/{id}/resolve {by_robot?}` | Finish the call |
| `GET /robots` | Robots with `status`, `battery`, `room` |
| `PUT /robots/{id} {status, battery, room?}` | Robot status report (Pi, every 5 s). `status` is `idle|busy|charging|fault`, `battery` 0 to 1 else 422. Unknown id is created unless the server sets `BELLHOP_ALLOW_NEW_ROBOTS=0` (then 404). An `idle` report is ignored for status while the robot holds an open call (battery and room still apply) |
| `PUT /residents/{id} {birth_year}` | Set the resident's birth year (1880 to 2015, else 422; unknown id 404). Needed for reminiscence |
| `GET /residents/{id}/reminiscence?k=3` | Era-appropriate `ContentItem`s `{id, kind song|film|news|event, year, title, blurb}` from the resident's youth (ages 15-25); empty list without a birth year. Source chosen by `BELLHOP_CONTENT` (`local` default, `wikipedia`, `apify`). See `examples/reminiscence.json` |
| `POST /residents/{id}/reminiscence/ingest?k=5` | Store the era items as memory facts tagged `reminiscence`; returns the 201 list of `MemoryFact`s. Run it at ingest time, not in the voice loop |
| `POST /calls/{id}/override {urgency, nurse_id?}` | Nurse corrects the robot's urgency (1 to 4). Returns the `Call`. Unknown call 404; call not yet resolved (no visit) 409. See `examples/call_override.json` |
| `GET /labelled-examples` | Calls with a nurse override: `{call_id, transcript, robot_urgency, nurse_urgency}`. See `examples/labelled_examples.json` |
| `GET /alerts` | Alerts for nurses, newest first |
| `POST /alerts/{id}/ack {nurse_id}` | Nurse taps "on my way" |
| `GET /metrics` | Savings counter: `resolved_without_nurse`, `minutes_saved`, `share_answered_within_10min`, `calls_by_hour/room/category` |
| `GET /residents/{id}/memory?q=&k=` | Memory recall for the voice loop |
| `POST /residents/{id}/memory {text, tags?, source?, confidence?, quote?, call_id?, at?}` | Add a fact through the memory guard: 201 + fact; 202 `{status:"pending_review"}` when low confidence from a non-staff source; 422 `{detail: reason}` (`too_short`, `too_long`, `clinical_claim`, `duplicate`). A duplicate also counts the existing fact as heard again (`times_seen`, `last_confirmed`). `at` dates a history import. The first tag is the fact's kind (`like`, `dislike`, `person`, `routine`, `health`, `style`, `event`) |
| `GET /residents/{id}/memory/all` | Every stored fact with its provenance: `source`, `confidence`, `quote`, `call_id`, `times_seen`, `last_confirmed`, `created_at` |
| `GET /residents/{id}/memory/pending` | Facts waiting for nurse review |
| `POST /residents/{id}/memory/pending/{pid}/approve` / `reject` | Approve (returns the fact) or drop a pending fact; unknown id 404 |
| `DELETE /residents/{id}/memory/{fact_id}` | Forget one fact (204, unknown 404) |
| `DELETE /residents/{id}/memory` | Forget everything for the resident: `{removed: n}` |
| `POST /residents/{id}/care {kind, value?, note?, call_id?}` | Record `mood`/`pain` (value 1 to 5 required), `drink`, `repeat_question`. Three days of pain in a row opens a PAIN flag |
| `GET /residents/{id}/care/history?days=14&kind=` | Recorded mood, pain and drink entries, oldest first. `POST .../care` also takes an optional `at` to date a reading |
| `GET /residents/{id}/care/summary` | `{pain_streak_days, mood_lower_than_usual, drinks_today, repeat_questions_today}` |
| `GET /residents/{id}/medical`, `PUT /residents/{id}/medical` | Staff-entered medical history `{conditions:[{name,since,note}], allergies, medicines, mobility, diet, last_review, reviewed_by}`. PUT replaces it |
| `POST /residents/{id}/medical/entries {category, text, since?, reviewed_by?}` | Add one reviewed entry (`condition`, `allergy`, `medicine`, `mobility`, `diet`); duplicates are ignored, mobility and diet are replaced. Likes, dislikes, people and routines go to `/memory` (422 here) |
| `POST /residents/{id}/notes/refine {category, text}` | Tidy a note staff typed. Returns `{category, text, since, notes[]}` and saves nothing. Rule based by default, Claude with `BELLHOP_REFINER=claude` |
| `POST /calls/import {...}` | Store a finished call from the past (history import for demos): own times, transcript, `by_robot`. Raises no alerts and triggers no learning |
| `GET /flags?resident_id=&open_only=true` | Flags with a `reason` |
| `POST /flags/{id}/resolve` | Resolve a flag |
| `GET` / `PUT /residents/{id}/preferences` | `{hard_of_hearing, quiet_mode, night_mode, favourite_drink}`; PUT merges the given fields |
| `GET /residents/{id}/speech-settings` | `{rate, volume, captions, tone}` derived from preferences |
| `POST /residents/{id}/family/messages {text}` / `family/replies {text}` | Voice note to the resident / resident reply (201) |
| `GET /residents/{id}/family/messages` | Messages, oldest first |
| `GET /residents/{id}/postcard` | `{lines: [...]}` positive, non-medical summary of today. Never mentions pain |
| `POST /residents {id?, name, room, risk_flags?, birth_year?}` | Create a resident (201). Omit `id` to generate one. Duplicate id or a room another resident occupies is 409; bad body 422 (`name` 1 to 80, `room` 1 to 32, up to 10 flags of 1 to 32 chars, unknown keys). See `examples/resident_created.json` |
| `GET /residents`, `GET /residents/{id}` | `[Resident]` / one `{id, name, room, risk_flags, birth_year}`; unknown id 404 |
| `PATCH /residents/{id}` | Change any of `name`, `room`, `risk_flags`, `birth_year` (only the given keys). Unknown id 404, room taken 409, invalid 422 |
| `POST /nurses {id?, name, on_shift?}` | Create a nurse (201, `on_shift` defaults true); duplicate id 409, invalid 422. See `examples/nurse_created.json` |
| `GET /nurses` | `[{id, name, on_shift, open_tasks}]` |
| `PATCH /nurses/{id}` | Change `name` and/or `on_shift` (going off shift keeps `open_tasks`); unknown id 404, invalid 422 |
| `GET /events` | Live Server-Sent Events stream, see [Live updates](#live-updates) |
| `GET /health` | `{"status":"ok"}` |

Unknown call, alert, flag, pending fact or resident gives 404.

## Meaning of the values
- **`Call.resolved_by_robot`** is set when the call is resolved: `true` only if the robot handled it and no nurse was needed.
- **`urgency`** is an integer: 1 chat, 2 routine, 3 nurse soon, 4 emergency. It never goes down on a call.
- **`status`** moves `ringing, assigned, (robot_en_route), in_visit, resolved, closed`. A call scored 3 or 4 becomes `escalated`, then `nurse_acked` after the nurse acknowledges.
- **`Alert.nurse_id`** is `null` for a broadcast: urgency 4 goes to every nurse on shift. Urgency 3 names one nurse.
- Times are ISO 8601 in UTC. `calls_by_hour` keys are UTC hours as strings.
- `share_answered_within_10min` is `0.0` until at least one call has a first response (`in-visit`).
- `minutes_saved` assumes 4 minutes per robot-resolved call. Label that assumption on screen.
- Errors: unknown id 404, illegal state change 409, bad body 422.

## Live updates
`GET /events` is a Server-Sent Events stream (`Content-Type: text/event-stream`). Polling `GET /calls`, `/alerts` and `/metrics` still works and is a fine fallback. Each message carries the ids plus the full current object, so no second request is needed. Samples: `examples/events.json`.

| `event:` | `data` fields | Full object |
| --- | --- | --- |
| `call.raised` | `call_id`, `room` | `call` |
| `call.assigned` | `call_id`, `robot_id`, `nurse_id` (either may be null) | `call` |
| `call.scored` | `call_id`, `urgency` (1 to 4), `category` | `call` |
| `call.resolved` | `call_id`, `by_robot` | `call` |
| `alert.raised` | `alert_id`, `call_id`, `level` | `alert` |
| `robot.updated` | `robot_id` | `robot` (after `PUT /robots/{id}`) |

The object is read at send time, so it can be newer than the event that triggered it (it is `null` if the record vanished). Each message also has a monotonic `id:`.

```js
const es = new EventSource("http://localhost:8000/events"); // add ?api_key=... if a key is set
for (const name of ["call.raised", "call.assigned", "call.scored", "call.resolved", "alert.raised", "robot.updated"]) {
  es.addEventListener(name, (e) => render(name, JSON.parse(e.data)));
}
es.onerror = () => {}; // the browser reconnects by itself (about 3 s)
```
- **Heartbeat:** a comment line `: ping` every 15 s keeps proxies open; EventSource ignores it.
- **Reconnect:** the server sends `retry: 3000`. Missed events are not replayed (`Last-Event-ID` is ignored), so after every (re)connect refetch `GET /calls` and `GET /alerts`, then apply events. Event ids restart at 1 when the server restarts.
- **Auth:** with `BELLHOP_API_KEY` set, `/events` accepts `X-API-Key` or `?api_key=<key>` (EventSource cannot send headers); wrong or missing is 401. The query parameter is accepted on no other route. It appears in URLs and access logs, so use a dashboard-only key and HTTPS.
- **Limits:** at most 20 concurrent streams (503 above). A slow client loses its oldest queued events (100 per client) rather than slowing the server.

## Changing the contract
Change the API in `backend/src/bellhop/api/`, run `cd backend && uv run python scripts/export_contract.py`, and commit `contracts/`. Tell Yash.
