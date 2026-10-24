# Bellhop simulator

A stand-in for the care home. It is a separate service that feeds the Bellhop backend through the backend's public HTTP routes, exactly as the real robot and staff would, so the dashboard (which only reads the backend) cannot tell it from a real home.

```text
simulator  --HTTP-->  backend  --HTTP + SSE-->  dashboard
```

It has two jobs:

- **seed** an empty backend with a fictional home: three nurses, three robots, twelve residents (what Bellhop has learned about each with its quote and how often it was heard, a nurse review queue, medical history, seven days of mood and pain readings) and fourteen days of past calls with full conversations, patterned per resident so the dashboard finds real tendencies.
- **run** the live part: ring bells at random, and play the robot for each one: `in-visit`, the conversation turns, `score`, wait for a nurse to acknowledge when the level needs one, `resolve`. Robots report status and battery every two seconds and go to charge when low. All residents and conversations are fictional.

Two things done from outside are followed too: a call rung through the API (for example `POST /calls`) that the backend gives to one of the simulator's robots is played as a visit, and a robot driven or stopped from the dashboard's Dispatch tab (`/navigate`, `/stop`) stays busy for ten seconds, or until stopped.

Because the conversations reach the backend as real turns, the backend's own learning (`MemoryLearner`) runs on them when a call resolves.

## Run it

Everything together, from the repo root: `scripts/dev.sh mock` (see the root README). Or by hand, with a backend already running on port 8000:

```bash
cd simulator && uv sync
uv run bellhop-sim seed                      # staff, robots, residents, history. Safe to repeat
uv run bellhop-sim run --seed-home           # seed if needed, then ring bells until Ctrl+C
uv run bellhop-sim run --scene busy          # start with an emergency, nurse calls and a chat
uv run bellhop-sim bell 104 --category fall  # ring one bell and play that visit
```

Start the backend with no data of its own so the simulator is the only source:

```bash
cd backend && BELLHOP_SEED_FILE=scenarios/empty.json uv run uvicorn bellhop.api.main:app --port 8000
```

| Option | Default | What it does |
| --- | --- | --- |
| `--base-url` / `BELLHOP_API` | `http://127.0.0.1:8000` | Which backend |
| `--api-key` / `BELLHOP_API_KEY` | none | Sent as `X-API-Key` |
| `--rate` | 1.5 | Bell presses per minute (0 for none) |
| `--speed` | 1 | 1 is realistic (a visit takes about a minute), 5 is five times faster |
| `--scene` | none | `busy`, `emergency` or `quiet` |
| `--nurse-delay` | 240 | Seconds before a nurse acknowledges a call that needs one. `0` leaves it to whoever uses the dashboard |
| `--random-seed` | random | Repeat the same run |

With a long `--nurse-delay` the calls that need a nurse stay open until someone presses "I'm on my way" on the dashboard, which is how to demo it. A bell with no free robot is taken by a nurse after the same delay.

## What it uses

| Route | For |
| --- | --- |
| `POST /nurses`, `PUT /robots/{id}`, `POST /residents`, `PUT /residents/{id}/preferences` | the home |
| `POST /residents/{id}/memory` (with `quote`, `source`, `confidence`, `at`) | what Bellhop has learned; low confidence facts land in the review queue |
| `PUT /residents/{id}/medical`, `POST /residents/{id}/care` (with `at`) | medical history and mood and pain readings |
| `POST /calls/import` | finished calls from the past, with their own times; raises no alerts |
| `POST /calls`, `/calls/{id}/in-visit`, `/turns`, `/score`, `/resolve`, `GET /alerts`, `POST /alerts/{id}/ack` | a live visit |

## Data

`data/residents.json`, `scenarios.json` and `patterns.json` are the fictional home: residents with their facts and medical history, ten conversation scripts (chat, tea, blanket, bathroom, confusion, hip pain, missed medication, chest tightness, fall, breathing) and the per-resident call patterns. Edit them to change the home.

## Tests

```bash
cd simulator && uv run pytest        # unit tests, plus the simulator against the real backend on a free port
uv run ruff check src tests && uv run ruff format --check src tests
```
