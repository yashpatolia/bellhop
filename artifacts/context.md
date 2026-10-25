# artifacts/context.md: read this first

Single-file handoff for any agent or teammate who starts with no chat history. Snapshot: 2026-10-24. Deeper docs: [AGENTS.md](../AGENTS.md) (rules and commands), [architecture/README.md](architecture/README.md) (index), [11-status.md](architecture/11-status.md) (checklist).

## 1. Product and team
**Bellhop**: a care-home robot that answers the call bell, talks with the resident, triages urgency and escalates to a nurse only when needed. Prototype for CalHacks; no real patient data, no diagnosis, lean toward escalation.

| Person | Lane |
| --- | --- |
| Aditya (the user) | Backend, database, RAG/memory, data, contracts |
| Yash | Frontend nurse dashboard (`frontend/`), integration |
| Gordon | ML: triage, voice, vision (`origin/ml`). Gordon said they could not finish it, so **the team now owns it and has autonomy** to rework it |
| Jeremy | Hardware, Raspberry Pi robot server |

## 2. Repo and branches
Repo `yashpatolia/calhacks-13`. Push over SSH: `git push git@github.com:yashpatolia/calhacks-13.git backend:backend` (HTTPS has no credentials).
- `master`: has everything merged (backend, contracts, SpacetimeDB module, dashboard, simulator, robot code). Work happens on short branches and goes in by pull request.
- `origin/ml` is Gordon's original work; `ml-work` (merged) is where it was finished. `origin/dashboard` and `origin/backend` are old and merged.
- Rules: commit/push only when the user says so; never push to `master` without being told; **no AI attribution in commits or repo files** (no Co-Authored-By trailer).

Layout: `backend/` (Python), `frontend/` (Vite/React), `contracts/` (openapi + examples), `spacetimedb/` (TypeScript module), `simulator/`, `ml/`, and `artifacts/` (all docs: `architecture/`, `plan/`, `components/`, static HTML), `tools/` (git-ignored local Node tooling).

## 3. Backend (done, verified)
Hexagonal: `domain` <- `ports` <- `services` <- `adapters`/`api` <- `container.py` (only place concrete classes are wired). TDD, `uv`, `backend/.venv`.
- **Verified 2026-10-24:** `cd backend && .venv/bin/python -m pytest -p no:warnings; echo EXIT=$?` gives 1039 passed, 1 skipped, EXIT=0 (about 60 s); after the 2026-10-24 robot-failure fixes (section 5) it is 1069 passed, 1 skipped, EXIT=0 via `uv run pytest -p no:warnings`. `ruff check` clean. (`-q` is in the pytest config, so use the exit code.)
- Flow: bell press -> call -> dispatch (robot first, nurse fallback if `go_to` fails) -> robot visit -> `/score` triage -> alerts -> resolve; memory recall, care signals (pain streak, mood, hydration, 4 flag types), visit notes, family postcard, memory guard, preferences, reminiscence feed, analytics, admin CRUD for residents/nurses, scenario loader, live SSE `GET /events`.
- Domain rules: states `RINGING -> ASSIGNED -> ROBOT_EN_ROUTE -> IN_VISIT -> RESOLVED -> CLOSED` plus `ESCALATED -> NURSE_ACKED`. Urgency 1 chat, 2 routine, 3 nurse soon, 4 emergency. Score only ratchets up; urgency >= 3 escalates; scores on resolved calls are ignored. `TriageGuard`: keyword floor (weak backstop, 11/24 to 20/24 on fresh phrasing), confidence < 0.6 bumps one level, model failure defaults to 3.
- Config via env (`backend/.env.example`): `BELLHOP_API_KEY` (header `X-API-Key`; `/events` also takes `?api_key=`), `BELLHOP_CORS_ORIGINS`, `BELLHOP_SEED_DEMO=1`, `BELLHOP_STORE=memory|spacetimedb`, `BELLHOP_MEMORY=local|moss`, `BELLHOP_CONTENT=local|wikipedia|apify`, `BELLHOP_ROBOT_URL`, `MOSS_*`, `APIFY_TOKEN`. Secrets only in env or git-ignored `.env`.
- Run: `cd backend && BELLHOP_SEED_DEMO=1 uv run uvicorn bellhop.api.main:app --host 0.0.0.0 --port 8000`; demo scenes: `uv run python scripts/demo_scenes.py`.
- Contract: `contracts/openapi.json` + `contracts/examples/*.json`, drift-tested. Regenerate with `cd backend && .venv/bin/python scripts/export_contract.py`.
- Verified live: SpacetimeDB module on a local 2.13.0 server (write-through store). **Never run with real services:** Moss (guessed SDK, falls back to local), Fetch.ai agent (`uagents` not installed), Apify adapter (CLI run only), `HttpRobotGateway` (no Pi yet).
- Room ids (decision): 12 = Margaret, 14 = Arthur, lobby = robot home. The user was to send this to Jeremy; confirm it was received.

