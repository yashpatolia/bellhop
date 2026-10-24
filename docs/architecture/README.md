# Architecture index

| Doc | Read it when |
| --- | --- |
| [00-overview.md](00-overview.md) | You need the big picture: style, layers, data flow |
| [01-module-map.md](01-module-map.md) | You need to know where a thing lives or who owns it, with the exact public interfaces |
| [02-extension-guide.md](02-extension-guide.md) | You are adding an adapter, dispatch rule, alert channel or event handler |
| [03-agent-roles.md](03-agent-roles.md) | You are an AI agent picking up work: roles, handoffs, definition of done |
| [04-decisions.md](04-decisions.md) | You wonder why something is the way it is, or want to change it |
| [05-testing.md](05-testing.md) | You are writing tests |

Scope: the `backend/` package `bellhop`. Robot firmware (Jeremy), triage model (Gordon) and React dashboard (Yash) integrate through the interfaces in the module map.
