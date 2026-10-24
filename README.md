# Bellhop: the robot that answers the call bell

CalHacks project plan, exported from the team's Claude doc on 2026-10-23.

Bellhop is a small AI robot that rolls to a resident's room when the call bell rings, talks to them, and calls a nurse only when the situation needs one.

| File | What's in it |
| --- | --- |
| [01-project.md](docs/plan/01-project.md) | The plan: problem, how it works, agents, hardware, software, sponsors, 48-hour build plan, demo script, cost model, guardrails |
| [02-research.md](docs/plan/02-research.md) | Supporting research: staffing and call-bell numbers, cost model assumptions, Jev, sponsor research, existing robots, Freenove kit notes, Piper voice options, sources |
| [03-extra-ideas.md](docs/plan/03-extra-ideas.md) | Feature ideas with rough hours and status, including the team brainstorm |
| [artifacts/index.html](artifacts/index.html) | Polished overview page: the idea, features, full tech stack and the team work split. Open it locally in a browser |
| [artifacts/project.html](artifacts/project.html), [research.html](artifacts/research.html), [extra-ideas.html](artifacts/extra-ideas.html) | Styled versions of the three pages above, with both diagrams redrawn |
| [project-with-diagrams.pdf](docs/plan/project-with-diagrams.pdf) | The Project tab as a PDF, including the two diagrams (bell-to-outcome flow and 48-hour plan) that the Markdown export replaces with placeholders |

The `artifacts/` folder is static HTML and CSS with no build step; open `artifacts/index.html` directly. The live doc is the source of truth. This repo is a snapshot, so re-export if the doc changes.

## Code and architecture

| Path | What's in it |
| --- | --- |
| [AGENTS.md](AGENTS.md) | Start here if you are an AI agent or new contributor: commands and rules |
| [docs/architecture/](docs/architecture/README.md) | Architecture, module map, extension guide, agent roles, decisions, testing |
| [contracts/](contracts/README.md) | Frontend contract: OpenAPI spec plus real example payloads, kept in sync by a drift test |
| [docs/architecture/11-status.md](docs/architecture/11-status.md) | Progress checklist: done and verified, unverified, gaps, blocked, next, team handoff |
| [backend/](backend/README.md) | Python backend (`uv`): call state, dispatch, memory recall, staff alerts, config table |

## Ask Bellhop through ASI:One (optional)
```
cd backend
uv sync --extra fetch
export BELLHOP_AGENT_SEED="<long secret phrase>"   # never commit it
uv run uvicorn bellhop.api.main:app &
uv run python -m bellhop.fetchai                   # then connect the Mailbox via the Agent inspector link; needs an Agentverse account
```
Then ask "what happened in room 12?" from ASI:One with the Agents toggle on. Details: `docs/architecture/06-integrations.md`.
