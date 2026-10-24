# Bellhop: the robot that answers the call bell

Bellhop is a small AI robot that rolls to a resident's room when the call bell rings, talks to them, and calls a nurse only when the situation needs one. It was built for CalHacks. This README explains how the system works technically: the architecture, each component, and why we made the choices we did.

The plan, research and polished HTML pages live in `artifacts/` (index at the bottom). This file is the engineering view.

## Contents

1. [System overview](#system-overview)
2. [The call lifecycle](#the-call-lifecycle)
3. [The agents](#the-agents)
4. [Hardware](#hardware)
5. [Backend and the data contract](#backend-and-the-data-contract)
6. [The nurse dashboard](#the-dashboard)
7. [Live data: SSE, REST and polling](#live-data-sse-rest-and-polling)
8. [Theming](#theming)
9. [The simulator and the two environments](#the-simulator-and-the-two-environments)
10. [Metrics and the savings claim](#metrics-and-the-savings-claim)
11. [Safety guardrails](#safety-guardrails)
12. [Design decisions and tradeoffs](#design-decisions-and-tradeoffs)
13. [Running it](#running-it)
14. [Repository map](#repository-map)
15. [Current status](#current-status)

## System overview

```text
  bell button (ESP32)                         nurse dashboard (browser)
        |                                              ^
        v                                              | REST snapshot + SSE events
  +-----------+   work items    +------------------------------------+
  | Dispatcher| --------------> |  Backend (FastAPI-style HTTP API)  |
  +-----------+                 |  /calls /alerts /robots /metrics   |
        |                       |  /events (Server-Sent Events)      |
        v                       +------------------------------------+
  +-----------+  audio/telemetry          ^
  |  Robot    | <---------------+         |  writes
  | (Pi 5)    |                 |   +-------------+
  | Navigator |                 +---| Companion   |  STT -> Claude -> TTS
  +-----------+                     | Triage      |  urgency 1 to 4
                                    | Memory      |  per-resident profile
                                    | Staff Liaison
                                    +-------------+
```

Three tiers:

- **Edge:** the bell button and the robot (Raspberry Pi 5 on a Freenove 4WD chassis). The robot drives, listens and speaks.
- **Cloud and backend:** the agents (Dispatcher, Companion, Triage, Memory, Staff Liaison) and one HTTP API that holds the state of calls, alerts and robots.
- **Dashboard:** a browser app for nurses. It never talks to the robot or agents directly. It only reads state from the backend, so a broken agent cannot break the screen.

The key architectural rule is that **the backend API is the single source of truth and the dashboard is a pure view of it**. Everything the nurse sees is derived from `Call`, `Robot` and a few other records.

## The call lifecycle

A call moves through a small state machine. The backend owns it (`ringing, assigned, robot_en_route, in_visit, escalated, nurse_acked, resolved, closed`); the dashboard shows the simpler view below, mapped in `dashboard/src/data/adapt.ts`.

```text
robot_en_route -> robot_with_resident -> resolved                  (urgency 1 and 2, robot handles it)
robot_en_route -> robot_with_resident -> nurse_notified -> nurse_en_route -> resolved   (urgency 3)
robot_en_route -> nurse_notified (immediately, robot stays) -> nurse_en_route -> resolved (urgency 4)
waiting -> nurse_notified -> ...                                   (no robot was free, a nurse owns it)
```

Urgency levels, always shown with words as well as colour:

| Level | Label | Who acts |
| --- | --- | --- |
| 1 | Robot resolving | Robot only. Chat, comfort. Never reaches a nurse. |
| 2 | Staff task | Routine help. The robot stays with the resident. |
| 3 | Needs a nurse | Nurse gets a short written summary. |
| 4 | Emergency | Alert fires immediately. Robot stays with the resident. |

Each call carries its own explanation: the triage `summary` (including the reason when a safety rule raised the level) and the full transcript. The dashboard adds the resident's background from what Bellhop knows about them.

## The agents

Six agents, each with one job (full table in [01-project.md](docs/plan/01-project.md)):

| Agent | Job | Runs on |
| --- | --- | --- |
| Dispatcher | Picks who answers each bell using risk flags and nurse load | Cloud |
| Navigator | Drives to the room, avoids obstacles, parks facing the resident | Robot |
| Companion | The conversation: STT, Claude, TTS, calm with confused residents | Cloud and robot audio |
| Triage | Scores urgency 1 to 4 from words, tone and camera | Cloud |
| Memory | Per-resident profile injected before every visit | Cloud |
| Staff Liaison | Notifies the right person with a short summary, or creates a task | Cloud |

Design notes:

- **Triage is two stage.** A fast typed classifier returns urgency and category with probabilities. Claude is the fallback and the explainer: it reviews any score below a confidence threshold and writes the human readable summary and SBAR. This keeps latency low on the common case and spends the large model only where judgement matters.
- **Triage is biased to escalate.** When the score is uncertain the call is treated as more urgent, not less. A false alarm costs a nurse a minute, a miss can cost far more.
- **Memory is injected, not retrieved on demand.** The resident's profile (likes, people, routines, recent mood) is put into the Companion's prompt before it speaks, so the first sentence already sounds like someone who knows them. Retrieval has to be fast (sub 10 ms target) because it sits inside the voice loop.
- **Orchestration is deliberately boring.** The Claude Agent SDK runs Companion and Triage. Dispatcher, Navigator, Memory and Staff Liaison are plain async Python workers. Small, separately testable agents also make the work easy to split across teammates.

## Hardware

Freenove 4WD Smart Car Kit with a Raspberry Pi 5, a USB speakerphone, a Wi-Fi bell button (ESP32 or Pico W), and a screen for captions and games.

- **Navigation is line following plus QR.** Black tape runs down the corridor and one QR sticker per door tells the camera which room it is at. This is far more reliable in a 48 hour build than SLAM, and the demo floor is controlled. The tradeoff is that it only works on prepared routes.
- **Separate power for the Pi.** Motors draw enough current to brown out a shared supply, so the Pi gets its own stable battery.
- **LEDs are a status channel.** Idle, listening, nurse on the way and emergency each get a colour so state is readable from across a room. Words are shown on the dashboard, so colour is never the only signal there.
- **Fallback:** if navigation fails on stage, the robot can be driven with the Freenove app while every other part stays real.

## Backend and the data contract

The backend is an HTTP API run by the backend teammate (Aditya). The dashboard depends only on this surface:

| Endpoint | Purpose |
| --- | --- |
| `GET /health` | Liveness, returns `{"status":"ok"}` |
| `GET /calls`, `/alerts`, `/robots`, `/metrics` | Full current state, used for first load and recovery |
| `GET /events` | Server-Sent Events stream |
| `POST /calls` | Create a call (demo script and bell) |

SSE event names: `call.raised`, `call.assigned`, `call.scored`, `call.resolved`, `alert.raised`, `robot.updated`. Every event carries identifying fields plus the **full current object** (`call`, `alert` or `robot`), so a client never needs a follow up request per event.

Network and auth:

- The backend is reached over **Tailscale** (a `100.x.x.x` address), not venue Wi-Fi and not a public tunnel. Venue networks are unreliable and often isolate clients. Tailscale gives a stable address across hotspots and keeps port 8000 off the public internet.
- The address is configuration, not code. It can change if the laptop is re-added.
- Auth is optional. If `BELLHOP_API_KEY` is set, REST calls send `X-API-Key`, and because browsers cannot set headers on `EventSource`, `/events` takes `?api_key=` instead. That query key can land in logs and history, so it must be a dashboard-only demo key and never committed.

The original shared-state plan was SpacetimeDB (live subscriptions with no polling code). The team shipped a plain HTTP plus SSE API instead; see tradeoffs below.

## The dashboard

`dashboard/` is Vite, React 19 and TypeScript, with Motion for animation. There is no router library and no state library. It has **no data of its own**: everything it shows comes from the backend over HTTP and SSE, so it behaves the same whether the backend holds a real home or the simulator's example home.

```text
dashboard/src/
  App.tsx               source creation and hash routing
  api/                  schema.d.ts (generated from contracts/openapi.json), types.ts
  data/
    types.ts            the view model the screens read: Call, Robot, Resident, Snapshot, Actions
    adapt.ts            wire format to view model. Pure, tested against contracts/examples
    store.ts            REST for the first load, SSE for updates, polling as a safety net, the actions
    source.ts           the React hooks and the backend address
  lib.ts                labels, status text, KPI maths
  components/           Charts
  views/                InsightsView
  layouts/sumi/         the one layout ("Slate & Coral"): Layout.tsx, ResidentsPage.tsx, layout.css
  layouts/shared.tsx    blocks used by the layout (activity log, detail, numbers, robots)
  theme/themes.css      tokens
```

Regenerate the wire types after the contract changes: `npm run gen:api`.

### Views

Four views share the same data: **Live** (the most urgent call, the activity log, robots, numbers), **Dispatch** (pick a room, see which robots are free, choose which free robot to drive there, the closest is preselected, and stop a driving robot; `POST /robots/{id}/navigate` and `/stop`), **Insights** (KPIs, hourly chart, category mix, backend metrics, alerts) and **Residents** (add a resident and give them a room, change a room, search, profile, habits and tendencies from the call history, what Bellhop has learned with the nurse review queue, staff notes, medical history, call history with full conversations). Routing is a hash (`#/`, `#/dispatch/<room>`, `#/insights`, `#/residents`, `#/residents/new`, `#/residents/<id>`, `#/residents/<id>/edit`, `#/residents/<id>/<callId>`). A hash router needs no server config, which matters because the dashboard may be served from a laptop or a static host.

When the backend cannot be reached the screens say so and keep trying; when the home is empty they say that instead of showing blank panels.

## Live data: SSE, REST and polling

`data/store.ts` implements the recovery-first pattern from the integration guide.

1. On `start()`, load calls, alerts, robots, nurses and metrics, then every resident with their memory, pending facts, medical history and care readings (REST).
2. Then open exactly one `EventSource` on `/events`.
3. Each event upserts the **full object** by `id` into the snapshot and notifies subscribers. A resolved call also schedules a short refresh of that resident, because learning from the conversation runs in the background after the call resolves.
4. On every (re)connect of the stream, load everything live again. The stream does not replay missed events.
5. A 10 second poll runs as a safety net. If a request fails the screens switch to "Cannot reach Bellhop" and retry every 3 seconds.
6. `stop()` closes the stream and clears the timers, so React remounts do not leak connections.

Why SSE rather than WebSockets or pure polling:

- The traffic is one way (server to dashboard), so SSE is enough. It rides plain HTTP, reconnects automatically and needs no client library.
- Polling alone would feel laggy for urgency 4 alerts. SSE alone is not correct: the stream deliberately **does not replay** missed events, so after any reconnect the client must refetch. The combination gives low latency in the normal case and correctness after any outage.
- WebSockets would add two-way capability we do not use, plus more reconnect logic to write.

Actions go to the backend and the result comes back through the same stream: "I'm on my way" acknowledges the call's alert (`POST /alerts/{id}/ack`), "Mark done" resolves it as staff, Approve and Reject answer the memory review queue, and a staff note is tidied by `POST /residents/{id}/notes/refine` and saved to memory or the medical history. A failed action shows its reason for a few seconds.

## Theming

A theme is a block of CSS variables in `theme/themes.css` under `[data-theme='id']`: surfaces, ink levels, accent, four urgency colours, radii, fonts and background. Every component reads only tokens, so adding a palette needs no component changes. The one layout shipped is "Slate & Coral" (`layouts/sumi/`).

Design rules, from `CLAUDE.md`:

- The audience is nurses and caretakers: large type, strong contrast, calm. Urgency is always words plus colour, never colour alone.
- Soft neutral palettes only. No amber. Body text and numbers stay highly legible.
- The page fills the full width, because the dashboard runs on a wall or desk monitor.

## The simulator and the two environments

The example home is a **separate service**, `simulator/`, that talks to the backend through the same public routes the robot and staff use. The dashboard cannot tell it from a real home. See [simulator/README.md](simulator/README.md).

| Environment | What runs | Use it for |
| --- | --- | --- |
| `scripts/dev.sh mock` | backend, simulator (twelve residents with facts, medical history and fourteen days of calls, then live bell presses), dashboard | building and rehearsing the UI, demos without hardware |
| `scripts/dev.sh empty` | backend and dashboard only | integrating the real robot and staff entry; the home stays empty until something posts to it |

## Metrics and the savings claim

`computeKpis` in `lib.ts` derives the numbers shown on Live and Insights from the call list: totals, resolved by robot, median first response and share answered within 10 minutes. The backend's own `/metrics` totals are shown beside them.

**Minutes saved = robot-resolved calls x 4 minutes.** The 4 minutes per call is an assumption taken from the research, and it is labelled as an assumption on screen. We state it openly because no study measures this for our setup, and a hidden constant would be an overclaim. The financial model (about 970 staff hours a year and roughly $24,000 of staff time for about $3,200 of running cost at 40 resolved calls a day) is in the research docs and rests on stated, untested assumptions.

## Safety guardrails

- Prototype only: demo residents are teammates and there is no real patient data.
- The bell stays a bell. Anyone can still reach a person, and the robot never discourages calling a nurse.
- Escalate when unsure.
- No diagnosis. The robot gathers and passes on information, it does not give medical advice.
- Gentle with confusion: never argue or correct sharply.
- API keys are never committed. `.env.local` is gitignored and `.env.example` documents the variables.

## Design decisions and tradeoffs

| Decision | Why | What we gave up |
| --- | --- | --- |
| Robot first, nurse only if needed | Cuts interruptions for non-clinical calls, which research suggests is a large share | Added moving parts; a wrong triage on stage is visible, hence escalation bias |
| One data seam in `source.ts` | UI built and demoed before the backend existed; backend swap touches one folder | A thin abstraction to maintain; only as rich as the `Snapshot` type |
| `useSyncExternalStore` instead of a state library | Perfect fit for an external, subscribable store; zero dependencies | Updates replace the whole snapshot object, fine at this scale |
| SSE plus REST refetch, with polling fallback | One way push is all we need; refetch guarantees correctness since events are not replayed | Three code paths to test; more than polling alone |
| Full object in every event | Client never makes a per-event follow up call; upsert by id is trivial | Larger payloads than diffs |
| HTTP API instead of SpacetimeDB | Faster to build and debug in 48 hours with Python agents; trivially mockable | Loses SpacetimeDB's built-in live queries and the sponsor integration |
| Tailscale for connectivity | Stable address across hotspots and isolated Wi-Fi; no public exposure | Every dashboard machine must join the tailnet; address is config |
| Line tracking plus QR navigation | Reliable and quick to build on a controlled floor | No general autonomy; tape must be laid |
| Claude as fallback and explainer over a fast classifier | Low latency on easy cases, careful reasoning on hard ones | Two models to keep in agreement |
| Hash routing, no router lib | Works from any static host or file; three views only | No nested routes or code splitting by route |
| Simulator as its own service | The dashboard has no fake data path; mock and real homes go through the same API | One more process to start in a demo |
| Words as well as colour for urgency | Accessibility and readability under stress | Slightly busier chips |
| Assumption-labelled savings counter | Honest metric a judge can interrogate | A less dramatic headline number |

## Running it

Everything at once, on this machine:

```bash
scripts/dev.sh mock     # backend + simulator + dashboard, with an example home that keeps ringing
scripts/dev.sh empty    # backend + dashboard, nothing in the home
scripts/dev.sh mock --scene busy --rate 3 --speed 2    # options go to the simulator
```

Then open http://localhost:5173. Needs `uv` and `npm`; run `npm install` in `dashboard/` once. Ports: `BACKEND_PORT` (8000) and `DASHBOARD_PORT` (5173).

Dashboard against a backend elsewhere (for example on the team tailnet):

1. Install Tailscale and join the team tailnet (ask Aditya for an invite).
2. Check the backend is reachable: `curl http://100.81.196.22:8000/health` should return `{"status":"ok"}`.
3. Copy `dashboard/.env.example` to `dashboard/.env.local` and set `VITE_BELLHOP_API_URL`. Add `VITE_BELLHOP_API_KEY` only if the backend uses a key.
4. Run `npm run dev`.

Other scripts in `dashboard/`: `npm run build` (typecheck and bundle), `npm run lint` (oxlint), `npm run test` (vitest), `npm run gen:api` (wire types from the contract).

Pre-demo checklist: health check passes, the first load fills the screens, a pressed bell appears without refresh, a robot status change updates its row, stopping and restarting the backend shows "Cannot reach Bellhop" and then recovers by itself.

## Code and architecture

| Path | What's in it |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Start here if you are an AI agent or new contributor: commands and rules |
| [docs/architecture/](docs/architecture/README.md) | Architecture, module map, extension guide, agent roles, decisions, testing |
| [contracts/](contracts/README.md) | Frontend contract: OpenAPI spec plus real example payloads, kept in sync by a drift test |
| [docs/architecture/11-status.md](docs/architecture/11-status.md) | Progress checklist: done and verified, unverified, gaps, blocked, next, team handoff |
| [backend/](backend/README.md) | Python backend (`uv`): call state, dispatch, memory recall, staff alerts, config table |

### Ask Bellhop through ASI:One (optional)

```bash
cd backend
uv sync --extra fetch
export BELLHOP_AGENT_SEED="<long secret phrase>"   # never commit it
uv run uvicorn bellhop.api.main:app &
uv run python -m bellhop.fetchai                   # then connect the Mailbox via the Agent inspector link; needs an Agentverse account
```

Then ask "what happened in room 12?" from ASI:One with the Agents toggle on. Details: `docs/architecture/06-integrations.md`.

## Repository map

| Path | What it is |
| --- | --- |
| `dashboard/` | The nurse dashboard (Vite, React, TypeScript, Motion) |
| `dashboard/src/data/` | View model, wire adapter, live store |
| `simulator/` | Stand-in care home that feeds the backend over its API (Python, `uv`) |
| `scripts/` | `dev.sh mock` and `dev.sh empty` start the whole stack |
| `artifacts/` | Static HTML and CSS plan, research and overview, no build step |
| `docs/plan/` | Markdown and PDF exports of the project, research and extra ideas |
| `docs/architecture/` | Backend architecture, module map, decisions, testing, status |
| `backend/` | Python backend (`uv`): call state, dispatch, memory recall, staff alerts |
| `contracts/` | Frontend contract: OpenAPI spec plus real example payloads |
| `spacetimedb/` | SpacetimeDB module |
| `AGENTS.md` | Commands and rules for AI agents and new contributors |
| `CLAUDE.md` | Working rules and design rules for contributors and AI assistants |

### Plan and research documents

The original plan, research and extra ideas live in `docs/plan/`, with polished HTML versions in `artifacts/`. The previous README, which indexes them, is kept as [artifacts/docs-index.md](artifacts/docs-index.md). Start with [01-project.md](docs/plan/01-project.md) for the plan or open [artifacts/index.html](artifacts/index.html) in a browser for the polished overview.

## Current status

- **Done:** nurse dashboard on the live backend (REST plus SSE, actions, review queue, staff notes, empty and offline states), the simulator, memory learning from finished calls, staff medical history, note tidy route.
- **Verified:** dashboard and simulator run against the real backend in a browser, in both environments. The unit and integration suites for all three are green.
- **Not verified:** nothing has run with the real robot on the Pi. The rule-based note tidy and fact extractor are the defaults; the Claude versions need `ANTHROPIC_API_KEY` and have not been measured.
- **Elsewhere in the project:** the backend, contracts and SpacetimeDB module are in this repo (see below); the robot code and voice loop are owned by other teammates.
