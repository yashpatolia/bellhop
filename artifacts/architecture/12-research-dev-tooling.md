# Dev tooling research: catch bugs earlier

Date 2026-10-23. Goal: less manual verification. Judged against "MVP, not over-engineered". Versions are from PyPI/npm on this date. Items marked MEASURED were run here with `uv run --no-sync --with <pkg>==<ver>` (ephemeral, no project file changed). Everything else is from docs only. The suite was being edited by others during the runs, so two unrelated tests failed intermittently.

## Baseline (measured)

| Fact | Value |
| --- | --- |
| Serial `pytest` | 34 s |
| `pytest -n auto` (16 cores) | 13 s |
| Coverage (`--cov=bellhop`) | 93 % (2992 stmts, 223 missed) |
| Frontend code in repo | none yet (contract only: `contracts/openapi.json`) |
| Already in dev group | pytest, pytest-asyncio, pytest-cov, hypothesis, ruff, httpx |

## Verdicts

| Tool | Verdict | Version (date) | Install | Setup | First command |
| --- | --- | --- | --- | --- | --- |
| import-linter | ADOPT NOW | 2.15 (2026-09-04) | `uv add --dev import-linter` | 10 min | `uv run lint-imports` |
| Schemathesis | ADOPT NOW | 4.32.4 (2026-10-22) | `uv add --dev schemathesis` | 15 min | `uv run pytest tests/integration/test_fuzz_contract.py` |
| vulture | ADOPT NOW | 2.16 (2026-03-25) | `uv add --dev vulture` | 5 min | `uv run vulture src --min-confidence 80` |
| pytest-xdist | ADOPT NOW | 3.8.0 (2025-07-01) | `uv add --dev pytest-xdist` | 2 min | `uv run pytest -n auto` |
| pre-commit | ADOPT NOW (thin) | 4.7.0 (2026-10-12) | `uv add --dev pre-commit` | 10 min | `uv run pre-commit install && uv run pre-commit run -a` |
| mypy | LATER (domain/ports/services only) | 2.4.0 (2026-10-01) | `uv add --dev mypy` | 20 min | `uv run mypy --strict src/bellhop/domain src/bellhop/ports src/bellhop/services` |
| pyright | SKIP (pick one checker; mypy fits uv/CI, pyright needs node wheel) | 1.1.414 (2026-09-10) | `uv add --dev pyright` | 15 min | `uv run pyright src` |
| pytest-cov threshold | LATER (already installed) | 7.1.0 | none | 2 min | `uv run pytest --cov=bellhop --cov-fail-under=90` |
| mutmut | LATER (run once on domain/services before demo) | 3.8.0 (2026-09-12) | `uv add --dev mutmut` | 30 min + run time | `uv run mutmut run` |
| cosmic-ray | SKIP (needs config and DB, slower; mutmut is simpler) | 8.7.0 (2026-08-09) | n/a | n/a | n/a |
| openapi-typescript + openapi-fetch (Yash) | ADOPT NOW (frontend) | 7.13.0 / 0.17.0 (2026-06-15) | `npm i -D openapi-typescript && npm i openapi-fetch` | 10 min | `npx openapi-typescript contracts/openapi.json -o src/api.d.ts` |
| Prism mock server (Yash) | ADOPT NOW if frontend starts before backend is reachable | 5.16.0 (2026-07-17) | `npx @stoplight/prism-cli` | 5 min | `npx @stoplight/prism-cli mock contracts/openapi.json -p 4010` |
| orval | SKIP (generates hooks; more than needed) | 8.44.0 (2026-10-21) | n/a | n/a | n/a |
| msw | LATER (only for frontend unit tests) | 3.0.3 (2026-10-10) | `npm i -D msw` | 20 min | n/a |
| locust | LATER (one bell-press scenario before demo) | 2.47.0 (2026-10-21) | `uv add --dev locust` | 20 min | `uv run locust -f scripts/loadtest.py --headless -u 20 -r 5 -t 30s -H http://localhost:8000` |
| k6 | SKIP (Go binary, JS scripts, extra install) | not checked | n/a | n/a | n/a |
| Docs generator (mkdocs, pdoc) | SKIP (docs are already markdown in `artifacts/architecture/`; FastAPI serves `/docs`; mkdocs last release 2024-08) | n/a | n/a | n/a | n/a |

## Schemathesis (details, MEASURED in-process)

The 4.x CLI has no in-process app option. In-process means a pytest file with `schemathesis.openapi.from_asgi`. The CLI works against a running server.

In-process test (ran as-is with `--with schemathesis==4.32.4`; put it at `backend/tests/integration/test_fuzz_contract.py`):

```python
import schemathesis
from bellhop.api.app import create_app
from bellhop.container import Settings, build_container

schema = schemathesis.openapi.from_asgi("/openapi.json", create_app(build_container(Settings.from_env())))

@schema.parametrize()
def test_contract(case):
    case.call_and_validate()
```

CLI against a live server (UNVERIFIED, from the 4.x CLI reference; flags `-u`, `-c`, `-n`, `-w`, `--exclude-checks` are documented):

