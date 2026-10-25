# Scenarios and admin

Two ways to set up a care home: a JSON scenario file at startup, or the admin routes at runtime. Both go through the same rules (names 1 to 80 chars, rooms 1 to 32, ids 1 to 64, one resident per room).

## Scenario files
Full format and a minimal example: [artifacts/components/backend-scenarios.md](../components/backend-scenarios.md). Summary:
- JSON with optional top-level `residents`, `nurses`, `robots`. A resident has `id`, `name`, `room`, optional `risk_flags`, `birth_year`, `facts` (`{text, tags}`) and `preferences`. A nurse has `id`, `name`, optional `on_shift`. A robot has `id`, optional `status`, `battery` (0 to 1), `room`.
- Unknown keys, duplicate ids and shared rooms are rejected; a bad file stops startup with a message naming the problem.
- `scenarios/demo.json` is the demo home; `scenarios/empty.json` starts with nothing.

Run with a scenario (from `backend/`):
```
BELLHOP_SEED_FILE=scenarios/demo.json uv run uvicorn bellhop.api.main:app --port 8000
```
`BELLHOP_SEED_FILE` wins over `BELLHOP_SEED_DEMO=1`. Code: `scenarios.py` (`load_scenario`, `apply_scenario`), applied by `container.py`.

## Admin routes
`services/admin.py` (`AdminService`, `Container.admin`) behind thin routes in `api/app.py`. Resident: `{id, name, room, risk_flags, birth_year}`. Nurse: `{id, name, on_shift, open_tasks}`.

| Route | Body | Result |
| --- | --- | --- |
| `POST /residents` | `{id?, name, room, risk_flags?, birth_year?}` | 201; 409 duplicate id or room taken; 422 invalid |
| `GET /residents`, `GET /residents/{id}` | none | 200; 404 unknown |
| `PATCH /residents/{id}` | any of `name`, `room`, `risk_flags`, `birth_year` | 200; 404, 409 room taken, 422 |
| `POST /nurses` | `{id?, name, on_shift?}` | 201; 409 duplicate id; 422 |
| `GET /nurses` | none | 200 |
| `PATCH /nurses/{id}` | any of `name`, `on_shift` | 200; 404; 422 |

- Omit `id` to have one generated (`res_...`, `nurse_...`). Unknown keys and explicit `null` for `name`, `room`, `risk_flags` are 422. `birth_year` accepts 1880 to 2015 or `null`.
- A resident created at runtime is matched to calls from their room immediately; a nurse is eligible for dispatch while `on_shift`. Going off shift never changes `open_tasks`.
- `PUT /residents/{id}` (`birth_year` only) remains for backward compatibility.
- Same auth and limits as every route (`X-API-Key` when `BELLHOP_API_KEY` is set, 1 MB body limit). Tests: `tests/integration/test_admin_api.py`, `tests/unit/test_admin_service.py`.

Robots are not created here: `PUT /robots/{id}` registers them (unless `BELLHOP_ALLOW_NEW_ROBOTS=0`), and each report is pushed to dashboards as `robot.updated` on `GET /events` (see [artifacts/components/contracts.md](../components/contracts.md#live-updates)).