## 4. Frontend (`frontend/`, Yash) and the simulator (`simulator/`)
Vite 8, React 19, TypeScript 6, `motion`, vitest; hash views `#/` Live, `#/insights`, `#/residents`, `#/residents/<id>`, `#/residents/<id>/<callId>`. The dashboard has **no mock data**: it reads the backend only (`VITE_BELLHOP_API_URL`, default `http://127.0.0.1:8000`, optional `VITE_BELLHOP_API_KEY`). `src/api/schema.d.ts` is generated from `contracts/openapi.json` (`npm run gen:api`); `src/data/adapt.ts` maps wire to view model and is tested against `contracts/examples`; `src/data/store.ts` does REST, SSE, polling and the actions (acknowledge alert, resolve, approve or reject pending facts, tidy and save staff notes). It shows "Cannot reach Bellhop" when offline and "This home is empty" for an empty backend.
- `simulator/` is a separate Python service (`uv run bellhop-sim seed|run|bell`) that plays the care home through the backend's public routes: it seeds staff, robots, twelve residents (facts with provenance, review queue, medical history, mood and pain), fourteen days of imported calls, then rings bells and acts as the robot. Fictional data only, in `simulator/data/*.json`.
- Run everything: `scripts/dev.sh mock` (backend + simulator + dashboard) or `scripts/dev.sh empty` (backend + dashboard). See `artifacts/architecture/16-simulator-and-environments.md`.
- Verified 2026-10-24: both environments in a browser, the live actions against the real backend, `npm run test` (adapter and store), `simulator` pytest against the real backend, backend suite.
- Backend routes added for this: provenance fields on memory facts, `GET /residents/{id}/memory/all`, `POST /calls/import`, care `at` and `GET .../care/history`, `GET/PUT .../medical`, `POST .../medical/entries`, `POST .../notes/refine`, `Call.resolved_by_robot`.
- Not done: login for staff, a UI to add residents (use the API), persistence of memory facts, care data and medical history in SpacetimeDB.

