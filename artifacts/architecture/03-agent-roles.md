# Agent roles

| Role | Does | Must not |
| --- | --- | --- |
| **Manager** | Splits work into packages, assigns file ownership, merges, runs the full suite, reports | Write feature code that a builder owns |
| **Architect** | Owns `domain/`, `ports/`, and `artifacts/architecture/`. Changes a port only with an ADR line in `04-decisions.md` | Implement services |
| **Builder** (one per work package) | TDD-implements the files listed for its package in `01-module-map.md` | Edit files outside its package, edit `domain/` or `ports/`, add dependencies |
| **Tester** | Writes cross-module integration tests and probes edge cases and invariants after builders finish | Change production code; report bugs to the manager with a failing test |
| **Researcher** | Reads docs and sponsor APIs, writes findings into `artifacts/architecture/` | Write production code |
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

## Roles actually used
Manager, architect, builders, testers, researcher, tech scout, reviewer (see `10-review.md`) and docs. The reviewer reads finished work and reports findings without editing production code; docs edits only markdown and checks it against the code.

## Working rules learned
- Verify builder claims independently: re-run the suite and read the diff; a "green" report is not evidence.
- One owner per shared file (`container.py`, `api/app.py`, `contracts/`). Builders add new files; the manager wires them.
- Evaluate on fresh inputs: tune on one set, measure on another written afterwards (the triage guard fell from 20/24 to 11/24 that way).
- Record a bug as a strict xfail test before fixing it.
- Do not run formatters while other agents are editing the same tree.