```
BELLHOP_API_KEY=k uv run uvicorn bellhop.api.main:app --port 8000 &
uv run st run ../contracts/openapi.json -u http://localhost:8000 -H "X-API-Key: k" -n 100 -c all
```

CI step (add to `backend.yml` after Test): `uv run pytest tests/integration/test_fuzz_contract.py`. Exit code 1 means a check failed, 2 means it tested nothing.

What it found today (37 of 38 operations fail with all checks; `not_a_server_error` alone passes all 38, 100 cases each, 29 s):

| Code | Count | Meaning here | Action |
| --- | --- | --- | --- |
| ST103 undocumented status | 29 | 404 and 409 returned but openapi lists only 200 and 422 | Add `responses={404: ..., 409: ...}` to routes, or exclude `status_code_conformance` |
| ST201 / ST203 / ST401 | 7 each | Contract declares required `X-API-Key`, but auth is off when `BELLHOP_API_KEY` is unset, so requests without it succeed | Run with a key set, or exclude `ignored_auth,missing_required_header,negative_data_rejection` |
| 5xx | 0 | The NaN-to-500 bug is already fixed; I could not confirm Schemathesis generates NaN, so "would have caught it" is likely but unproven | Keep `not_a_server_error` as the gate |

Limits: it is single-threaded, so it will not find the duplicate-fact race. Data is shared across cases, so use a fresh container per test if flaky.

## import-linter (MEASURED)

Config (ran as INI; same content works under `[tool.importlinter]` in `pyproject.toml`). Siblings separated by `|` are independent of each other:

```
root_package = bellhop
[contract: layers]  type = layers
layers = container / api | adapters | fetchai | labelled | seed | scenarios / services / ports / domain
```

Real violations it found now:

| Violation | Rule broken |
| --- | --- |
| `services.memory_guard` imports `adapters.local_memory` | AGENTS.md rule 2: services import only domain and ports |
| `api.deps` imports `adapters.system` | api and adapters are siblings |
| `api.{app,deps,main}` import `container` | AGENTS.md layering puts container on top; decide whether api may import the `Container` type (then place `container` below `api` or add an `ignore_imports` line) |
| `seed` imports `scenarios` | sibling modules; group them or ignore |

Decide the intended layers first; the contract then fails CI on drift. Add `uv run lint-imports` to CI and pre-commit.

## vulture and type checkers (MEASURED)

| Tool | Result on `src` | Reading |
| --- | --- | --- |
| vulture `--min-confidence 80` | 0 findings | Safe CI gate |
| vulture `--min-confidence 60` | 71 findings | Re-finds review items: `CompositeNotifier`, `retry_failed`, `hello()`; also false positives (FastAPI routes, Pydantic fields, `HTMLParser` hooks). Use a whitelist file |
| mypy default | 8 errors in 3 files | Fix then gate |
| mypy `--strict` on domain, ports, services | 1 error (`services/family.py:30` returns Any) | Cheap to adopt on these three packages |
| pyright default | 31 errors | Noisier than mypy here; skip |

## Frontend (Yash)

| Step | Command |
| --- | --- |
| Types from the contract | `npx openapi-typescript ../contracts/openapi.json -o src/api.d.ts` |
| Typed client | `createClient<paths>({ baseUrl })` from `openapi-fetch` |
| Mock now | `npx @stoplight/prism-cli mock ../contracts/openapi.json -p 4010` (uses `contracts/examples/` if referenced in the spec; check) |
| Drift guard | CI: regenerate `api.d.ts`, `git diff --exit-code` |

UNVERIFIED: I did not run Prism or the generators. Prism is slow-moving (last release 2026-07).

## Pre-commit (ADOPT, thin)

Local hooks only (no remote repos to pin): `ruff check`, `ruff format --check`, `lint-imports`, and a contract-drift hook running `uv run python scripts/export_contract.py && git diff --exit-code ../contracts`. The drift test in pytest already guards CI, so the hook only shortens feedback. Keep it under 5 s; leave pytest to CI.

## Ranked top 5 plan

| Rank | Item | Minutes | Would have caught |
| --- | --- | --- | --- |
| 1 | import-linter contract in CI | 10 | Dependency-direction drift (4 live violations today) |
| 2 | Schemathesis pytest file, `not_a_server_error` gate plus documented-status fix | 25 | NaN-to-500 class (likely, unproven); undocumented 404/409 in contract Yash codes against |
| 3 | vulture at 80 in CI, 60 as a manual review with whitelist | 10 | Dead fields and parameters (review V3, V4, V11) |
| 4 | pytest-xdist (`-n auto`, 34 s to 13 s) plus `--cov-fail-under=90` | 5 | Nothing directly; faster loop, guards coverage (93 % now) |
| 5 | openapi-typescript plus Prism for Yash | 15 | Frontend/contract drift; unblocks UI before backend is up |

Total about 65 minutes. Not covered by any of these: the duplicate-fact race (needs a Hypothesis stateful or `ThreadPoolExecutor` test, about 20 min) and mutation testing (LATER; mutmut is the pick, unrun here).