## 5. ML (`origin/ml`, Gordon, unfinished, ours to finish)
Code under `ml/pi/src/rover/`: `vision/` (Picamera2, YOLO NCNN, YuNet faces, ArUco markers, UDP to :5005/:5006), `speech/` (VAD, Deepgram Flux STT with Moonshine offline fallback, Piper TTS, visit state machine), `agent/` (Claude replies, persona, tools: look, request_staff, stop, go_to_room, follow_patient, face_patient), `triage/` (Claude Haiku + optional "Jev" via TypeSafe, merged by taking the higher urgency, 3 s budget), `backend.py` client, `config.py`. 94 pure-logic tests in `ml/tests` (not run by us yet). Env names: `DEEPGRAM_API_KEY`, `ANTHROPIC_API_KEY`, `TYPESAFE_API_KEY` (optional), `BELLHOP_API`, `BELLHOP_API_KEY`, `ROBOT_ID`, `PI_SERVER_URL`, audio device names.
- Contract check: its calls to `/calls`, `/in-visit`, `/turns`, `/score` (with `confidence`), `/triage-failed`, `/resolve`, `PUT /robots/{id}`, residents/preferences/speech-settings/memory all match our openapi. Same urgency scale as the backend; Jev-only results are forced to confidence 0.5 so the guard bumps up.
- **Status 2026-10-24.** Work lives in worktree `/home/aditya/CalHacks/calhacks-ml`, local branch `ml-work` (from `origin/ml`). **Uncommitted and not pushed.** Local-only secrets: `ml/dev/.env` (git-ignored) holds `APIFY_TOKEN` and `ANTHROPIC_API_KEY`; both were pasted in chat, rotate them after the hackathon.
- **Verified by running myself (2026-10-24):** in `ml/pi`, `uv run pytest` 349 passed EXIT=0; `uv run ruff check . ../dev ../tests` and `ruff format --check . ../dev ../tests` clean (plain `ruff check .` only covers `pi/`); no em or en dashes; the e2e harness `uv run python ../dev/e2e/run.py` (real backend from this repo plus fake Pi, about 100 s) gave 148 PASS, 0 FAIL, 0 known backend bugs on 3 runs in a row; backend `1069 passed, 1 skipped`, ruff clean, `contracts/` untouched. Schemathesis fuzz of the drive server clean (reported by the builder, not re-run by me).
- **Built:**
  - Lazy `sounddevice` import (the PortAudio collection failure is gone).
  - `rover.drive`: stdlib HTTP server, `POST /go_to` (202, background drive, authorized for 60 s), `/led`, `/stop`, `/follow`, `/face` (mode flag only), `GET /snapshot` (adds power and Wi-Fi RSSI), 5 s watchdog for follow/face, markers 201=12, 202=14, 203=lobby, `python -m rover.drive --fake`, motors off on SIGTERM/SIGINT/SIGHUP, LED returns to idle after 120 s without a live visit.
  - `rover/status.py` heartbeat every 5 s (`PUT /robots/{id}`; undervoltage reports `fault`); `rover/power.py`, `rover/safety.py`, `rover/obslog.py` (JSONL log via `ROVER_LOG`), `speech/textmode.py` (`--script`, no mic), `speech/ledguard.py`.
  - Visit loop polls `/snapshot` for arrival and retries `resolve` 4 times (a failed resolve used to leave the call open and the robot busy).
  - Triage: 6 s budget, one Claude retry, `/triage-failed` as last resort, Jev optional and raise-only.
  - Tools: `dev/e2e/` (end-to-end harness, fault-injection proxy, `scenario_backend_dies.py`, Schemathesis fuzz), `dev/tail.py` (merge and filter logs), `pi/scripts/doctor.py`, `pi/scripts/smoke.sh`, `pi/deploy/` (systemd units, `push.sh`, safe-stop checklist), `dev/eval_triage.py` (defaults to `GET /labelled-examples` plus `hard_cases.jsonl`, `--mock`).
  - Backend fixes found by the harness: failed robot `go_to` now always assigns a nurse and pages them (`RobotUnreachable` event), best-effort `/stop` after a failed `go_to` plus one delayed re-stop, `ROBOT_EN_ROUTE` is now set, an in-visit after escalation is accepted (200) without changing status. Docs updated (`01-module-map`, `09-hardware-interface`, `11-status`).
