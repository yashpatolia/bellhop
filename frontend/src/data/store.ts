import type { ApiAlert, ApiCall, ApiMetrics, ApiNurse, ApiResident, ApiRobot, ApiRefined, ApiFact, ApiPending, ApiMedical, ApiCare, ApiPrefs } from '../api/types'
import type { Actions, Call, Category, EntryCategory, RefinedEntry, Resident, Snapshot } from './types'
import type { DataSource } from './source'
import { hourlyCounts, splitCalls, toAlert, toCall, toMetrics, toNurse, toResident, toRobot, type ResidentParts } from './adapt'
import { FACT_KIND_OF, isFactCategory } from './staffEntries'

// The one place that talks to the backend. REST for the first load and for recovery, one SSE
// stream (GET /events) for updates, a slow poll as a safety net. Everything it hands to the
// screens is the view model from types.ts, built by adapt.ts.

const POLL_MS = 10_000
const RETRY_MS = 3_000
const PROBLEM_MS = 8_000
const MAX_CALLS = 1000
const EVENTS = ['call.raised', 'call.assigned', 'call.scored', 'call.resolved', 'alert.raised', 'robot.updated'] as const

export interface StoreOptions {
  baseUrl: string
  apiKey?: string
  fetchFn?: typeof fetch
  eventSource?: (url: string) => EventSource
  now?: () => number
}

export class ApiError extends Error {
  readonly status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

type Raw = {
  calls: Map<string, ApiCall>
  alerts: Map<string, ApiAlert>
  robots: Map<string, ApiRobot>
  nurses: ApiNurse[]
  metrics: ApiMetrics
  residents: ApiResident[]
  parts: Map<string, ResidentParts>
}

const EMPTY_PARTS: ResidentParts = { prefs: null, facts: [], pending: [], medical: null, care: [] }

const PROBLEM_TEXT: Record<string, string> = {
  duplicate: 'Bellhop already has that note.',
  too_short: 'That note is too short.',
  too_long: 'That note is too long.',
  clinical_claim: 'Notes about diagnoses and doses belong in the medical history, not in what Bellhop learns.',
}

export class LiveStore {
  private raw: Raw = { calls: new Map(), alerts: new Map(), robots: new Map(), nurses: [], metrics: {}, residents: [], parts: new Map() }
  private snapshot: Snapshot
  private listeners = new Set<() => void>()
  private dirty = true
  private tick: ReturnType<typeof setInterval> | undefined
  private poll: ReturnType<typeof setInterval> | undefined
  private retry: ReturnType<typeof setTimeout> | undefined
  private problemTimer: ReturnType<typeof setTimeout> | undefined
  private stream: EventSource | null = null
  private running = false
  private connection: Snapshot['connection'] = { state: 'connecting', problem: null, empty: false }
  private readonly base: string
  private readonly fetchFn: typeof fetch
  private readonly clock: () => number

  private readonly opts: StoreOptions

  constructor(opts: StoreOptions) {
    this.opts = opts
    this.base = opts.baseUrl.replace(/\/$/, '')
    this.fetchFn = opts.fetchFn ?? ((...a) => fetch(...a))
    this.clock = opts.now ?? Date.now
    this.snapshot = this.build()
  }

  // -- DataSource -----------------------------------------------------------------------------
  subscribe = (fn: () => void) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }
  getSnapshot = () => this.snapshot

  start = () => {
    if (this.running) return
    this.running = true
    this.tick = setInterval(() => this.publish(), 1000)
    void this.connect()
  }

  stop = () => {
    this.running = false
    clearInterval(this.tick)
    clearInterval(this.poll)
    clearTimeout(this.retry)
    clearTimeout(this.problemTimer)
    this.stream?.close()
    this.stream = null
  }

  // -- loading --------------------------------------------------------------------------------
  private async connect() {
    try {
      await Promise.all([this.loadLive(), this.loadResidents()])
    } catch (e) {
      this.goOffline(e)
      return
    }
    this.setConnection({ state: 'live', problem: null })
    this.openStream()
    clearInterval(this.poll)
    this.poll = setInterval(() => void this.refresh(), POLL_MS)
  }

