# Yash: connect the dashboard to the live Bellhop backend

This is the complete demo-day setup for the dashboard. Follow it in order. Do not use venue Wi-Fi or the laptop's ordinary LAN address: use the Tailscale address below.

## What you need

- Your computer, with internet access.
- A Tailscale account that has been invited to the team's tailnet. Ask Aditya for an invite if the sign-in does not show the Bellhop laptop.
- The dashboard source and its normal Node setup.
- The current backend address from Aditya. At the time this guide was written it is:

  ```text
  http://100.81.196.22:8000
  ```

  This is a Tailscale IP. It can change if the laptop is removed and re-added, so treat the address as configuration, not a hard-coded value.

## 1. Install and join Tailscale

1. Install Tailscale from [tailscale.com/download](https://tailscale.com/download) for your operating system.
2. Open Tailscale and sign in with the account that Aditya invited to the team network.
3. Check the Tailscale Machines page. You should see the Bellhop laptop/WSL node.
4. In a terminal on your computer, verify that you can reach the backend:

   ```bash
   curl http://100.81.196.22:8000/health
   ```

   Expected response:

   ```json
   {"status":"ok"}
   ```

Stop here if this fails. Confirm that Tailscale says Connected, that you joined the same tailnet, and that Aditya's backend terminal is still running. Do not substitute a `192.168.x.x` laptop address; that may fail on a hotspot.

## 2. Configure the dashboard API base URL

Set the dashboard's API base URL to the full Tailscale URL, with no trailing slash:

```text
http://100.81.196.22:8000
```

For a Vite app, put this in its uncommitted `.env.local`:

```bash
VITE_BELLHOP_API_URL=http://100.81.196.22:8000
```

Then use `import.meta.env.VITE_BELLHOP_API_URL` as the base URL. If the dashboard uses another build system, make the equivalent local environment setting. Never commit a real API key.

First load the initial state with:

```text
GET /calls
GET /alerts
GET /robots
GET /metrics
```

The backend currently allows browser origins by default. If the backend later enables `BELLHOP_API_KEY`, normal HTTP requests must send `X-API-Key`; see [Authentication](#authentication) for the EventSource exception.

## 3. Add the live SSE connection

Open one `EventSource` after the initial fetch. The browser reconnects it automatically. The server sends a retry hint of about three seconds and heartbeat comments every 15 seconds.

```ts
const api = import.meta.env.VITE_BELLHOP_API_URL;
const eventNames = [
  "call.raised",
  "call.assigned",
  "call.scored",
  "call.resolved",
  "alert.raised",
  "robot.updated",
] as const;

const connectEvents = () => {
  const source = new EventSource(`${api}/events`);

  source.addEventListener("call.raised", event => {
    const data = JSON.parse((event as MessageEvent).data);
    upsertCall(data.call);
  });
  source.addEventListener("call.assigned", event => {
    const data = JSON.parse((event as MessageEvent).data);
    upsertCall(data.call);
  });
  source.addEventListener("call.scored", event => {
    const data = JSON.parse((event as MessageEvent).data);
    upsertCall(data.call);
  });
  source.addEventListener("call.resolved", event => {
    const data = JSON.parse((event as MessageEvent).data);
    upsertCall(data.call);
  });
  source.addEventListener("alert.raised", event => {
    const data = JSON.parse((event as MessageEvent).data);
    upsertAlert(data.alert);
  });
  source.addEventListener("robot.updated", event => {
    const data = JSON.parse((event as MessageEvent).data);
    upsertRobot(data.robot);
  });

  source.onerror = () => {
    // EventSource reconnects automatically. Do not create another source here.
    // Refresh below so the screen catches up after a lost connection.
    void refreshAll();
  };
  return source;
};
```

`upsertCall`, `upsertAlert`, and `upsertRobot` should replace an object by its `id` in client state. Every event includes identifying fields and the **full current object** (`call`, `alert`, or `robot`), so do not make a second request for each event. Guard against a missing full object in case a record was deleted between enqueue and send.

The exact event payloads and examples are in [contracts/README.md](../../contracts/README.md#live-updates) and `contracts/examples/events.json`.

## 4. Keep polling as the fallback

SSE is the normal live path. Polling is the recovery path, not a competing live-feed implementation:

- Call `refreshAll()` once before opening SSE.
- Call it after an SSE connection error/reconnect.
- Optionally run it every 5 seconds while `EventSource.readyState` is not `OPEN`.
- `refreshAll()` should fetch `/calls`, `/alerts`, `/robots`, and `/metrics`, then replace the relevant state.

The stream intentionally does not replay missed events. A refetch after reconnect is required for correct state.

## Authentication

When the backend uses no `BELLHOP_API_KEY`, no credentials are needed.

When it does use one:

- `fetch` requests send `X-API-Key: <key>`.
- Browser `EventSource` cannot set headers. Build the event URL as:

  ```ts
  const source = new EventSource(`${api}/events?api_key=${encodeURIComponent(apiKey)}`);
  ```

The query-key exception exists only for `/events`. It can appear in browser history and access logs, so use a dashboard-only demo key and do not put the key in a committed frontend file.

## Demo verification checklist

Complete this before the demo:

1. `curl http://100.81.196.22:8000/health` succeeds from your machine.
2. The dashboard's initial `/calls` request succeeds.
3. Press a demo call bell or run `POST /calls` from the backend demo script; the call appears without a page refresh.
4. Change a robot's status; the dashboard updates its robot card without a page refresh.
5. Turn Tailscale off briefly, then back on. The dashboard reconnects and `refreshAll()` restores the correct calls and alerts.
6. Confirm the dashboard's fallback polling visibly works if SSE is unavailable.

## Fast troubleshooting

| Symptom | Check |
| --- | --- |
| `curl` cannot connect | Both devices must show Connected in Tailscale and be in the same tailnet; check that the backend is still running on port 8000. |
| Browser gets CORS error | Use the Tailscale URL exactly; ask Aditya to add the dashboard's origin to `BELLHOP_CORS_ORIGINS` if it was narrowed. |
| `401` from REST | The backend has `BELLHOP_API_KEY`; send `X-API-Key`. |
| `401` from `/events` | Add `?api_key=` to the EventSource URL, using the same key. |
| Screen becomes stale after Wi-Fi changes | Keep one EventSource only; call `refreshAll()` after `onerror` or reconnect. |
| Tailscale works but the old local IP does not | Expected on a phone hotspot or isolated Wi-Fi. Keep using the `100.x.x.x` Tailscale address. |

## Do not do these things

- Do not expose port 8000 to the public internet.
- Do not use a Cloudflare quick tunnel for the SSE stream.
- Do not hard-code a secret or the API URL into a committed source file.
- Do not open a new EventSource on every render or every error; close it when the dashboard unmounts.