- **Local triage scorer (`triage/local.py`, bge-small embeddings plus a 6.5 KB head), OFF by default (`LOCAL_TRIAGE=1`).** Eval on 156 held-out rows (`uv run python ../dev/train/evaluate.py --claude`): missed urgent cases floor 34, local 11, Claude alone 3, Claude+floor 3, Claude+floor+local 2; false alarms 2%, 17%, 8%, 10%, 25%. Verdict: Claude already catches almost everything, adding local triples false alarms, so it stays off and is only an offline fallback. Caveats: labels came from one labeller (a coding agent), a human should review `dev/train/data/labels/verify.txt`; 3 Claude calls timed out in the run; about 60 synthetic lines share templates with some eval cases. Data: public Reddit text via Apify (`trudax/reddit-scraper-lite`, 440 posts, spend about $2.3) plus Hugging Face empathetic dialogues; usernames and URLs stripped.
- **Not verified (no hardware yet):** `RealCar`, camera, markers, mic and speaker, ADC battery, real Pi power and Wi-Fi readings; real marker navigation (the navigator is a timed simulation with an ultrasonic stop); the systemd units and `push.sh` on a Pi; `HttpRobotGateway` against a real Pi; live Deepgram and Piper; the Wi-Fi power-save commands; 5 s to 60 s drive authorization on a real car; Pi 5 latency of the local scorer.
- **Pi bring-up findings (2026-10-24, via Raspberry Pi Connect):** Pi hostname `raspberrypi`, user `pi`, LAN `10.0.16.21`, Tailscale `100.73.9.29` on Gordon's tailnet (our laptop is not on it, and the WSL shell cannot reach the LAN). `throttled=0x0`, camera `imx708` detected, Wi-Fi "Cal Hacks 13.0" 5 GHz -62 dBm, 48 GB free, **only 2 GB RAM**, **Python 3.13.5 (Trixie), not Bookworm 3.11**, `uv` not installed, **no USB mic or speaker detected** yet (`arecord -l` empty, `aplay -l` HDMI only). `setup_pi.sh` stops on non-3.11. A resolver check says all heavy deps resolve for 3.13 aarch64 if numpy 2 is allowed (fastembed needs numpy >= 2.1), but that is untested on the Pi; fallback is reflashing Bookworm.
- **Hardware report from the user (not verified by me):** vision was tested on the Pi and worked. Details (which code, which markers, what distance, FPS) not yet recorded.
- **Known remaining gaps:** `POST /calls` still blocks about 2 s while a failing `go_to` times out (async dispatch judged too large; see `11-status.md`); the delayed re-stop is a heuristic and can cut a legitimate drive short (real fix: Pi rejects stale `go_to`); `artifacts/components/contracts.md` still calls `robot_en_route` optional (Yash's file); marker map and room ids still to confirm with Jeremy; 2 GB RAM may not fit vision, speech and Moonshine together; GPL/AGPL/non-commercial voice licences (fine for a hackathon only).
- **Ranked plan now:** (1) get the code onto the Pi (needs a pushed `ml-work` branch, not yet authorized) and decide Python 3.13 vs Bookworm reflash; (2) plug in USB mic and speaker, run `scripts/doctor.py`, then a lifted-wheel motor test with `python -m rover.drive` (no `--fake`) and the safe-stop checklist in `artifacts/components/robot-safe-stop.md`; (3) real marker navigation (replace `SimNavigator`) and camera/ArUco checks at demo distance; (4) live speech run with Deepgram and Piper; (5) human review of triage labels, then decide whether the local scorer ever goes on; (6) systemd units and Tailscale access for us.

## 6. Open items, ranked
1. ML-to-backend end-to-end run on the Pi (section 5). The dashboard live mode is done (section 4).
2. (done) The robot code is merged into master through `ml-work`; run its tests in `ml/pi` (`uv run pytest`).
3. Jeremy: Pi server (`/go_to`, `/led`, `/stop`, `/snapshot`), room ids, marker map, battery.
4. Dev tooling quick wins from [12-research-dev-tooling.md](architecture/12-research-dev-tooling.md): import-linter (fixes 4 layering violations), Schemathesis, vulture, pytest-xdist + coverage floor, openapi-typescript/Prism for the frontend.
5. Deploy plan (Tailscale, Pi watchdog, SSE) in [14-research-deploy-and-connectivity.md](architecture/14-research-deploy-and-connectivity.md); set `BELLHOP_API_KEY` and narrow CORS for the demo.
6. Deferred cleanup: simplify over-engineered guards (GuardedNotifier, GuardedRobotGateway, SerializedSubscriptions, CompositeNotifier), SpacetimeDB writes to a background worker.
7. Triage stretch: embedding floor (fastembed, raise-only), see [13-research-policy-and-triage.md](architecture/13-research-policy-and-triage.md).
8. User-side: `uv sync --extra fetch` to try the Fetch.ai agent; Moss project id/key (optional); `APIFY_TOKEN` in `backend/.env` (optional).

## 7. Working rules (do not break)
- TDD; record a bug as a strict xfail first; verify every builder/agent claim by re-running the suite and reading the diff.
- Isolation: Python only via `backend/.venv` and `uv` (never system pip); Node only project-local (never `npm install -g`); secrets never in chat, code or commits.
- CodeGraph index in `.codegraph/` (git-ignored). Refresh `codegraph sync`, or full `codegraph index` if stale. In the main session use only search/callers/callees/impact/node; delegate exploration to agents.
- One owner per shared file (`container.py`, `api/app.py`, `contracts/`). Update docs in the same change.
- Tooling quirks: the shell hook blocks `curl`/`wget`/WebFetch (user can run `!` commands); don't work around hooks.

## 8. Repo-level rules from CLAUDE.md (dashboard and docs)
- Never use em dashes or en dashes in code, copy, comments or docs.
- Dashboard: no mock data in the frontend (it reads the backend only, through `frontend/src/data/source.ts`; example data comes from `simulator/`); fill the full page width; readable and calm for nurses, urgency always shown in words as well as colour; no amber; theme tokens live in `frontend/src/theme/themes.css`.
