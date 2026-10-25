# Setup

How to set up every service Bellhop uses, from a fresh clone to a running demo. The README explains how the system works; this file is the checklist for getting it running.

Never commit a key or token. Put values in git-ignored `.env` files or in your shell, and rotate any key that was ever pasted into chat.

## 1. What you are setting up

| Service | What it is | Needed? | Section |
| --- | --- | --- | --- |
| Backend | The HTTP API that holds calls, residents, memory and alerts | Yes | [3](#3-backend) |
| Dashboard | The nurse web app | Yes | [4](#4-dashboard) |
| Simulator | Example residents and a fake robot, for demos without hardware | Optional | [5](#5-simulator-and-the-two-environments) |
| SpacetimeDB | Database so data survives a backend restart | Optional (recommended for a demo) | [6](#6-spacetimedb-persistence) |
| Anthropic (Claude) | Learns facts from conversations, tidies staff notes, writes the robot's replies | Optional on the backend, required on the robot | [7](#7-claude-anthropic) |
| Moss | Semantic memory search | Optional | [8](#8-moss-memory-search) |
| Apify or Wikipedia | Era-appropriate reminiscence content | Optional | [9](#9-reminiscence-content-wikipedia-or-apify) |
| Fetch.ai agent | "Ask Bellhop" from ASI:One | Optional | [10](#10-fetchai-agent) |
| Robot (Raspberry Pi) | Driving, camera, voice | For the real robot | [11](#11-the-robot-raspberry-pi) |
| Deepgram | Speech to text on the robot | For the real robot | [11](#11-the-robot-raspberry-pi) |
| Tailscale | Private network between laptop, Pi and dashboard machines | For the real robot | [12](#12-network-tailscale) |

With nothing but section 2 you get a working demo on one machine: backend, simulator and dashboard, no keys, no hardware.

## 2. Prerequisites and the fast path

Install once:

| Tool | Version | Install |
| --- | --- | --- |
| git | any | with GitHub SSH access to `yashpatolia/calhacks-13` |
| uv | recent | `curl -LsSf https://astral.sh/uv/install.sh \| sh` or `brew install uv`. It installs Python for you |
| Node.js and npm | 22 | `brew install node@22`, or <https://nodejs.org> |

Then, from the repo root:

```bash
git clone git@github.com:yashpatolia/calhacks-13.git && cd calhacks-13
(cd frontend && npm install)
scripts/dev.sh mock      # backend + simulator + dashboard with example data
```

Open <http://localhost:5173>. Use `scripts/dev.sh empty` instead for a backend and dashboard with nothing in the home (for the real robot, or to add residents yourself on the Residents tab). Ctrl+C stops everything. See [section 5](#5-simulator-and-the-two-environments) for options.

## 3. Backend

Python 3.12 or newer, managed by `uv`.

```bash
cd backend
uv sync                                   # add --extra claude, --extra moss or --extra fetch as needed
cp .env.example .env                      # then fill in what you use; names are listed below
BELLHOP_SEED_FILE=scenarios/empty.json uv run uvicorn bellhop.api.main:app --host 0.0.0.0 --port 8000
```

`uv run` does not read `.env` by itself. Either `export` the variables in your shell, or run `set -a; source .env; set +a` first. `--host 0.0.0.0` lets the dashboard and Pi on other machines reach it; use `127.0.0.1` for a single machine.

Check it: `curl http://127.0.0.1:8000/health` returns `{"status":"ok"}`, and <http://127.0.0.1:8000/docs> shows every route.

Starting data (pick one):

| Setting | Result |
| --- | --- |
| `BELLHOP_SEED_FILE=scenarios/empty.json` | Nothing in the home. Add residents on the dashboard, nurses and robots through the API |
| `BELLHOP_SEED_DEMO=1` | The small demo home (Margaret in room 12, Arthur in 14, two nurses, one robot) |
| `BELLHOP_SEED_FILE=path/to/home.json` | Your own home, format in `artifacts/components/backend-scenarios.md` |

Add a nurse and a robot by hand (the dashboard's "I'm on my way" needs a nurse on shift):

```bash
curl -X POST localhost:8000/nurses -H 'Content-Type: application/json' -d '{"id":"nurse_ines","name":"Ines"}'
curl -X PUT  localhost:8000/robots/robot_1 -H 'Content-Type: application/json' -d '{"status":"idle","battery":0.9,"room":"dock"}'
```

### All backend settings

Read from the environment at startup (`backend/src/bellhop/container.py`).

| Variable | Default | Meaning |
| --- | --- | --- |
| `BELLHOP_SEED_FILE` | unset | Scenario JSON to load; wins over `BELLHOP_SEED_DEMO` |
| `BELLHOP_SEED_DEMO` | unset | `1` loads the demo home |
| `BELLHOP_STORE` | `memory` | `memory` or `spacetimedb` ([section 6](#6-spacetimedb-persistence)) |
| `BELLHOP_STDB_URL` | `http://127.0.0.1:3000` | SpacetimeDB address |
| `BELLHOP_STDB_DB` | `bellhop` | SpacetimeDB database name |
| `BELLHOP_STDB_TOKEN` | unset | SpacetimeDB token (hosted only) |
| `BELLHOP_MEMORY` | `local` | `local` or `moss` ([section 8](#8-moss-memory-search)) |
| `MOSS_PROJECT_ID`, `MOSS_PROJECT_KEY` | unset | Moss credentials |
| `BELLHOP_LEARNING` | `rule` | How facts are learned from conversations: `rule` (offline) or `claude` ([section 7](#7-claude-anthropic)) |
| `BELLHOP_EXTRACTOR_MODEL` | `claude-opus-5-5` | Claude model for fact extraction |
| `BELLHOP_REFINER` | `rule` | How staff notes are tidied: `rule` or `claude` |
| `BELLHOP_REFINER_MODEL` | `claude-sonnet-5-5` | Claude model for the note tidy |
| `ANTHROPIC_API_KEY` | unset | Needed when either of the two above is `claude` |
| `BELLHOP_CONTENT` | `local` | Reminiscence content: `local`, `wikipedia` or `apify` ([section 9](#9-reminiscence-content-wikipedia-or-apify)) |
| `APIFY_TOKEN` | unset | Needed when `BELLHOP_CONTENT=apify` |
| `BELLHOP_ROBOT_URL` | unset | The robot's drive server, for example `http://<pi-tailscale-ip>:8080`. Unset means no robot is commanded (a recording stub is used) |
| `BELLHOP_API_KEY` | unset | When set, every route except `/health` needs the `X-API-Key` header. Unset means open |
| `BELLHOP_CORS_ORIGINS` | `*` | Comma-separated browser origins allowed, for example `http://localhost:5173` |
| `BELLHOP_ALLOW_NEW_ROBOTS` | `1` | `0` means only known robots may report in |
| `BELLHOP_GUARDS` | `1` | `0` turns off the timeouts around the robot, notifier and memory |

### Tests

```bash
uv run pytest && uv run ruff check src tests scripts && uv run ruff format --check src tests scripts
```

## 4. Dashboard

```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

The dashboard has no data of its own and reads only the backend. Set where it is with `frontend/.env.local` (git-ignored; `.env.example` shows the names):

| Variable | Default | Meaning |
| --- | --- | --- |
| `VITE_BELLHOP_API_URL` | `http://127.0.0.1:8000` | The backend address, no trailing slash. For another machine use its Tailscale address, for example `http://100.x.y.z:8000` |
| `VITE_BELLHOP_API_KEY` | unset | Only if the backend sets `BELLHOP_API_KEY`. It is compiled into the browser code, so use a key made for the dashboard alone |

Restart `npm run dev` after changing `.env.local`. Other commands: `npm run build` (typecheck and bundle into `dist/`), `npm run test`, `npm run lint`, `npm run gen:api` (regenerate the wire types after `contracts/openapi.json` changes).

If the screen says "Cannot reach Bellhop", the backend is down or the address is wrong; it retries every few seconds by itself.

## 5. Simulator and the two environments

The simulator is a separate Python service that feeds the backend over its API: three nurses, three robots, twelve residents (what Bellhop has learned, a review queue, medical history, mood and pain), fourteen days of past calls, then live bell presses with a fake robot that plays each visit. Fictional data only.

```bash
scripts/dev.sh mock       # the whole stack with the simulator
scripts/dev.sh empty      # backend and dashboard only
scripts/dev.sh demo       # the real (empty) backend on :8000, a demo backend on :8001 filled by the simulator
scripts/dev.sh mock --scene busy --rate 3 --speed 2     # options for the simulator
```

Or by hand, with a backend already running: `cd simulator && uv sync && uv run bellhop-sim run --seed-home`. Options (`--rate`, `--speed`, `--scene`, `--nurse-delay`) are in `artifacts/components/simulator.md`. The simulator needs the same `--base-url` and `--api-key` (or `BELLHOP_API` and `BELLHOP_API_KEY`) as the backend if you changed them.

`scripts/dev.sh empty` and `demo` start the real backend on SpacetimeDB by default, and print a warning and fall back to memory if the server is not running. `mock` and the demo backend always use memory, so made-up residents never reach the database. Starting uvicorn by hand still defaults to memory unless you export `BELLHOP_STORE=spacetimedb`.

In `demo` mode the dashboard shows a **Demo** button in the top bar. It switches the dashboard to the demo backend (`VITE_BELLHOP_DEMO_URL`, default `http://127.0.0.1:8001`), with a banner saying the data is made up. The demo backend is in memory and separate from the real one, so demo activity never reaches the real home or SpacetimeDB. If the demo backend is not running, the dashboard says so.

Seeding is safe to repeat. A restarted in-memory backend loses everything, so run the simulator again (`scripts/dev.sh` does).

## 6. SpacetimeDB (persistence)

Without it the backend keeps everything in memory and loses it on restart. With it, calls, residents, memory facts, the nurse review queue, care readings, flags, preferences, family notes and medical history survive a restart.

1. Install the CLI and start a local server (leave it running):

   ```bash
   curl -sSf https://install.spacetimedb.com | sh   # answer yes; downloads about 50 MB
   export PATH="$HOME/.local/bin:$PATH"             # the installer does not do this for you
   spacetime --version                              # confirms the install
   spacetime start                                  # http://127.0.0.1:3000
   ```

   To keep the PATH in new terminal tabs: `echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc`. If a command says `spacetime: command not found`, this is the cause. `spacetime start` runs in the foreground, so give it its own terminal tab. It does not restart by itself after a reboot.

   Or with Docker: `docker run --rm --pull always -p 3000:3000 clockworklabs/spacetime start`.

2. Publish the module (from the repo root):

   ```bash
   (cd spacetimedb && npm install && npx tsc --noEmit)
   spacetime publish bellhop --module-path spacetimedb --server local -y
   ```

   The first publish also logs the CLI in to the local server. The first publish onto a database made by an older version of the module needs `--delete-data`, which wipes its rows. Publish again after any change to `spacetimedb/src/index.ts`.

3. Start the backend against it, with the server from step 1 already running:

   ```bash
   export BELLHOP_STORE=spacetimedb
   export BELLHOP_STDB_URL=http://127.0.0.1:3000
   export BELLHOP_STDB_DB=bellhop
   cd backend && uv run uvicorn bellhop.api.main:app --port 8000
   ```

   If `BELLHOP_STORE` is not set in the shell that starts the backend, it silently uses memory.

4. Check: add a resident on the dashboard, restart the backend, and the resident is still there. `spacetime sql bellhop "SELECT * FROM resident" --server local` shows the rows. If you wipe the database with `--delete-data`, restart the backend and run `bellhop-sim seed` again, otherwise the running backend writes its old in-memory rows back.

   This was checked against a real local server (v2.13.0): residents, memory facts, the review queue, care readings, medical history and calls all came back after a backend restart.

If the server cannot be reached the backend logs a warning and falls back to memory. If the module is older than the backend (the memory and care tables are missing) it keeps working and logs that those tables are not persisted; publish the module again. Prefer a local server for the demo over the hosted Maincloud, which needs `spacetime login` and `BELLHOP_STDB_TOKEN`, so venue Wi-Fi is not in the loop.

## 7. Claude (Anthropic)

Used in three places, each with its own key location:

| Where | What | Key goes in |
| --- | --- | --- |
| Backend, fact learning | Reads a finished conversation and proposes facts to remember | the backend's environment |
| Backend, staff note tidy | Rewrites a note typed on the Residents tab | the backend's environment |
| Robot | Writes the spoken replies and scores urgency | the Pi's `.env` ([section 11](#11-the-robot-raspberry-pi)) |

Get a key at <https://console.anthropic.com>. For the backend:

```bash
cd backend && uv sync --extra claude          # installs the anthropic package
export ANTHROPIC_API_KEY=...
export BELLHOP_LEARNING=claude                 # learn facts with Claude instead of the offline rules
export BELLHOP_REFINER=claude                  # tidy staff notes with Claude (falls back to the rules on any failure)
# optional: BELLHOP_EXTRACTOR_MODEL=claude-sonnet-5-5   BELLHOP_REFINER_MODEL=claude-haiku-5-5
```

Choose the extraction model by measured accuracy, not price. Score it on the labelled conversations, offline rules first:

```bash
cd backend
uv run python -m bellhop.labelled.memory_eval --extractor rule
uv run python -m bellhop.labelled.memory_eval --extractor claude --model claude-opus-5-5
uv run python -m bellhop.labelled.memory_eval --extractor claude --model claude-sonnet-5-5
```

Without a key, leave both settings at `rule`: everything still works.

## 8. Moss (memory search)

Optional; the default `local` index needs nothing. For Moss: create a project at <https://portal.usemoss.dev> (ask for sponsor access at the event) and make an API key under API Keys (shown once). Then:

```bash
cd backend && uv sync --extra moss
export BELLHOP_MEMORY=moss MOSS_PROJECT_ID=... MOSS_PROJECT_KEY=...
```

Any Moss failure or slow answer falls back to the local index. This adapter has never run against the real service, so test a recall before relying on it.

## 9. Reminiscence content (Wikipedia or Apify)

`BELLHOP_CONTENT=local` (default) uses built-in era content. `wikipedia` needs no key, only internet access. `apify` needs a token from <https://console.apify.com> under Settings, API and Integrations: `export BELLHOP_CONTENT=apify APIFY_TOKEN=...`. Apify takes about 12 seconds a page, so it is used only when content is loaded ahead of time, never during a conversation.

## 10. Fetch.ai agent

Optional: ask "what happened in room 12?" from ASI:One. Needs an account at <https://agentverse.ai>.

```bash
cd backend && uv sync --extra fetch
export BELLHOP_AGENT_SEED="<a long secret phrase>"     # fixes the agent's address
# optional: BELLHOP_AGENT_PORT=8001   BELLHOP_AGENT_ALLOWED_SENDERS=agent1q...,agent1q...
uv run uvicorn bellhop.api.main:app --port 8000 &     # the agent reads from the backend
uv run python -m bellhop.fetchai
```

Open the Agent Inspector link printed at startup and connect the Mailbox once. This has never been run, so expect to fix something on the first try. Details: `artifacts/architecture/06-integrations.md`.

## 11. The robot (Raspberry Pi)

The Pi runs `rover.drive` (motors and a small HTTP server on port 8080), `rover.vision` (camera, people, door markers) and `rover.speech` (microphone, speech to text, Claude replies, voice). It talks to the backend only over HTTP. Full detail: `artifacts/components/ml.md` and `artifacts/components/robot-deploy.md`.

Hardware: Freenove 4WD car kit with a Raspberry Pi 5, Camera Module 3, a USB microphone and speaker, and a stable separate power supply for the Pi. Wiring and the safe-stop checklist are in `artifacts/components/robot-wiring.md` and `artifacts/components/robot-safe-stop.md`; do the checklist with the wheels off the ground before the first drive.

Keys:

| Key | Where from | Needed for |
| --- | --- | --- |
| `DEEPGRAM_API_KEY` | <https://console.deepgram.com> | speech to text (without it the robot falls back to the offline Moonshine model) |
| `ANTHROPIC_API_KEY` | <https://console.anthropic.com> | replies and triage |
| `TYPESAFE_API_KEY` | sponsor sandbox | optional advisory triage; leave empty to disable |

On the Mac, to try the voice code without hardware:

```bash
cd ml/pi && uv sync && cp .env.example .env     # fill in the keys
uv run python scripts/download_models.py        # vision, face, voice and offline speech models
uv run python scripts/smoke.py                  # expect: SMOKE OK
```

On the Pi (64-bit Raspberry Pi OS, Trixie or Bookworm, with SSH and internet), from the repo root on the Mac:

```bash
rsync -av --exclude .venv --exclude .python-version --exclude runs --exclude __pycache__ --exclude .env ml/pi/ pi@<pi-host>:~/ml/
ssh pi@<pi-host>
cd ~/ml && bash scripts/setup_pi.sh             # system packages, venv, dependencies, models, smoke test
```

Then edit `~/ml/.env` on the Pi (it is never copied from the Mac):

```bash
BELLHOP_API=http://<laptop-tailscale-ip>:8000    # the backend
BELLHOP_API_KEY=                                  # only if the backend sets one
ROBOT_ID=robot_1
PI_SERVER_URL=http://127.0.0.1:8080
MIC_NAME=<part of the USB mic name>               # from: uv run python -m sounddevice
SPEAKER_NAME=<part of the USB speaker name>       # the default is HDMI, so set this
BELLHOP_MARKER_ROOMS={"210":"12"}                 # physical marker id to the backend's room; {} if you use marker ids directly
DEEPGRAM_API_KEY=...
ANTHROPIC_API_KEY=...
```

Check each part, one at a time: `scripts/check_camera.py`, `scripts/check_level.py` (speech level), `scripts/check_marker.py --at 1.0` (marker distance), `scripts/doctor.py`. Printed markers use the `DICT_4X4_250` dictionary, 15 cm. A 2 GB Pi cannot run vision and speech together comfortably: watch `free -m` and add swap.

Run it (the backend laptop must be started with `--host 0.0.0.0`):

```bash
# on the laptop, point the backend at the robot
export BELLHOP_ROBOT_URL=http://<pi-tailscale-ip>:8080
# on the Pi
uv run python -m rover.drive            # motors and the server
uv run python -m rover.vision           # camera (one terminal each; see artifacts/components/ml.md for the 2 GB note)
uv run python -m rover.speech           # voice
```

To start them at boot instead, put the same variables in `/etc/bellhop/env` (mode 600) and install the systemd units from `ml/pi/deploy/` (steps in `artifacts/components/robot-deploy.md`).

Before any drive test, run the safe stationary conversation test in `artifacts/components/ml.md`: it exercises the whole voice path with the backend's `BELLHOP_ROBOT_URL` unset so nothing can drive.

Then open the dashboard: the robot should appear under Robots within seconds, and the Dispatch tab can drive it to a room.

## 12. Network (Tailscale)

Venue Wi-Fi often isolates devices, so use Tailscale between the laptop (backend), the Pi and any machine running the dashboard.

1. Make an account and install on each machine: `curl -fsSL https://tailscale.com/install.sh | sh` (Linux and the Pi), or the Mac app from <https://tailscale.com/download>.
2. Join the same tailnet: `sudo tailscale up` (the Pi) and sign in on the others.
3. Read each address with `tailscale ip -4`. Use the laptop's address for `BELLHOP_API` on the Pi and `VITE_BELLHOP_API_URL`, and the Pi's for `BELLHOP_ROBOT_URL`.
4. Check: `curl http://<laptop-tailscale-ip>:8000/health` from the Pi and from the dashboard machine.

Keep a phone hotspot as a backup network.

## 13. Securing a demo deployment

Do this before the backend is reachable by anyone but you:

```bash
export BELLHOP_API_KEY=<a long random string>
export BELLHOP_CORS_ORIGINS=http://<dashboard-host>:5173
```

Then set the same key as `BELLHOP_API_KEY` on the Pi and as `VITE_BELLHOP_API_KEY` for the dashboard (and `--api-key` for the simulator). The dashboard's live updates carry the key in the URL (`?api_key=`), so use a key made only for this, over a private network.

## 14. A full demo, start to finish

1. Laptop and Pi on Tailscale ([12](#12-network-tailscale)).
2. Laptop: SpacetimeDB running and the module published ([6](#6-spacetimedb-persistence)).
3. Laptop: backend with `BELLHOP_STORE=spacetimedb`, `BELLHOP_ROBOT_URL`, `BELLHOP_API_KEY`, `BELLHOP_CORS_ORIGINS`, and the Claude settings if you have a key ([3](#3-backend), [7](#7-claude-anthropic)).
4. Laptop: dashboard (`npm run dev`, or `npm run build` and serve `frontend/dist`).
5. Pi: `rover.drive`, `rover.vision`, `rover.speech` ([11](#11-the-robot-raspberry-pi)).
6. Dashboard: add residents and rooms on the Residents tab, and a nurse and the robot through the API.
7. Press a bell (`curl -X POST $API/calls -H 'Content-Type: application/json' -d '{"room":"12"}'`, or the bell button) and watch it on the Live tab.

## 15. When something is wrong

| What you see | Check |
| --- | --- |
| Dashboard says "Cannot reach Bellhop" | `curl <backend>/health`; `VITE_BELLHOP_API_URL`; backend started with `--host 0.0.0.0`; Tailscale up |
| 401 from the backend | `BELLHOP_API_KEY` is set on the backend, so every client needs the same key |
| Browser console shows a CORS error | `BELLHOP_CORS_ORIGINS` does not include the dashboard's address |
| "This home is empty" | Normal for `empty`; add residents on the Residents tab or run the simulator |
| "I'm on my way" does nothing useful | No nurse on shift: `POST /nurses` |
| `spacetime: command not found` | `~/.local/bin` is not on your PATH ([6](#6-spacetimedb-persistence)) |
| Data gone after restarting the backend | `BELLHOP_STORE` is `memory`, or SpacetimeDB was unreachable (look for a warning at startup) |
| Warning "module lacks the memory and care tables" | Publish `spacetimedb/` again ([6](#6-spacetimedb-persistence)) |
| `BELLHOP_LEARNING=claude` fails at startup or learning does nothing | `uv sync --extra claude` and `ANTHROPIC_API_KEY` |
| Robot does not appear on the dashboard | `BELLHOP_API` on the Pi; `ROBOT_ID`; the Pi can `curl <backend>/health` |
| Dashboard Drive or a bell does nothing on the robot | `BELLHOP_ROBOT_URL` on the backend; `rover.drive` running; `curl <pi>:8080/snapshot` |
| Robot cannot hear or speak | `MIC_NAME` and `SPEAKER_NAME`; `scripts/doctor.py`; the default speaker is HDMI |
| Port already in use | Another run is still going: stop it, or set `BACKEND_PORT` and `FRONTEND_PORT` for `scripts/dev.sh` |
