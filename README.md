# Bellhop

An autonomous robot fleet that takes the non-urgent call bells off nurses' hands.

Most bell presses in a care home are not emergencies. They are a drink, a chat, a question or a small request, and each one still pulls a nurse away from residents who need hands. Bellhop sends a robot from the fleet to the room instead. It talks to the resident, handles what it can, and calls a nurse only when something is urgent, so nursing time goes to the people who need it. Built at Cal Hacks 13.0 ([Devpost](https://devpost.com/software/bellhop)).

## What it does

- **Offloads non-immediate tasks.** A robot from the fleet answers the bell, drives to the room, greets the resident by name, and listens.
- **Escalates what is urgent.** It scores each call for urgency and sends falls, pain and distress to a nurse right away, in words as well as colour.
- **Coordinates the fleet.** Calls go to the closest free robot, and a nurse can send any robot to any room by hand.
- **Remembers each resident.** It learns small facts from conversation, and a nurse approves the uncertain ones.
- **Keeps nurses in charge.** A live dashboard shows every call and robot, and the nurse can resolve a call at any point.

## How it fits together

```
robot fleet (Pi)  <-->  backend (FastAPI)  <-->  frontend (React)
 speech, vision,          calls, memory,           nurse dashboard
 driving                  triage, events
                              |
                      SpacetimeDB (optional)
```

| Folder | What is in it |
| --- | --- |
| [`backend/`](backend) | Python API: call lifecycle, triage, memory learning, live events |
| [`frontend/`](frontend) | The nurse dashboard (Vite, React, TypeScript) |
| [`ml/`](ml) | The robot: speech to text, text to speech, vision and driving on the Pi |
| [`simulator/`](simulator) | Plays a fictional care home so you can demo without hardware |
| [`spacetimedb/`](spacetimedb) | Optional database module so data survives a restart |
| [`contracts/`](contracts) | The API contract and example payloads |
| [`artifacts/`](artifacts) | All documentation, plan and research |

## Quick start

You need [`uv`](https://docs.astral.sh/uv/) and Node 22.

```bash
cd frontend && npm install && cd ..
scripts/dev.sh mock     # backend, simulator and dashboard with an example home
scripts/dev.sh empty    # the same with an empty home, for the real robot
scripts/dev.sh demo     # an empty real home, plus a Demo button that switches to an example one
```

Open http://localhost:5173.

## Documentation

All documentation lives in [`artifacts/`](artifacts).

- [Setup guide](artifacts/setup.md): every service, from a fresh clone to a demo
- [Engineering overview](artifacts/overview.md): architecture, call lifecycle, decisions
- [Architecture notes](artifacts/architecture/README.md): module map, testing, status
- [Project plan and research](artifacts/docs-index.md), with [polished pages](artifacts/index.html)
- [API contract](artifacts/components/contracts.md)
