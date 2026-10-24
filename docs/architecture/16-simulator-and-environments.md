# Simulator and environments

How the pieces connect when you run Bellhop on one machine, and how to get a home with example data or an empty one.

```text
simulator  --HTTP-->  backend  --HTTP + SSE-->  dashboard
(example home)        (:8000)                   (:5173)

robot (Pi) --HTTP-->  backend                    (the real thing, when it exists)
```

The dashboard reads only the backend. Whatever writes to the backend, the simulator or the robot and staff, the screens look the same. That is the point of the split (ADR-21).

## Two environments

| | `scripts/dev.sh mock` | `scripts/dev.sh empty` |
| --- | --- | --- |
| Backend | empty scenario, in memory | same |
| Simulator | seeds the example home, then rings bells and plays the robot | not started |
| Dashboard | shows the example home | shows "This home is empty" until something is added |
| For | building the UI, rehearsing a demo, trying the learning pipeline on real turns | wiring the real robot, entering residents by hand, checking the empty and offline states |

`scripts/dev.sh` passes extra arguments to the simulator in mock mode: `scripts/dev.sh mock --scene busy --rate 3 --speed 2`. Set `BELLHOP_API_KEY` in the environment of all three (and `VITE_BELLHOP_API_KEY` for the dashboard) to try with auth on.

## Adding a home by hand (empty environment)

```bash
curl -X POST localhost:8000/nurses     -H 'Content-Type: application/json' -d '{"id":"nurse_ines","name":"Ines"}'
curl -X POST localhost:8000/residents  -H 'Content-Type: application/json' -d '{"id":"res_ada","name":"Ada Reyes","room":"21","birth_year":1941,"risk_flags":["falls"]}'
curl -X PUT  localhost:8000/robots/robot_1 -H 'Content-Type: application/json' -d '{"status":"idle","battery":0.9,"room":"dock"}'
```

Or start the backend with a scenario file (`BELLHOP_SEED_FILE=my.json`, format in `backend/scenarios/README.md`). The dashboard needs at least one nurse on shift for "I'm on my way" to work.

## What the dashboard shows when something is wrong

| Situation | Screen |
| --- | --- |
| First load in progress | "Connecting to Bellhop..." |
| Backend unreachable or a request failed | "Cannot reach Bellhop at <address> (<reason>). Trying again." Retries every 3 s, recovers by itself |
| Backend up, no residents and no calls | "This home is empty..." with a pointer to the simulator |
| An action failed (for example a call was already resolved) | the backend's reason for 8 seconds |

## Where the example data lives

`simulator/data/*.json`: residents (facts with their quote, source, confidence and how often they were heard; medical history; seven days of mood and pain), ten conversation scripts and per-resident call patterns. Nothing in the dashboard or backend holds example data any more. Everything fictional; no real patient data.

## Contract checks

`cd dashboard && npm run gen:api` regenerates `src/api/schema.d.ts` from `contracts/openapi.json`. `src/data/adapt.test.ts` and `store.test.ts` run the wire adapter and the live store against `contracts/examples/*.json`, so a contract change that breaks the dashboard fails a test.
