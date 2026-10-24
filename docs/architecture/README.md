# Architecture index

| Doc | Read it when |
| --- | --- |
| [00-overview.md](00-overview.md) | You need the big picture: style, layers, data flow |
| [01-module-map.md](01-module-map.md) | You need to know where a thing lives or who owns it, with the exact public interfaces |
| [02-extension-guide.md](02-extension-guide.md) | You are adding an adapter, dispatch rule, alert channel or event handler |
| [03-agent-roles.md](03-agent-roles.md) | You are an AI agent picking up work: roles, handoffs, definition of done |
| [04-decisions.md](04-decisions.md) | You wonder why something is the way it is, or want to change it |
| [05-testing.md](05-testing.md) | You are writing tests |
| [06-integrations.md](06-integrations.md) | You need sponsor facts: SpacetimeDB, Moss, Fetch.ai |
| [07-tech-scout.md](07-tech-scout.md) | You want library verdicts and bottleneck notes |
| [08-scenarios-and-admin.md](08-scenarios-and-admin.md) | You are setting up residents and nurses: scenario files, `BELLHOP_SEED_FILE`, admin routes |
| [09-hardware-interface.md](09-hardware-interface.md) | You are building the Pi, bell button or LEDs (Jeremy) |
| [10-review.md](10-review.md) | You want the independent review findings |
| [11-status.md](11-status.md) | You need what is done, verified, blocked and next, with test numbers |
| [12-research-dev-tooling.md](12-research-dev-tooling.md) | You want the dev tooling research (research note; may still be in progress) |
| [13-research-policy-and-triage.md](13-research-policy-and-triage.md) | You want research on a data-driven policy layer, clinical alignment and paraphrase recall |
| [14-research-deploy-and-connectivity.md](14-research-deploy-and-connectivity.md) | You want research on deployment and connectivity (Pi to backend, dashboard hosting) |

Scope: the `backend/` package `bellhop`. Robot firmware (Jeremy), triage model (Gordon) and React dashboard (Yash) integrate through the interfaces in the module map.
