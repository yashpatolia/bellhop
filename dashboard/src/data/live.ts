import type { Alert, Call, Metrics, Robot, Snapshot, Urgency } from './types'
import type { DataSource } from './source'
import { staticSnapshot } from './mock'
import { applyEntry, refineLocally } from './staffEntries'

// Live source for the Bellhop backend: REST for initial state, one SSE
// stream for updates, refetch as the recovery path. The backend does not own
// residents, nurses or hourly buckets yet, so those stay on the mock base.
// Payload shapes are normalised tolerantly (camelCase or snake_case) until
// contracts/ is checked in.

type Raw = Record<string, unknown>
type Entity = { id: string }

const API = (import.meta.env.VITE_BELLHOP_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''
const API_KEY = import.meta.env.VITE_BELLHOP_API_KEY as string | undefined

export const liveEnabled = API !== ''

const POLL_MS = 5000

const pick = (r: Raw, ...keys: string[]) => {
  for (const k of keys) if (r[k] !== undefined && r[k] !== null) return r[k]
  return undefined
}

function toMs(v: unknown, fallback: number | null): number | null {
  if (typeof v === 'number') return v < 1e12 ? v * 1000 : v
  if (typeof v === 'string') {
    const t = Date.parse(v)
    if (!Number.isNaN(t)) return t
  }
  return fallback
}

function normalizeCall(raw: Raw, prev?: Call): Call {
  const base: Call = prev ?? {
    id: String(raw.id),
    residentId: '',
    room: 0,
    urgency: 1,
    category: 'other',
    status: 'robot_en_route',
    handledBy: 'robot',
    robotId: null,
    createdAt: Date.now(),
    firstResponseSec: null,
    resolvedAt: null,
    resolvedByRobot: false,
    summary: '',
    sbar: { s: '', b: '', a: '', r: '' },
    transcript: [],
    confidence: 0,
    costUsd: 0,
    feedback: null,
  }
  const out = { ...base, id: String(raw.id) } as Call
  const set = <K extends keyof Call>(k: K, ...keys: string[]) => {
    const v = pick(raw, k as string, ...keys)
    if (v !== undefined) out[k] = v as Call[K]
  }
  set('residentId', 'resident_id')
  set('room', 'room_number')
  set('urgency', 'score')
  set('category')
  set('status')
  set('handledBy', 'handled_by')
  set('robotId', 'robot_id')
  set('firstResponseSec', 'first_response_sec')
  set('resolvedByRobot', 'resolved_by_robot')
  set('summary')
  set('sbar')
  set('transcript')
  set('confidence')
  set('costUsd', 'cost_usd')
  set('feedback')
  out.createdAt = toMs(pick(raw, 'createdAt', 'created_at'), base.createdAt) ?? base.createdAt
  out.resolvedAt = toMs(pick(raw, 'resolvedAt', 'resolved_at'), base.resolvedAt)
  return out
}

function normalizeRobot(raw: Raw, prev?: Robot): Robot {
  const base: Robot = prev ?? { id: String(raw.id), name: String(raw.id), state: 'idle', battery: 100, x: 0, y: 0, targetRoom: null, callId: null }
  const out = { ...base, id: String(raw.id) } as Robot
  const set = <K extends keyof Robot>(k: K, ...keys: string[]) => {
    const v = pick(raw, k as string, ...keys)
    if (v !== undefined) out[k] = v as Robot[K]
  }
  set('name')
  set('state', 'status')
  set('battery', 'battery_pct')
  set('x')
  set('y')
  set('targetRoom', 'target_room')
  set('callId', 'call_id')
  return out
}

function normalizeAlert(raw: Raw, prev?: Alert): Alert {
  const base: Alert = prev ?? { id: String(raw.id), callId: null, room: null, urgency: 4, message: '', createdAt: Date.now(), acknowledged: false }
  const out = { ...base, id: String(raw.id) } as Alert
  const call = pick(raw, 'callId', 'call_id')
  if (call !== undefined) out.callId = String(call)
  const room = pick(raw, 'room', 'room_number')
  if (room !== undefined) out.room = Number(room)
  const urgency = pick(raw, 'urgency', 'level', 'score')
  if (urgency !== undefined) out.urgency = urgency as Urgency
  const message = pick(raw, 'message', 'title', 'summary', 'text')
  if (message !== undefined) out.message = String(message)
  const ack = pick(raw, 'acknowledged', 'resolved')
  if (ack !== undefined) out.acknowledged = Boolean(ack)
  out.createdAt = toMs(pick(raw, 'createdAt', 'created_at'), base.createdAt) ?? base.createdAt
  return out
}

function normalizeMetrics(body: unknown): Metrics | null {
  if (!body || typeof body !== 'object') return null
  const out: Metrics = {}
  for (const [k, v] of Object.entries(body as Raw)) if (typeof v === 'number' || typeof v === 'string') out[k] = v
  return Object.keys(out).length ? out : null
}

const list = (body: unknown, key: string): Raw[] => {
  if (Array.isArray(body)) return body as Raw[]
  const inner = (body as Raw | null)?.[key]
  return Array.isArray(inner) ? (inner as Raw[]) : []
}

function upsert<T extends Entity>(items: T[], next: T): T[] {
  const i = items.findIndex(x => x.id === next.id)
  if (i === -1) return [next, ...items]
  const copy = items.slice()
  copy[i] = next
  return copy
}

export function createLiveSource(): DataSource {
  let snapshot: Snapshot = staticSnapshot()
  snapshot = { ...snapshot, calls: [], robots: [], alerts: [], metrics: null }
  const listeners = new Set<() => void>()
  let source: EventSource | null = null
  let pollTimer: number | undefined
  let stopped = true

  const emit = () => listeners.forEach(l => l())
  const patch = (p: Partial<Snapshot>) => {
    snapshot = { ...snapshot, ...p, now: Date.now() }
    emit()
  }

  const headers = (): HeadersInit => (API_KEY ? { 'X-API-Key': API_KEY } : {})
  const getJson = async (path: string) => {
    const res = await fetch(`${API}${path}`, { headers: headers() })
    if (!res.ok) throw new Error(`${path} ${res.status}`)
    return res.json()
  }

  const refreshAll = async () => {
    try {
      const [calls, alerts, robots, metrics] = await Promise.all([getJson('/calls'), getJson('/alerts'), getJson('/robots'), getJson('/metrics')])
      if (stopped) return
      const prevCalls = new Map(snapshot.calls.map(c => [c.id, c]))
      const prevRobots = new Map(snapshot.robots.map(r => [r.id, r]))
      const prevAlerts = new Map(snapshot.alerts.map(a => [a.id, a]))
      patch({
        calls: list(calls, 'calls').map(r => normalizeCall(r, prevCalls.get(String(r.id)))),
        robots: list(robots, 'robots').map(r => normalizeRobot(r, prevRobots.get(String(r.id)))),
        alerts: list(alerts, 'alerts').map(r => normalizeAlert(r, prevAlerts.get(String(r.id)))),
        metrics: normalizeMetrics(metrics),
      })
    } catch {
      // backend unreachable: keep the last known state and retry via polling
    }
  }

  // Events carry calls and robots, not rollups, so refresh metrics shortly after call activity.
  let metricsTimer: number | undefined
  const refreshMetricsSoon = () => {
    window.clearTimeout(metricsTimer)
    metricsTimer = window.setTimeout(async () => {
      try {
        const m = normalizeMetrics(await getJson('/metrics'))
        if (!stopped) patch({ metrics: m })
      } catch {
        // keep the previous metrics
      }
    }, 1000)
  }

  const onEvent = (key: 'call' | 'robot' | 'alert') => (e: Event) => {
    try {
      const data = JSON.parse((e as MessageEvent).data) as Raw
      const obj = data[key] as Raw | undefined
      if (!obj || obj.id === undefined) return
      if (key === 'call') {
        const prev = snapshot.calls.find(c => c.id === String(obj.id))
        patch({ calls: upsert(snapshot.calls, normalizeCall(obj, prev)) })
        refreshMetricsSoon()
      } else if (key === 'robot') {
        const prev = snapshot.robots.find(r => r.id === String(obj.id))
        patch({ robots: upsert(snapshot.robots, normalizeRobot(obj, prev)) })
      } else {
        const prev = snapshot.alerts.find(a => a.id === String(obj.id))
        patch({ alerts: upsert(snapshot.alerts, normalizeAlert(obj, prev)) })
      }
    } catch {
      // ignore malformed frames
    }
  }

  const connect = () => {
    const qs = API_KEY ? `?api_key=${encodeURIComponent(API_KEY)}` : ''
    const es = new EventSource(`${API}/events${qs}`)
    const names: [string, 'call' | 'robot' | 'alert'][] = [
      ['call.raised', 'call'],
      ['call.assigned', 'call'],
      ['call.scored', 'call'],
      ['call.resolved', 'call'],
      ['alert.raised', 'alert'],
      ['robot.updated', 'robot'],
    ]
    names.forEach(([n, k]) => es.addEventListener(n, onEvent(k)))
    // EventSource reconnects on its own; never open a second one here.
    es.onerror = () => void refreshAll()
    return es
  }

  return {
    subscribe: fn => {
      listeners.add(fn)
      return () => {
        listeners.delete(fn)
      }
    },
    getSnapshot: () => snapshot,
    actions: {
      // No backend endpoint for these yet: apply locally so the UI responds.
      nurseOnMyWay: id =>
        patch({ calls: snapshot.calls.map(c => (c.id === id ? { ...c, status: 'nurse_en_route' } : c)) }),
      resolve: id =>
        patch({ calls: snapshot.calls.map(c => (c.id === id ? { ...c, status: 'resolved', resolvedAt: Date.now() } : c)) }),
      // Residents are still on the mock base, so staff entries are applied locally too.
      refineEntry: refineLocally,
      addEntry: (residentId, entry) =>
        patch({ residents: snapshot.residents.map(r => (r.id === residentId ? applyEntry(r, entry, Date.now()) : r)) }),
    },
    start: () => {
      stopped = false
      void refreshAll().then(() => {
        if (stopped || source) return
        source = connect()
      })
      pollTimer = window.setInterval(() => {
        if (!source || source.readyState !== EventSource.OPEN) void refreshAll()
      }, POLL_MS)
    },
    stop: () => {
      stopped = true
      window.clearTimeout(metricsTimer)
      source?.close()
      source = null
      window.clearInterval(pollTimer)
    },
  }
}
