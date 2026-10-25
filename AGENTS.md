# AGENTS.md

Entry point for any contributor or tooling. Read [artifacts/context.md](artifacts/context.md) for the full handoff, then this, then [artifacts/architecture/README.md](artifacts/architecture/README.md).

## What this repo is
Bellhop: a care-home robot that answers the call bell and escalates to a nurse only when needed.
Product plan: `artifacts/plan/01-project.md`. Static overview pages: `artifacts/`.
Current progress, gaps and handoffs: [artifacts/architecture/11-status.md](artifacts/architecture/11-status.md). Frontend API contract: [artifacts/components/contracts.md](artifacts/components/contracts.md).

## Layout
```
backend/src/bellhop/   domain, ports, services, adapters, api, fetchai, labelled, container.py
backend/tests/         unit/ and integration/ (mirror src)
backend/scripts/       demo_scenes.py, export_contract.py
contracts/             openapi.json + example payloads (drift-tested)
frontend/              nurse dashboard (Vite, React, TypeScript); reads the backend only
simulator/             bellhop-sim: plays a fictional home against the backend API
ml/                    the robot (Raspberry Pi): speech, vision, driving
spacetimedb/           TypeScript module for the optional SpacetimeDB store
scripts/dev.sh         runs backend, simulator and frontend together (mock or empty)
artifacts/             all documentation: setup.md, context.md, overview.md, architecture/, plan/, components/, HTML pages
tools/                 local Node tooling, git-ignored
.github/workflows/     backend.yml, frontend.yml, simulator.yml: lint, format check, tests
```

## Commands (run from `backend/`)
```
uv sync                                  # install
uv run pytest                            # all tests (must stay green; includes contract drift)
uv run pytest tests/unit                 # fast loop
uv run ruff check src tests scripts      # lint
uv run ruff format src tests scripts     # format
BELLHOP_SEED_DEMO=1 uv run uvicorn bellhop.api.main:app --port 8000   # run the API
uv run python scripts/demo_scenes.py     # play the three demo scenes against a running server
uv run python scripts/export_contract.py # regenerate contracts/ after an API change
```
Use `uv` for everything. Never `pip install`; add deps with `uv add [--dev] <pkg>`. CI (`.github/workflows/backend.yml`) runs lint, format check and `uv run pytest`.

## Exploring the code
This repo has a CodeGraph index (`.codegraph/`, git-ignored). Use it for exploration instead of grepping. Refresh with `codegraph sync`; if results look stale, run a full `codegraph index`.

## Environments (isolation rule)
Not Python-only: TypeScript/Node is fine where it fits (SpacetimeDB module, dashboard, tooling). Always isolate:
- Python: `backend/.venv` via `uv run`. Never install into system Python.
- Node: project-local `node_modules` (`npm install` inside `tools/`, `spacetimedb/`, etc.), run with `npx` or `node_modules/.bin`. Never `npm install -g`.
- Secrets: env vars or git-ignored `.env` files only; never in chat, code or commits.
- Unavoidable user-level CLIs (for example the `spacetime` binary) are documented with their install command in the relevant README.

## Non-negotiable rules
1. **TDD.** Write the failing test, watch it fail for the right reason, write minimal code, refactor.
2. **Dependency direction:** `domain` <- `ports` <- `services` <- `adapters`/`api` <- `container`.
   Services import only `domain` and `ports`. Adapters implement ports. Only `container.py` wires concrete classes.
3. **No I/O in `domain/`.** Time and ids come from the `Clock` and `IdGenerator` ports.
4. **One behaviour change = one test + one small diff.** No speculative abstractions (YAGNI).
5. **Lean toward escalation:** urgency never ratchets down (`Call.score`); uncertain triage is treated as more urgent.
6. **No diagnosis, no real patient data.** Prototype only.
7. Keep files small and single-purpose. Public behaviour is documented in `artifacts/architecture/`; update docs in the same change.

## Where things go
See [01-module-map.md](artifacts/architecture/01-module-map.md). To extend (new adapter, dispatch rule, alert channel) see [02-extension-guide.md](artifacts/architecture/02-extension-guide.md).
