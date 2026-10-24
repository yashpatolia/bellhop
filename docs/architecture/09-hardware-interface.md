# Hardware interface (Pi, bell button, rooms)

Owner on the hardware side: Jeremy. Backend side: Aditya. Status: **backend half is not built yet**; this doc fixes the contract so both sides can work in parallel.

## What exists today
| Direction | Mechanism | State |
| --- | --- | --- |
| Bell press to backend | `POST /calls {room}` | Done |
| Robot arrived | `POST /calls/{id}/in-visit` | Done |
| Call finished | `POST /calls/{id}/resolve` | Done |
| Backend commands robot | `RobotGateway.go_to`, `set_led` | Port only; default adapter just records |
| Robot reports status, battery, room | none | **Missing** |

## What the backend will add (after the current store work lands)
1. `GET /robots`, `PUT /robots/{id} {status, battery, room}` so the Pi can report in (every 5 s is enough). `status` is one of `idle`, `busy`, `charging`, `fault`. `battery` is 0 to 1.
2. `HttpRobotGateway`: the backend calls an HTTP server on the Pi. Wrapped in the existing timeout guard; on failure the call falls back to a nurse.

## What we need from the hardware side
| # | Need | Why |
| --- | --- | --- |
| 1 | A small HTTP server on the Pi: `POST /go_to {room}`, `POST /led {state}`, `POST /stop`, `GET /snapshot` | The backend commands the robot over HTTP. The Freenove server can be extended; any language is fine |
| 2 | Pi hostname or IP and port reachable from the backend machine (same hotspot or router) | Needed for `BELLHOP_ROBOT_URL` |
| 3 | Pi code that calls `PUT /robots/{id}` with status, battery and current room | Dispatcher skips robots with low battery or a fault |
| 4 | Pi calls `POST /calls/{id}/in-visit` on arrival | Starts the response-time clock and the visit |
| 5 | Room ids that match the backend. Pick one set (the brief's examples use 204 and 210, our seed uses 12 and 14) and tell us the marker-to-room map | `go_to(room)` and the bell button both send these strings |
| 6 | Bell button (ESP32 or Pico W) sending `POST /calls {"room": "<id>"}` with a hard 2 s timeout and a retry | Fallback is a web button |
| 7 | Confirmation that LED states can be set by name | See below |

## LED states (proposed names)
`idle`, `listening`, `nurse_on_way`, `emergency`. The backend will send `emergency` on urgency 4 and `nurse_on_way` on urgency 3.

## Robot must stay safe when the network drops
If the backend is unreachable the Pi keeps its last safe state (stopped, LED idle). Never drive without a fresh command. Local-only modes in the brief (Piper voice, games) keep working.
