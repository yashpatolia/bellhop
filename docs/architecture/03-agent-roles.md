# Agent roles

| Role | Does | Must not |
| --- | --- | --- |
| **Manager** | Splits work into packages, assigns file ownership, merges, runs the full suite, reports | Write feature code that a builder owns |
| **Architect** | Owns `domain/`, `ports/`, and `docs/architecture/`. Changes a port only with an ADR line in `04-decisions.md` | Implement services |
| **Builder** (one per work package) | TDD-implements the files listed for its package in `01-module-map.md` | Edit files outside its package, edit `domain/` or `ports/`, add dependencies |
| **Tester** | Writes cross-module integration tests and probes edge cases and invariants after builders finish | Change production code; report bugs to the manager with a failing test |
| **Researcher** | Reads docs and sponsor APIs, writes findings into `docs/architecture/` | Write production code |
| **Tech Scout** | Finds libraries and data-pipeline options, hunts bottlenecks and inefficiencies, writes ADOPT NOW / LATER / SKIP verdicts into `07-tech-scout.md` | Write production code or add dependencies; the manager adopts |

## Handoff rules
- A builder who needs a port or domain change stops and reports the exact change; the architect applies it.
- Each package ends with: its tests green, `uv run ruff check` clean, full `uv run pytest` green.
- Report format: files created, tests added, anything deferred, any contract concern.

## Definition of done (any package)
1. Failing test seen before each behaviour was implemented.
2. Public interface matches `01-module-map.md` exactly.
3. No new dependency, no I/O in `domain/`, services import only `domain` and `ports`.
4. Docs updated if behaviour or interface changed.
