# Bellhop: the robot that answers the call bell

CalHacks project plan, exported from the team's Claude doc on 2026-10-23.

Bellhop is a small AI robot that rolls to a resident's room when the call bell rings, talks to them, and calls a nurse only when the situation needs one.

| File | What's in it |
| --- | --- |
| [01-project.md](../docs/plan/01-project.md) | The plan: problem, how it works, agents, hardware, software, sponsors, 48-hour build plan, demo script, cost model, guardrails |
| [02-research.md](../docs/plan/02-research.md) | Supporting research: staffing and call-bell numbers, cost model assumptions, Jev, sponsor research, existing robots, Freenove kit notes, Piper voice options, sources |
| [03-extra-ideas.md](../docs/plan/03-extra-ideas.md) | Feature ideas with rough hours and status, including the team brainstorm |
| [index.html](index.html) | Polished overview page: the idea, features, full tech stack and the team work split. Open it locally in a browser |
| [project.html](project.html), [research.html](research.html), [extra-ideas.html](extra-ideas.html) | Styled versions of the three pages above, with both diagrams redrawn |
| [project-with-diagrams.pdf](../docs/plan/project-with-diagrams.pdf) | The Project tab as a PDF, including the two diagrams (bell-to-outcome flow and 48-hour plan) that the Markdown export replaces with placeholders |

This folder is static HTML and CSS with no build step; open `index.html` directly. The live doc is the source of truth. This repo is a snapshot, so re-export if the doc changes.

## Dashboard

The nurse dashboard lives in `dashboard/` (Vite, React, TypeScript). Run `cd dashboard && npm install && npm run dev`. It uses mock data until the real store exists; see `dashboard/src/data/source.ts`. Open `/#/themes` to compare the layouts.
