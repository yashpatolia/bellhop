# Overview

## Style
Hexagonal (ports and adapters) with a small event bus.

```
 bell button / robot / dashboard / triage
              |  HTTP (api/)
              v
        +-----------+      +------------+
        | services  | ---> |   ports    |  (Protocols)
        +-----------+      +------------+
              |                  ^
              v                  | implements
        +-----------+      +------------+
        |  domain   |      |  adapters  |  in-memory | spacetimedb | moss | log/push
        +-----------+      +------------+
```

- **domain**: pydantic models + pure rules (call state machine, urgency ratchet). No I/O.
- **ports**: `typing.Protocol` interfaces for storage, memory recall, notifications, robot commands, events, clock, ids.
- **services**: use cases. Each has one job and takes ports through its constructor.
- **adapters**: concrete port implementations. In-memory ones are the default and the test doubles; sponsor ones (SpacetimeDB, Moss) are swappable.
- **api**: thin FastAPI layer; no business logic.
- **container.py**: the only place that picks concrete adapters (composition root).

## Patterns in use (and why)
| Pattern | Where | Why it earns its place |
| --- | --- | --- |
| Ports and adapters | everywhere | Sponsor access can fail; swap in minutes |
| State machine | `Call.transition` | Illegal call states are unrepresentable |
| Strategy | `DispatchPolicy` | Dispatch rules will change (nearest robot, nurse load, fleet) |
| Observer / event bus | `EventBus` | Liaison and analytics react to calls without Dispatcher knowing them |
| Composition root | `container.py` | One place to change wiring |

Nothing else. No DI framework, no CQRS, no repositories-per-aggregate beyond the ports listed.

## Data flow (the milestone path)
1. Bell press -> `POST /calls` -> `CallService.raise_call(room)` -> `CallRaised`.
2. `Dispatcher` reacts: picks robot / nurse / both via `DispatchPolicy` -> `CallAssigned`; `RobotGateway.go_to`.
3. Robot arrives; Companion fetches `GET /residents/{id}/memory?q=...` (`MemoryService.recall`).
4. Triage result -> `POST /calls/{id}/score` -> `TriageGuard.decide` (keyword floor, low confidence; model failure uses `POST /calls/{id}/triage-failed`) -> `Call.score` -> `CallScored`.
5. `Liaison` reacts to urgency >= 3: creates `Alert`, `Notifier.send` -> `AlertRaised`.
6. Resolution -> `CallResolved` -> `Visit` recorded; `Analytics` reads calls and visits for the dashboard counters.

## Invariants
- Urgency only ratchets up. Urgency 4 alerts immediately and to everyone on shift.
- A call is closed only after it is resolved.
- Services never construct adapters; adapters never import services.