  private goOffline(e: unknown) {
    const why = e instanceof Error ? e.message : 'unknown error'
    this.setConnection({ state: 'offline', problem: `Cannot reach Bellhop at ${this.base} (${why}). Trying again.` })
    this.stream?.close()
    this.stream = null
    clearInterval(this.poll)
    clearTimeout(this.retry)
    if (this.running) this.retry = setTimeout(() => void this.connect(), RETRY_MS)
  }

  /** Calls, alerts, robots, nurses and metrics: everything the live screen shows. */
  async loadLive() {
    const [calls, alerts, robots, nurses, metrics] = await Promise.all([
      this.get<ApiCall[]>(`/calls?limit=${MAX_CALLS}`),
      this.get<ApiAlert[]>('/alerts?limit=1000'),
      this.get<ApiRobot[]>('/robots'),
      this.get<ApiNurse[]>('/nurses'),
      this.get<ApiMetrics>('/metrics'),
    ])
    this.raw.calls = new Map(calls.map((c) => [c.id, c]))
    this.raw.alerts = new Map(alerts.map((a) => [a.id, a]))
    this.raw.robots = new Map(robots.map((r) => [r.id, r]))
    this.raw.nurses = nurses
    this.raw.metrics = metrics
    this.touch()
  }

  async loadResidents() {
    const residents = await this.get<ApiResident[]>('/residents')
    this.raw.residents = residents
    const loaded = await Promise.all(residents.map((r) => this.fetchParts(r.id)))
    this.raw.parts = new Map(residents.map((r, i) => [r.id, loaded[i]]))
    this.touch()
  }

  /** After adding or changing a resident: take the new list, then everything known about them. */
  private async reloadResident(id: string) {
    this.raw.residents = await this.get<ApiResident[]>('/residents')
    this.raw.parts.set(id, await this.fetchParts(id))
    this.touch()
  }

  async refreshResident(id: string) {
    if (!this.raw.residents.some((r) => r.id === id)) return
    this.raw.parts.set(id, await this.fetchParts(id))
    this.touch()
  }

  private async fetchParts(id: string): Promise<ResidentParts> {
    const [prefs, facts, pending, medical, care] = await Promise.all([
      this.get<ApiPrefs>(`/residents/${id}/preferences`),
      this.get<ApiFact[]>(`/residents/${id}/memory/all`),
      this.get<ApiPending[]>(`/residents/${id}/memory/pending`),
      this.get<ApiMedical>(`/residents/${id}/medical`),
      this.get<ApiCare[]>(`/residents/${id}/care/history?days=14`),
    ])
    return { prefs, facts, pending, medical, care }
  }

  private async refresh() {
    try {
      await this.loadLive()
      if (this.connection.state !== 'live') this.setConnection({ state: 'live', problem: null })
    } catch (e) {
      this.goOffline(e)
    }
  }

  // -- live events ----------------------------------------------------------------------------
  private openStream() {
    this.stream?.close()
    const key = this.opts.apiKey ? `?api_key=${encodeURIComponent(this.opts.apiKey)}` : ''
    const url = `${this.base}/events${key}`
    const es = this.opts.eventSource ? this.opts.eventSource(url) : new EventSource(url)
    this.stream = es
    // Events missed while disconnected are not replayed: refetch on every (re)connect.
    es.addEventListener('open', () => void this.refresh())
    for (const name of EVENTS) es.addEventListener(name, (e) => this.onEvent(name, JSON.parse((e as MessageEvent).data)))
  }

  onEvent(name: (typeof EVENTS)[number], data: Record<string, unknown>) {
    if (name === 'alert.raised' && data.alert) this.raw.alerts.set((data.alert as ApiAlert).id, data.alert as ApiAlert)
    else if (name === 'robot.updated' && data.robot) this.raw.robots.set((data.robot as ApiRobot).id, data.robot as ApiRobot)
    else if (data.call) {
      const call = data.call as ApiCall
      this.raw.calls.set(call.id, call)
      if (name === 'call.resolved') this.afterResolved(call)
    }
    this.touch()
  }

