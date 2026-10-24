# Scenarios

A scenario is a JSON file that sets up a home: residents, nurses, robots and what the robot knows about each resident.

- Apply one at startup with `BELLHOP_SEED_FILE=scenarios/demo.json`. It wins over `BELLHOP_SEED_DEMO=1`.
- A missing, malformed or invalid file stops startup with a message naming the problem (no silent empty system).
- `demo.json` is the demo home (Margaret, Arthur, Priya, Sam, `robot_1`); `BELLHOP_SEED_DEMO=1` applies it. `empty.json` starts with nothing.
- Unknown keys are rejected. Resident ids, nurse ids and robot ids must each be unique, and two residents cannot share a room.

Top-level keys (all optional): `residents`, `nurses`, `robots`.

| Object | Field | Required | Rules |
| --- | --- | --- | --- |
| resident | `id` | yes | 1 to 64 chars, unique |
| resident | `name` | yes | 1 to 80 chars |
| resident | `room` | yes | 1 to 32 chars, unique across residents |
| resident | `risk_flags` | no | list of strings, each 1 to 32 chars, at most 10 (for example `"falls"`) |
| resident | `birth_year` | no | integer |
| resident | `facts` | no | list of `{"text": string, "tags": [string]}`; remembered for recall |
| resident | `preferences` | no | any of `hard_of_hearing`, `quiet_mode`, `night_mode` (booleans), `favourite_drink` (string) |
| nurse | `id`, `name` | yes | id unique |
| nurse | `on_shift` | no | boolean, default `true` |
| robot | `id` | yes | unique |
| robot | `status` | no | `idle` (default), `busy`, `charging`, `fault` |
| robot | `battery` | no | 0 to 1, default 1 |
| robot | `room` | no | where the robot is now |

Minimal example:

```json
{
  "residents": [{"id": "res_ines", "name": "Ines", "room": "301",
                 "facts": [{"text": "Loves jasmine tea", "tags": ["tea"]}]}],
  "nurses": [{"id": "nurse_lena", "name": "Lena"}],
  "robots": [{"id": "bot_a", "room": "hall"}]
}
```
