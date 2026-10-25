# Bellhop backend

Call state, dispatch, memory recall and staff alerts for the Bellhop care-home robot.

## Quick start

```
uv sync
BELLHOP_SEED_DEMO=1 uv run uvicorn bellhop.api.main:app --host 0.0.0.0 --port 8000
```

Seed data adds the demo resident (room 12) and her memories. Then, in a second terminal, play the demo:

```
uv run python scripts/demo_scenes.py                    # all three scenes, 2 s between steps
uv run python scripts/demo_scenes.py --scene 3 --pace 0 # one scene, no pauses
```

Options: `--base-url` (default `http://127.0.0.1:8000`), `--scene 1|2|3|all`, `--pace SECONDS`, `--room` (default 12). It exits non-zero if the server is unreachable or a step returns an unexpected status.

## Tests and lint

```
uv run pytest
uv run ruff check src tests
uv run ruff format src tests
```

## Configuration

Read from the environment by `Settings.from_env` in `src/bellhop/container.py`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `BELLHOP_MEMORY` | `local` | Memory backend: `local` or `moss` |
| `BELLHOP_STORE` | `memory` | Store: `memory` or `spacetimedb` |
| `BELLHOP_SEED_DEMO` | unset | `1` loads the demo resident and memories |
| `BELLHOP_STDB_URL` | `http://127.0.0.1:3000` | SpacetimeDB address |
| `BELLHOP_STDB_DB` | `bellhop` | SpacetimeDB database name |
| `BELLHOP_STDB_TOKEN` | unset | SpacetimeDB token |
| `MOSS_PROJECT_ID` | unset | Moss project id |
| `MOSS_PROJECT_KEY` | unset | Moss project key |
| `BELLHOP_GUARDS` | `1` | `0` disables timeout guards around adapters |
| `BELLHOP_ROBOT_URL` | unset | Robot HTTP gateway URL |
| `BELLHOP_CONTENT` | `local` | Reminiscence content: `local`, `wikipedia` or `apify` |
| `BELLHOP_LEARNING` | `rule` | How facts are learned from conversations: `rule` (offline baseline) or `claude` (needs `ANTHROPIC_API_KEY`) |
| `BELLHOP_EXTRACTOR_MODEL` | `claude-opus-5-5` | Claude model used by the `claude` extractor |
| `APIFY_TOKEN` | unset | Apify API token |
| `BELLHOP_API_KEY` | unset | Shared secret. When set, every route except `GET /health` needs `X-API-Key` (401 otherwise); `GET /events` also accepts `?api_key=` for browser EventSource. Unset = open (dev) |
| `BELLHOP_CORS_ORIGINS` | `*` | Comma-separated allowed browser origins, e.g. `http://localhost:5173`. Use the dashboard origin outside dev |
| `BELLHOP_ALLOW_NEW_ROBOTS` | `1` | `0` makes `PUT /robots/{id}` update known robots only (404 otherwise). Default lets the Pi self-register in the demo |

`BELLHOP_ROBOT_URL` and `BELLHOP_STDB_URL` must be `http://` or `https://` (build fails otherwise). Request bodies are capped at 1 MB (413) and string fields have length limits (422).

Keep secrets in env vars or a git-ignored `.env`, never in the repo.

## Layout

- `src/bellhop/domain/`: models, events and rules; no I/O.
- `src/bellhop/ports/`: interfaces the services depend on.
- `src/bellhop/services/`: call, dispatch, triage and analytics logic.
- `src/bellhop/adapters/` and `api/`: concrete integrations and the FastAPI app.
- `src/bellhop/container.py`: the only place concrete classes are wired.

## Further reading

- [../AGENTS.md](../../AGENTS.md): rules and commands for contributors
- [architecture/README.md](../architecture/README.md): architecture
- [contracts.md](contracts.md): API contract and examples