  /** A resolved call may teach Bellhop something (learning runs in the background): look again shortly. */
  private afterResolved(call: ApiCall) {
    setTimeout(() => {
      if (!this.running) return
      void this.get<ApiMetrics>('/metrics').then((m) => {
        this.raw.metrics = m
        this.touch()
      }, () => {})
      if (call.resident_id) void this.refreshResident(call.resident_id).catch(() => {})
    }, 2500)
  }

  // -- actions --------------------------------------------------------------------------------
  actions: Actions = {
    nurseOnMyWay: (callId) =>
      this.guard(async () => {
        const alert = [...this.raw.alerts.values()]
          .filter((a) => a.call_id === callId && !a.acked_at)
          .sort((a, b) => b.level - a.level)[0]
        if (!alert) throw new Error('There is no alert to answer for this call yet.')
        const nurse = alert.nurse_id ?? this.pickNurse()
        await this.send('POST', `/alerts/${alert.id}/ack`, { nurse_id: nurse })
        await this.loadLive()
      }),
    driveRobot: (robotId, target) => this.command(robotId, 'navigate', { target }),
    stopRobot: (robotId) => this.command(robotId, 'stop'),
    addRobot: async (robotId, room) => {
      // Offline until the robot itself reports in: it takes no calls before then.
      const robot = await this.send<ApiRobot>('PUT', `/robots/${encodeURIComponent(robotId)}`, { status: 'offline', battery: 0, room })
      this.raw.robots.set(robot.id, robot)
      this.touch()
    },
    resolve: (callId) =>
      this.guard(async () => {
        await this.send('POST', `/calls/${callId}/resolve`, { by_robot: false })
        await this.loadLive()
      }),
    addResident: async (input) => {
      const created = await this.send<ApiResident>('POST', '/residents', {
        name: input.name,
        room: input.room,
        risk_flags: input.riskFlags,
        ...(input.birthYear ? { birth_year: input.birthYear } : {}),
      })
      if (input.hardOfHearing) await this.send('PUT', `/residents/${created.id}/preferences`, { hard_of_hearing: true })
      await this.reloadResident(created.id)
      return created.id
    },
    updateResident: async (residentId, input) => {
      await this.send('PATCH', `/residents/${residentId}`, {
        name: input.name,
        room: input.room,
        risk_flags: input.riskFlags,
        birth_year: input.birthYear,
      })
      await this.send('PUT', `/residents/${residentId}/preferences`, { hard_of_hearing: input.hardOfHearing })
      await this.reloadResident(residentId)
    },
    refineEntry: async (residentId, draft) => {
      const out = await this.send<ApiRefined>('POST', `/residents/${residentId}/notes/refine`, draft)
      return { category: out.category as EntryCategory, text: out.text, since: out.since ?? undefined, notes: out.notes ?? [] }
    },
    addEntry: (residentId, entry) =>
      this.guard(async () => {
        await this.saveEntry(residentId, entry)
        await this.refreshResident(residentId)
      }),
    reviewFact: (residentId, factId, decision) =>
      this.guard(async () => {
        await this.send('POST', `/residents/${residentId}/memory/pending/${factId}/${decision}`)
        await this.refreshResident(residentId)
      }),
  }

  private async saveEntry(residentId: string, entry: RefinedEntry) {
    if (isFactCategory(entry.category)) {
      const body = { text: entry.text, tags: [FACT_KIND_OF[entry.category]!], source: 'staff', confidence: 1 }
      await this.send('POST', `/residents/${residentId}/memory`, body)
    } else {
      await this.send('POST', `/residents/${residentId}/medical/entries`, { category: entry.category, text: entry.text, since: entry.since })
    }
  }

