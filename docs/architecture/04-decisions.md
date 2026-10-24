# Decisions

Format: ID, decision, reason, consequence. Append; do not rewrite history.

- **ADR-1 Hexagonal layout.** Sponsor access is uncertain (plan risk table), so every external dependency sits behind a port. Consequence: slight indirection, large flexibility.
- **ADR-2 Synchronous ports.** MVP traffic is a few calls; sync keeps tests and services simple. FastAPI runs sync handlers in a threadpool. Revisit if a SpacetimeDB client forces async: wrap it in the adapter.
- **ADR-3 In-memory adapters are first-class.** They are the default runtime for the demo fallback and the test doubles. Consequence: contract tests run against every adapter.
- **ADR-4 Urgency only ratchets up.** Matches the "lean toward escalation" guardrail; enforced in `Call.score`, not in callers.
- **ADR-5 Event bus is in-process and synchronous.** Deterministic tests. A durable bus is not needed for the demo; SpacetimeDB subscriptions serve the dashboard.
- **ADR-6 Pydantic v2 models in the domain.** Same objects serialize to the API and validate input; the one framework dependency allowed in `domain/`.
- **ADR-7 Python 3.12, uv only.** Single toolchain; `uv.lock` committed.
- **ADR-8 Local lexical memory first, Moss second.** Meets the 50 ms budget with zero keys; Moss is an adapter swap if access works.
- **ADR-9 Guard external calls with timeouts and a breaker.** A hung notifier, robot gateway or memory index must not stall a bell press or the voice loop. `adapters/guards.py` runs calls in a small shared thread pool with a deadline (stdlib only). Notifier failures are logged and kept in `failed_alerts` for retry; gateway timeouts raise so the Dispatcher falls back to a nurse; memory recall over budget uses the local fallback and trips a circuit breaker. On by default; `Settings(guard_timeouts=False)` disables. Consequence: a hung call holds a worker thread until it returns. Known limitation: the synchronous event bus does not time-box handlers, so a slow handler still delays `publish`.
