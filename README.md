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
8. [Theming and layouts](#theming-and-layouts)
9. [The mock simulator](#the-mock-simulator)
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

A call moves through a small state machine. The same statuses are used by the backend, the mock simulator and every dashboard layout (`dashboard/src/data/types.ts`).

```text
robot_en_route -> robot_with_resident -> resolved                  (urgency 1, robot handles it)
robot_en_route -> robot_with_resident -> nurse_notified -> resolved (urgency 2, task for aide or kitchen)
robot_en_route -> robot_with_resident -> nurse_notified -> nurse_en_route -> resolved   (urgency 3)
robot_en_route -> nurse_notified (immediately, robot stays) -> nurse_en_route -> resolved (urgency 4)
```

Urgency levels, always shown with words as well as colour:

| Level | Label | Who acts |
| --- | --- | --- |
| 1 | Robot resolving | Robot only. Chat, comfort. Never reaches a nurse. |
| 2 | Staff task | Robot creates a task for an aide or the kitchen. |
| 3 | Needs a nurse | Nurse gets a written SBAR summary. |
| 4 | Emergency | Alert fires immediately. Robot stays with the resident. |

Each call carries its own explanation: a one line `summary`, an SBAR block (Situation, Background, Assessment, Recommendation), the full transcript, the triage `confidence`, and the AI `costUsd` for that call. Nurses use SBAR in handovers, so the format is already familiar.

## The agents

Six agents, each with one job (full table in [01-project.md](artifacts/docs/01-project.md)):

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

`dashboard/` is Vite, React 19 and TypeScript, with Motion for animation. There is no router library and no state library.

```text
dashboard/src/
  App.tsx               source creation, hash routing, theme selection
  data/
    types.ts            Call, Robot, Resident, Snapshot, Actions (the contract)
    source.ts           THE seam: picks live or mock, exposes the React hooks
    live.ts             REST + SSE source for the real backend
    mock.ts             Simulator that fakes calls and robot movement
    layout.ts           24 room East Wing floor plan geometry
  lib.ts                labels, status text, KPI maths (shared by all layouts)
  components/           Screen, Header, FloorMap, Charts, CallParts
  views/                LiveView, InsightsView, ResidentsView, ThemesPage
  layouts/<theme>/      Layout.tsx + layout.css per theme (5 live)
  theme/                themes.css (tokens), themes.ts (metadata)
```

### The data seam

All data goes through `src/data/source.ts`. A source implements:

```ts
interface DataSource {
  subscribe: (fn: () => void) => () => void
  getSnapshot: () => Snapshot
  actions: { nurseOnMyWay(id): void; resolve(id): void }
  start: () => void
  stop: () => void
}
```

`useLiveData(source)` wires this into React with `useSyncExternalStore`, which gives tear-free reads and one subscription regardless of how many components render. `createSource()` returns the live source when `VITE_BELLHOP_API_URL` is set and the mock otherwise. No component knows which one it has.

Why this shape: the dashboard was built top down before the backend existed. Putting one interface between UI and data meant the whole interface could be designed and demoed on mock data, then the real source dropped in by changing one function. Swapping to SpacetimeDB, or anything else, would also touch only this folder.

### Views

Three views share the same data: **Live** (open calls, floor map, robots), **Insights** (KPIs, hourly chart, category mix, cost) and **Residents** (profile, mood and pain trends, AI cost per resident). Routing is a hash (`#/`, `#/insights`, `#/residents`, `#/themes`). A hash router needs no server config, which matters because the dashboard may be served from a laptop or a static host.

## Live data: SSE, REST and polling

`data/live.ts` implements the recovery-first pattern from the integration guide.

1. On `start()`, call `refreshAll()` (REST) to load calls and robots.
2. Then open exactly one `EventSource` on `/events`.
3. Each event upserts the **full object** by `id` into the snapshot and notifies subscribers.
4. On `onerror`, call `refreshAll()` again. `EventSource` reconnects by itself, so no new source is created.
5. A 5 second poll runs only while the stream is not `OPEN`.
6. `stop()` closes the stream and clears the timer, so React remounts do not leak connections.

Why SSE rather than WebSockets or pure polling:

- The traffic is one way (server to dashboard), so SSE is enough. It rides plain HTTP, reconnects automatically and needs no client library.
- Polling alone would feel laggy for urgency 4 alerts. SSE alone is not correct: the stream deliberately **does not replay** missed events, so after any reconnect the client must refetch. The combination gives low latency in the normal case and correctness after any outage.
- WebSockets would add two-way capability we do not use, plus more reconnect logic to write.

Normalisation: the mapper in `live.ts` accepts camelCase or snake_case and merges onto the previous object, because the backend payload shape was not yet checked in. It is the one place to tighten once the contract is final.

Fields the backend does not provide yet (residents, nurses, hourly buckets) stay on the mock base. The nurse action buttons are applied locally for now since no endpoint exists for them.

## Theming and layouts

Two separate mechanisms:

- **Theme tokens** (`theme/themes.css`): a theme is a block of CSS variables under `[data-theme='id']`: surfaces, ink levels, accent, four urgency colours, radii, fonts and background. Every component reads only tokens, so adding a palette needs no component changes.
- **Per-theme layouts** (`layouts/<id>/Layout.tsx`): a theme may also ship an entirely different arrangement. `layouts/registry.ts` auto-discovers them with `import.meta.glob`. A theme without a layout falls back to the shared `Screen`.

Current layouts, each with a distinct information model for the same data:

| Theme | Idea |
| --- | --- |
| Birch & Moss (default) | Shift board: four swim lanes by urgency |
| Harbor Fog | Floor map fills the screen with floating glass panels |
| Espresso Night | Dark radar: rooms on a ring, scan line, built for night shifts |
| Plum & Stone | Inbox and reading pane for calls |
| Ink & Rust | One large urgent call at a time, slim list of the rest |

Five more were prototyped and moved to `dashboard/_archived-layouts/`. `#/themes` renders every live layout side by side on a frozen snapshot (`useStaticData`) using a scaled, `aria-hidden` preview. The theme choice is stored in `localStorage` (guarded, since storage can be blocked) and can be forced with `?theme=`.

Design rules, from `CLAUDE.md`, that every theme follows:

- The audience is nurses and caretakers: large type, strong contrast, calm. Urgency is always words plus colour, never colour alone.
- Muted earthy palettes only. No amber. Body text and numbers stay highly legible even in themes with a serif accent.
- The page fills the full width. No narrow centred layouts, because the dashboard runs on a wall or desk monitor.

Tradeoff: per-theme layout files duplicate some structure (each is 400 to 500 lines plus CSS). We accepted that because the point was to explore genuinely different ways of presenting urgency, not recolour one layout. Shared logic (labels, status text, KPIs) lives in `lib.ts` and `components/` so the duplication is presentation only.

## The mock simulator

`data/mock.ts` is a self-contained fake of the whole system, used when no backend URL is set and for theme previews:

- Twelve residents with flags, likes, 7 day mood and pain.
- Nine scripted scenarios (chat, tea, blanket, bathroom, confusion, hip pain, missed medication, chest tightness, fall, breathing) each with a transcript and SBAR.
- A 1 second tick that spawns calls at random intervals, caps open calls at four, drives robots along corridor waypoints on the floor plan, advances calls through the state machine, and resolves them.
- Robots go home to the dock to charge when battery drops.
- `?demo=busy` seeds one emergency, two nurse calls, a task and a chat for layout checks.

It exists so the UI could be built, reviewed and rehearsed without hardware or network. It is also a living spec of the lifecycle above.

## Metrics and the savings claim

`computeKpis` in `lib.ts` derives everything shown on Insights from the call list: totals, resolved by robot, median first response, share answered within 10 minutes, AI cost per call and average resident feedback.

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
| Per-theme layouts plus shared tokens | Real exploration of how to present urgency while keeping logic shared | Duplicated presentation code across five layouts |
| Words as well as colour for urgency | Accessibility and readability under stress | Slightly busier chips |
| Assumption-labelled savings counter | Honest metric a judge can interrogate | A less dramatic headline number |

## Running it

Dashboard on mock data:

```bash
cd dashboard && npm install && npm run dev
```

Dashboard on the live backend:

1. Install Tailscale and join the team tailnet (ask Aditya for an invite).
2. Check the backend is reachable: `curl http://100.81.196.22:8000/health` should return `{"status":"ok"}`.
3. Copy `dashboard/.env.example` to `dashboard/.env.local` and set `VITE_BELLHOP_API_URL`. Add `VITE_BELLHOP_API_KEY` only if the backend uses a key.
4. Run `npm run dev`.

Other scripts: `npm run build` (typecheck and bundle), `npm run lint` (oxlint). Useful URLs: `/#/themes` to compare layouts, `/?theme=mocha` to force a theme, `/?demo=busy` for a busy mock floor.

Pre-demo checklist for live mode: health check passes, initial `/calls` loads, a pressed bell appears without refresh, a robot status change updates its card, toggling Tailscale off and on recovers via refetch, and the polling fallback visibly works with SSE unavailable.

## Repository map

| Path | What it is |
| --- | --- |
| `dashboard/` | The nurse dashboard (Vite, React, TypeScript, Motion) |
| `dashboard/src/data/` | Types, source seam, live and mock sources |
| `dashboard/src/layouts/` | One folder per live theme layout |
| `dashboard/_archived-layouts/` | Retired themes kept for reference |
| `artifacts/` | Static HTML and CSS plan, research and overview, no build step |
| `artifacts/docs/` | Markdown and PDF exports of the project, research and extra ideas |
| `CLAUDE.md` | Working rules and design rules for contributors and AI assistants |

### Plan and research documents

The original plan, research and extra ideas live in `artifacts/`. The previous README, which indexes them, is kept as [artifacts/docs-index.md](artifacts/docs-index.md). Start with [01-project.md](artifacts/docs/01-project.md) for the plan or open [artifacts/index.html](artifacts/index.html) in a browser for the polished overview.

## Current status

- **Done:** nurse dashboard with five distinct layouts, mock simulator, live REST plus SSE source, theme gallery.
- **Not yet verified:** the live source has not been run against the real backend (the Tailscale address was unreachable from the dev machine when written). The call and robot field mapping in `live.ts` is tolerant on purpose and should be checked against the first real payload.
- **Not wired:** nurse action buttons are local only; `/alerts` and `/metrics` are not shown; residents, nurses and hourly data still come from the mock base.
- **Elsewhere in the project:** the robot code, voice loop, agents and backend are owned by other teammates and are described here from the plan, not implemented in this repo.
