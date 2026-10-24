# AGENTS.md

Entry point for any AI agent or new contributor. Read this, then `docs/architecture/README.md`.

## What this repo is
Bellhop: a care-home robot that answers the call bell and escalates to a nurse only when needed.
Product plan: `docs/plan/01-project.md`. Static overview pages: `artifacts/`.
The Python backend (call state, dispatch, memory recall, staff alerts) lives in `backend/`.

## Commands (run from `backend/`)
```
uv sync                      # install
uv run pytest                # all tests (must stay green)
uv run pytest tests/unit     # fast loop
uv run ruff check src tests  # lint
uv run ruff format src tests # format
```
Use `uv` for everything. Never `pip install`; add deps with `uv add [--dev] <pkg>`.

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
7. Keep files small and single-purpose. Public behaviour is documented in `docs/architecture/`; update docs in the same change.

## Where things go
See `docs/architecture/01-module-map.md`. To extend (new sponsor adapter, new dispatch rule, new alert channel) see `docs/architecture/02-extension-guide.md`.
