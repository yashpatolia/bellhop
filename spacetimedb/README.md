# Bellhop SpacetimeDB module

TypeScript module (SpacetimeDB 2.x) holding Bellhop's state. Tables: `call`, `call_turn`,
`resident`, `nurse`, `robot`, `alert`, `visit`, `memory_fact` (all public). Reducers are
full-row upserts: `save_call`, `append_turn`, `save_resident`, `save_nurse`, `save_robot`,
`save_alert`, `save_visit`, `save_memory_fact`. Column order equals reducer argument order and
must match `backend/src/bellhop/adapters/spacetimedb_store.py` (`COLUMNS`).

Status: see "Verification status" at the bottom.

## Commands

```bash
# 1. Install the CLI (macOS/Linux/WSL), then confirm
curl -sSf https://install.spacetimedb.com | sh
spacetime version list

# 2. Local standalone server (default http://127.0.0.1:3000); leave running
spacetime start
#    or: docker run --rm --pull always -p 3000:3000 clockworklabs/spacetime start

# 3. Module dependencies (project-local, from this directory)
cd spacetimedb && npm install && npx tsc --noEmit

# 4. Publish as database "bellhop" to the local server (repeat to update)
spacetime login            # hosted Maincloud only; local server works with the default identity
spacetime publish bellhop --module-path . --server local
#    first publish of a changed schema may need: --delete-data (wipes rows)

# 5. Smoke test
spacetime call bellhop save_robot '["b1","idle",1.0,""]' --server local
spacetime sql bellhop "SELECT * FROM robot" --server local
spacetime logs bellhop --server local
```

Run the backend against it (token optional locally; never commit one):

```bash
export BELLHOP_STORE=spacetimedb
export BELLHOP_STDB_URL=http://127.0.0.1:3000
export BELLHOP_STDB_DB=bellhop
# export BELLHOP_STDB_TOKEN=...   # from `spacetime login` / POST /v1/identity
```

If the server is unreachable at startup the backend logs a warning and uses the in-memory store.

## Verification status

VERIFIED on 2026-10-23 against a real local server (CLI 2.13.0, `spacetime start`):
`npx tsc --noEmit` clean; `spacetime publish bellhop --module-path . --server local` built and
published; the Python `SpacetimeDBStore` wrote calls (with turns), residents, nurses, robots,
alerts and visits over HTTP with no token, and a second store hydrated them back equal.
Not exercised live: token-authenticated calls, Maincloud, the dashboard subscription client.
