# Frontend contract

Source of truth for the dashboard (and anything else that talks to the backend).

| File | What it is |
| --- | --- |
| `openapi.json` | OpenAPI 3 spec generated from the live FastAPI app. A backend test fails if it drifts |
| `examples/*.json` | Real responses from the three demo scenes (plus `robots.json`). Use them as mock data before the backend runs |

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
Open http://localhost:8000/docs for interactive docs. CORS allows every origin, so a Vite dev server on another port works.
Demo data: residents Margaret (room 12, falls risk) and Arthur (room 14), nurses `nurse_priya` and `nurse_sam`, robot `robot_1`.

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
| `PUT /robots/{id} {status, battery, room?}` | Robot status report (Pi, every 5 s). `status` is `idle|busy|charging|fault`, `battery` 0 to 1 else 422. Unknown id is created. An `idle` report is ignored for status while the robot holds an open call (battery and room still apply) |
| `GET /alerts` | Alerts for nurses, newest first |
| `POST /alerts/{id}/ack {nurse_id}` | Nurse taps "on my way" |
| `GET /metrics` | Savings counter: `resolved_without_nurse`, `minutes_saved`, `share_answered_within_10min`, `calls_by_hour/room/category` |
| `GET /residents/{id}/memory?q=&k=` | Memory recall for the voice loop |
| `POST /residents/{id}/memory {text, tags?, source?, confidence?}` | Add a fact through the memory guard: 201 + fact; 202 `{status:"pending_review"}` when low confidence from a non-staff source; 422 `{detail: reason}` (`too_short`, `too_long`, `clinical_claim`, `duplicate`) |
| `GET /residents/{id}/memory/pending` | Facts waiting for nurse review |
| `POST /residents/{id}/memory/pending/{pid}/approve` / `reject` | Approve (returns the fact) or drop a pending fact; unknown id 404 |
| `DELETE /residents/{id}/memory/{fact_id}` | Forget one fact (204, unknown 404) |
| `DELETE /residents/{id}/memory` | Forget everything for the resident: `{removed: n}` |
| `POST /residents/{id}/care {kind, value?, note?, call_id?}` | Record `mood`/`pain` (value 1 to 5 required), `drink`, `repeat_question`. Three days of pain in a row opens a PAIN flag |
| `GET /residents/{id}/care/summary` | `{pain_streak_days, mood_lower_than_usual, drinks_today, repeat_questions_today}` |
| `GET /flags?resident_id=&open_only=true` | Flags with a `reason` |
| `POST /flags/{id}/resolve` | Resolve a flag |
| `GET` / `PUT /residents/{id}/preferences` | `{hard_of_hearing, quiet_mode, night_mode, favourite_drink}`; PUT merges the given fields |
| `GET /residents/{id}/speech-settings` | `{rate, volume, captions, tone}` derived from preferences |
| `POST /residents/{id}/family/messages {text}` / `family/replies {text}` | Voice note to the resident / resident reply (201) |
| `GET /residents/{id}/family/messages` | Messages, oldest first |
| `GET /residents/{id}/postcard` | `{lines: [...]}` positive, non-medical summary of today. Never mentions pain |
| `GET /health` | `{"status":"ok"}` |

Unknown call, alert, flag, pending fact or resident gives 404.

## Meaning of the values
- **`urgency`** is an integer: 1 chat, 2 routine, 3 nurse soon, 4 emergency. It never goes down on a call.
- **`status`** moves `ringing, assigned, (robot_en_route), in_visit, resolved, closed`. A call scored 3 or 4 becomes `escalated`, then `nurse_acked` after the nurse acknowledges.
- **`Alert.nurse_id`** is `null` for a broadcast: urgency 4 goes to every nurse on shift. Urgency 3 names one nurse.
- Times are ISO 8601 in UTC. `calls_by_hour` keys are UTC hours as strings.
- `share_answered_within_10min` is `0.0` until at least one call has a first response (`in-visit`).
- `minutes_saved` assumes 4 minutes per robot-resolved call. Label that assumption on screen.
- Errors: unknown id 404, illegal state change 409, bad body 422.

## Live updates
MVP is polling: `GET /calls`, `GET /alerts` and `GET /metrics` once a second is plenty. Streaming (SSE, or SpacetimeDB subscriptions) comes later and will not change these shapes.

## Changing the contract
Change the API in `backend/src/bellhop/api/`, run `cd backend && uv run python scripts/export_contract.py`, and commit `contracts/`. Tell Yash.
