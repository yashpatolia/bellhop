# Research: running Bellhop together (hosting, Pi link, live updates, demo day)

Researched 2026-10-23. The vendor and network claims below remain unverified because page fetches failed in this session. Since this research was written, the recommended `GET /events` SSE endpoint has been implemented; its actual wire contract is in [artifacts/components/contracts.md](../components/contracts.md#live-updates). Tailscale setup and the Pi watchdog remain deployment work.
## Assumptions
1. Backend is `bellhop.api.main:app` (FastAPI, Python 3.12, `uv`), default `BELLHOP_STORE=memory` (verified in `container.py`). `GET /health` exists.
2. The React dashboard runs on a teammate's machine and needs to reach the backend over HTTP from a different host (CORS default `*`, verified).
3. The Pi sits behind NAT, possibly on a phone hotspot or venue Wi-Fi with client isolation. We cannot count on inbound connections to the Pi.
4. Demo is short. Total team size is small (at most 6 people on Tailscale).
5. No budget; no card on file.

## 1. Shared backend

| Option | Setup | Cold start | Free tier (as found) | WS / SSE | Secrets | Verdict |
| --- | --- | --- | --- | --- | --- | --- |
| Laptop + Tailscale (tailnet) | 10 min | none | Personal plan, up to 6 users, unlimited user devices (pricing page via search); non-commercial | Both (plain TCP) | env on laptop | Best default |
| Laptop + `cloudflared` quick tunnel | 2 min | none | free, no account | **SSE not supported on quick tunnels** (Cloudflare docs via search); 200 in-flight cap; random URL per run; WS unverified | env on laptop | Fine for REST; bad for SSE |
| Laptop + Cloudflare named tunnel | 20 min | none | free, needs account and a domain you control | SSE and WS fine (limits apply to quick tunnels only) | env on laptop | Good public URL, more setup |
| Tailscale Funnel | 5 min after tailnet | none | no current quota found (unverified) | WS unverified | env on laptop | Only for judges' phones |
| ngrok free | 5 min | none | 1 GB/month out; interstitial page for browsers (header `ngrok-skip-browser-warning` bypasses); static-domain rules conflict between official pages | SSE and WS unverified | env on laptop | Backup |
| localhost.run | 1 min (`ssh -R 80:localhost:8000 localhost.run`) | none | free, random URL | unverified | n/a | Last resort; not researched |
| Render free web service | 15 min | ~1 min after 15 min idle (docs via search); WS messages keep it awake since 2026-02-24 | 750 free instance hours/month; local disk lost on spin-down | WS yes; SSE streaming unverified | dashboard env vars | Cold start kills a live demo |
| Fly.io | 20 min | none if `min_machines_running=1` | **No free allowance for new orgs**: trial only (about 2 h runtime or 7 days; apps stop until a card is added) (docs via search) | Both | `fly secrets set` | Needs card; skip |
| Railway | 15 min | none | One-time $5 trial grant; Hobby is $5/month; card now required (docs via search); a $1 free plan is claimed by third parties only | Both | dashboard vars | Needs card; skip |
| Google Cloud Run | 30 min | seconds (min instances 0) or 0 (min 1, billed) | request and vCPU-second free allowance (numbers conflicted in search: 240k vs 180k vCPU-s; check page); billing account required | WS yes (Google docs, from memory, unverified); streams are bounded by the request timeout (unverified) | Secret Manager or env | Overkill |
| Plain VPS | 30 min | none | not free | Both | `.env` | Overkill |

Why not a cloud host: the state is in memory, the Pi must reach it either way, and a cold or restarted instance loses calls mid-demo. A laptop on the same table is faster to debug and costs nothing.

### What a restart loses

| Store | On restart | Notes |
| --- | --- | --- |
| `memory` (default) | All calls, alerts, visits, robot registry, memory facts added at runtime | `BELLHOP_SEED_DEMO=1` (or `BELLHOP_SEED_FILE`) re-seeds residents, nurses, memory. Re-run `scripts/demo_scenes.py` to rebuild calls |
| SpacetimeDB (`BELLHOP_STORE` set to the stdb adapter, see 06-integrations) | Nothing, if the stdb server keeps its data dir | Adds a second process and a module publish step; the dashboard can subscribe directly |

Recommendation for demo day: keep `memory` plus seed; run the backend under a restart loop (`while true; do ...; done`) so a crash returns to a known seeded state in seconds; never restart between rehearsal and demo. Use SpacetimeDB only if the dashboard teammate has already built on it (see section 3).

### Minimal start command (no Docker)

```
cd backend
uv sync
BELLHOP_SEED_DEMO=1 BELLHOP_API_KEY=<secret> BELLHOP_CORS_ORIGINS="*" \
  uv run uvicorn bellhop.api.main:app --host 0.0.0.0 --port 8000
```

`--host 0.0.0.0` is required for others to reach it (default is loopback). WSL2 caveat: in default NAT mode other machines cannot reach the WSL IP. Run Tailscale inside WSL (it gets its own tailnet IP) or enable mirrored networking in `%UserProfile%\.wslconfig` (`[wsl2]` then `networkingMode=mirrored`). Unverified on this specific laptop; test early.

### Dockerfile sketch (only if we later pick a cloud host)

```
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev
COPY backend/src ./src
ENV BELLHOP_SEED_DEMO=1 PATH="/app/.venv/bin:$PATH"
CMD ["sh","-c","uvicorn bellhop.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

Env var names (from repo): `BELLHOP_API_KEY`, `BELLHOP_CORS_ORIGINS`, `BELLHOP_SEED_DEMO`, `BELLHOP_SEED_FILE`, `BELLHOP_STORE`, `BELLHOP_ROBOT_URL`, `BELLHOP_ALLOW_NEW_ROBOTS`, `BELLHOP_GUARDS`, `BELLHOP_MEMORY`, `BELLHOP_CONTENT`; optional SpacetimeDB: `BELLHOP_STDB_URL`, `BELLHOP_STDB_DB`, `BELLHOP_STDB_TOKEN`; agent side: `BELLHOP_AGENT_PORT`, `BELLHOP_AGENT_SEED`, `BELLHOP_AGENT_ALLOWED_SENDERS`. Check each against `container.py` before relying on it.

## 2. Pi to backend link

Problem: the current design needs the backend to reach the Pi (`BELLHOP_ROBOT_URL`). Phone hotspots and many venue networks block client-to-client traffic, and mDNS multicast is usually blocked by isolation too.

| Option | Works with client isolation | Code change | Setup | Notes |
| --- | --- | --- | --- | --- |
| mDNS `raspberrypi.local` (avahi, preinstalled on Pi OS) | No (multicast dropped); Android resolution is also unreliable (not verified) | none | 0 | Good only on a plain travel router |
| Tailscale on Pi and laptop | Yes (outbound to coordination server, direct or relay over HTTPS) | none | 10 min | Pi OS Trixie: Tailscale's apt repo steps at tailscale.com/docs/install/rpi/rpi-trixie, or `curl -fsSL https://tailscale.com/install.sh \| sh` then `sudo tailscale up`; read the IP with `tailscale ip -4`; disable key expiry on the Pi |
| MQTT with Mosquitto | Yes if the broker is reachable by both (broker on laptop over tailnet, or a public broker) | new dependency on both sides, new adapter | 60+ min | Best protocol, wrong cost for a hackathon; `HttpRobotGateway` would be replaced |
| Pi opens outbound SSE or long-poll to backend | Yes, with no VPN | one backend endpoint, one Pi loop | 45 min | Pi needs only a route to the backend URL (tunnel, tailnet, or LAN) |
| Pi opens outbound WebSocket | Yes | new endpoint and Pi library | 60 min | Same as above with more moving parts |

Recommended, simplest option that works when the Pi cannot be reached inbound: **Tailscale on the Pi and the laptop**. It keeps the 09-hardware-interface design as is (backend POSTs `go_to`, Pi PUTs status) and needs zero code. Set `BELLHOP_ROBOT_URL=http://<pi-tailscale-ip>:<port>` and the Pi uses `http://<laptop-tailscale-ip>:8000`. Caveats: Tailscale's own admin console is needed once per device; the laptop (inside WSL) must be a tailnet member.

If Tailscale is blocked or fails at the venue: switch to the outbound command channel (one new endpoint, kept as the contingency, not built now):

- `GET /robots/{id}/commands?wait=25` long-poll. Returns `204` on timeout, or `200 {"seq": 7, "cmd": "go_to", "room": "12"}`. Pi loops, acknowledges with `POST /robots/{id}/commands/{seq}/ack`. `HttpRobotGateway` is swapped for a `QueueRobotGateway` that enqueues instead of POSTing.
- Reuses the existing `PUT /robots/{id}` heartbeat for liveness.

### Failure behaviour we want (all Pi side)

| Condition | Pi behaviour |
| --- | --- |
| No successful heartbeat or command poll for 5 s | Stop motors, LED `idle`, discard any queued move |
| Command older than 10 s when received | Ignore it (include `issued_at` in the payload) |
| Link returns | Do not resume the old move; wait for a fresh command |
| Backend marks Pi stale (no `PUT` for 15 s) | Dispatcher treats robot as unavailable and falls back to a nurse |

### Changes to 09-hardware-interface.md (proposed, not made)

1. Add a "Network topology" section: Tailscale on Pi and laptop is the default; same-LAN IP is the fallback; the outbound long-poll channel is the contingency.
2. Replace need #2 ("hostname reachable from backend") with the tailnet IP and a note that mDNS is unreliable under client isolation.
3. Make the 5 s link-loss timeout and the 10 s command expiry explicit in "Robot must stay safe when the network drops".

## 3. Live dashboard updates

| Option | Frontend work | Backend work | Behind tunnels / proxies | Verdict |
| --- | --- | --- | --- | --- |
| Polling every 1-2 s (`GET /calls`, `/alerts`, `/robots`) | Minimal, already works | none | Works everywhere | Always keep as fallback |
| SSE | `new EventSource(url)`, auto-reconnect built in | one endpoint | Fine on tailnet; not on cloudflared quick tunnels | Recommended |
| WebSocket (FastAPI) | Manual reconnect and heartbeat code | one endpoint plus connection manager | Needs upgrade support | Not worth it for one-way data |
| SpacetimeDB subscriptions from React | Generated TS bindings; teammate learns a new client | module, stdb adapter, publish | Needs the stdb server reachable | Only if already adopted; extra process on demo day |

Library: FastAPI 0.135.0 and later ships native SSE (`from fastapi.sse import EventSourceResponse`, yield `ServerSentEvent` for `event`/`id`/`retry`) per the FastAPI tutorial (seen in search results; the version claim comes from search, not our lockfile). `sse-starlette` is the older package that gives `EventSourceResponse` with configurable `ping=`. Check our `uv.lock` FastAPI version; if below 0.135, `uv add sse-starlette` (needs team approval, dependency rule). A bare `StreamingResponse(media_type="text/event-stream")` also works with no dependency but you hand-write `event:`/`data:` framing and keep-alives.

### Original endpoint design (superseded by the implemented contract)

`GET /events` (SSE). Subscribes to the existing `EventBus` (`ports.EventBus.subscribe`) per connection, pushes into an `asyncio.Queue`, unsubscribes on disconnect. Because services are synchronous, bridge with `loop.call_soon_threadsafe(queue.put_nowait, item)` inside the handler.

| Event name | Trigger | `data` payload |
| --- | --- | --- |
| `snapshot` | on connect | `{"calls": [Call...], "alerts": [Alert...], "robots": [...]}` (same shape as the `GET` endpoints) |
| `call` | `CallRaised`, `CallAssigned`, `CallScored`, `CallResolved` | `Call` JSON (`model_dump(mode="json")`); `id:` is `call.id` |
| `alert` | `AlertRaised` | `Alert` JSON |
| `robot` | `PUT /robots/{id}` | robot JSON |
| `ping` | every 15 s | comment line `: ping` |

Client contract: `snapshot` replaces state; `call`/`alert`/`robot` upsert by `id`. `EventSource` reconnects itself and the new `snapshot` resyncs (no `Last-Event-ID` replay). Frontend code:

```
const es = new EventSource(`${API}/events`);
es.addEventListener("call", e => upsertCall(JSON.parse(e.data)));
es.addEventListener("alert", e => upsertAlert(JSON.parse(e.data)));
```

Least work for the frontend teammate: SSE with polling as the fallback. SpacetimeDB subscriptions are the least work only if the module and bindings already exist (06-integrations plans that; no code was verified here).

## 4. Demo-day resilience checklist

| Item | Action |
| --- | --- |
| Primary network | Phone hotspot (not venue Wi-Fi), 2.4 GHz if the Pi struggles; laptop, Pi, teammate laptop all join it; Tailscale on top |
| Second network | Travel router or second phone hotspot; know the SSID and password; test Pi auto-join |
| Offline fallback | Pi: local-only modes (Piper voice, games, stop-and-idle). Dashboard: polling plus a `?mock=1` mode with canned JSON from `scenarios/` |
| Health checks | `curl -fsS http://<host>:8000/health`; `tailscale status`; dashboard shows last event age |
| Pre-flight (10 min before) | restart backend once, confirm seed, run smoke test, charge the Pi battery, kill background syncs |
| Secrets | `BELLHOP_API_KEY` in a git-ignored `.env`; share by hand, not in chat |
| Pre-record | A full 90 s screen capture of the three demo scenes (dashboard plus robot), the robot driving to a room, and a voice reply; keep the files on the laptop and on a phone |

### One-command smoke test

Uses only the existing script and `/health`:

```
cd backend && curl -fsS "$API/health" && BELLHOP_API="$API" uv run python scripts/demo_scenes.py
```

`BELLHOP_API` appears in the repo env names; confirm `demo_scenes.py` reads it (not verified). A `make smoke` wrapper is a 5-minute follow-up.

## Ranked top 5 (what to do, in order)

| Rank | Task | Minutes | Why |
| --- | --- | --- | --- |
| 1 | Backend on laptop with `--host 0.0.0.0`, `BELLHOP_SEED_DEMO=1`, restart loop; fix WSL reachability | 20 | Everything else depends on it |
| 2 | Tailscale on laptop (inside WSL), Pi, and the dashboard teammate's machine; set `BELLHOP_ROBOT_URL` and the Pi's backend URL to tailnet IPs | 20 | Removes the inbound-to-Pi problem with no code |
| 3 | Pi safety watchdog: stop and idle after 5 s without a good heartbeat or poll; reject commands older than 10 s | 30 | Required by the safety invariant |
| 4 | `GET /events` SSE endpoint (design above) with polling kept as fallback | 45 | Live dashboard, minimal frontend work |
| 5 | Smoke test wrapper plus a 90 s pre-recorded demo | 25 | Insurance if the network dies |

## Recommended default stack

Backend on the team laptop (memory store, seeded, restart loop), reachable over a Tailscale tailnet that includes the Pi and the dashboard teammate; phone hotspot as the physical network with a second hotspot as backup; existing HTTP design for the Pi unchanged, with a Pi-side 5 s link-loss watchdog; dashboard uses SSE (`GET /events`) with polling fallback; SpacetimeDB left optional. Contingencies in order: LAN IPs on a travel router, the outbound long-poll command channel, the pre-recorded demo.

## Not verified
Cloud Run WebSocket and timeout behaviour; Tailscale Funnel limits and WebSocket support; cloudflared quick tunnel WebSocket support; ngrok static-domain and session-limit rules; Android hotspot behaviour for mDNS and client isolation; FastAPI version in our lockfile; whether `demo_scenes.py` honours `BELLHOP_API`; WSL mirrored networking on the team laptop; whether every env var name above is read in `container.py`.