  /** A manual robot command. The backend answers with the robot, so the screen updates at once. */
  private async command(robotId: string, what: 'navigate' | 'stop', body?: unknown): Promise<boolean> {
    try {
      const robot = await this.send<ApiRobot>('POST', `/robots/${encodeURIComponent(robotId)}/${what}`, body)
      this.raw.robots.set(robot.id, robot)
      this.touch()
      return true
    } catch (e) {
      this.showProblem(e instanceof Error ? e.message : 'The robot did not take that command.')
      return false
    }
  }

  private pickNurse(): string {
    const onShift = this.raw.nurses.filter((n) => n.on_shift).sort((a, b) => a.open_tasks - b.open_tasks)
    if (!onShift.length) throw new Error('No nurse is on shift to take this.')
    return onShift[0].id
  }

  /** Run an action; a failure is shown to staff for a few seconds instead of being lost. */
  private async guard(fn: () => Promise<void>) {
    try {
      await fn()
    } catch (e) {
      this.showProblem(e instanceof Error ? e.message : 'That did not work.')
    }
  }

  private showProblem(text: string) {
    clearTimeout(this.problemTimer)
    this.setConnection({ problem: text })
    this.problemTimer = setTimeout(() => {
      if (this.connection.state === 'live') this.setConnection({ problem: null })
    }, PROBLEM_MS)
  }

  // -- http -----------------------------------------------------------------------------------
  private headers(): HeadersInit {
    return { 'Content-Type': 'application/json', ...(this.opts.apiKey ? { 'X-API-Key': this.opts.apiKey } : {}) }
  }

  private async get<T>(path: string): Promise<T> {
    return this.send<T>('GET', path)
  }

  private async send<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
    const res = await this.fetchFn(`${this.base}${path}`, { method, headers: this.headers(), body: body === undefined ? undefined : JSON.stringify(body) })
    if (!res.ok) {
      let detail = ''
      try {
        const j = await res.json()
        detail = typeof j.detail === 'string' ? j.detail : ''
      } catch {
        /* no body */
      }
      throw new ApiError(PROBLEM_TEXT[detail] ?? (detail || `${method} ${path} failed (${res.status})`), res.status)
    }
    if (res.status === 202) return (await res.json()) as T
    return res.status === 204 ? (undefined as T) : ((await res.json()) as T)
  }

  // -- snapshot -------------------------------------------------------------------------------
  private setConnection(patch: Partial<Snapshot['connection']>) {
    this.connection = { ...this.connection, ...patch }
    this.touch()
  }

  private touch() {
    this.dirty = true
    this.publish()
  }

  private publish() {
    this.snapshot = this.build()
    for (const fn of this.listeners) fn()
  }

  private cache: { calls: Call[]; today: Call[]; past: Call[]; alerts: ReturnType<typeof toAlert>[]; residents: Resident[] } | null = null

  private build(): Snapshot {
    const now = this.clock()
    if (this.dirty || !this.cache) {
      const calls = [...this.raw.calls.values()].map(toCall)
      const byId = new Map(calls.map((c) => [c.id, c]))
      const { today, past } = splitCalls(calls, now)
      const residents = this.raw.residents.map((r) => toResident(r, this.raw.parts.get(r.id) ?? EMPTY_PARTS, now))
      this.cache = { calls, today, past, alerts: [...this.raw.alerts.values()].map((a) => toAlert(a, byId)), residents }
      this.dirty = false
    }
    const c = this.cache
    return {
      now,
      calls: c.today,
      pastCalls: c.past,
      residents: c.residents,
      robots: [...this.raw.robots.values()].map((r) => toRobot(r, c.calls)),
      nurses: this.raw.nurses.map(toNurse),
      hourly: hourlyCounts(c.calls, now),
      alerts: c.alerts,
      metrics: toMetrics(this.raw.metrics),
      connection: { ...this.connection, empty: this.connection.state === 'live' && this.raw.residents.length === 0 && this.raw.calls.size === 0 },
    }
  }
}

export function createLiveSource(opts: StoreOptions): DataSource {
  return new LiveStore(opts)
}

export type { Category }
