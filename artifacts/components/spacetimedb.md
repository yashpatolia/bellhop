# Bellhop SpacetimeDB module

TypeScript module (SpacetimeDB 2.x) holding Bellhop's state (all tables public).

| Tables | Held by |
| --- | --- |
| `call`, `call_turn`, `resident`, `nurse`, `robot`, `alert`, `visit` | `spacetimedb_store.py` (`COLUMNS`) |
| `memory_fact`, `pending_fact`, `care_entry`, `flag`, `preferences`, `family_message`, `family_delivery`, `medical_record` | `spacetimedb_data.py` (`DATA_COLUMNS`) |

Reducers are full-row upserts (`save_<table>`, and `append_turn` for transcript lines) plus
`delete_memory_fact`, `delete_resident_memory` and `delete_pending_fact`. Column order equals
reducer argument order and must match the Python lists; `backend/tests/unit/test_stdb_module_sync.py`
reads this file and fails if they drift.

**After changing this module, publish it again.** A backend older or newer than the published
module keeps working: if the memory and care tables are missing it logs a warning and holds that data
in memory only, until the module is published. The change that added `resolved_by_robot` to `call`
and the memory and care tables needs `--delete-data` on the first publish onto an existing
database (it wipes the rows).

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
spacetime call bellhop save_robot '["b1","idle",1.0,"",""]' --server local
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
