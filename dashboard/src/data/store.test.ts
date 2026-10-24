import { afterEach, describe, expect, it, vi } from 'vitest'
import callsList from '../../../contracts/examples/calls_list.json'
import alertsJson from '../../../contracts/examples/alerts.json'
import robotsJson from '../../../contracts/examples/robots.json'
import metricsJson from '../../../contracts/examples/metrics.json'
import nursesJson from '../../../contracts/examples/nurses_list.json'
import pendingJson from '../../../contracts/examples/memory_pending.json'
import residentsJson from '../../../contracts/examples/residents_list.json'
import { LiveStore } from './store'

type Reply = unknown | ((init: RequestInit) => unknown)

/** A backend that answers from the contract examples, and remembers what it was asked. */
function fakeBackend(overrides: Record<string, Reply> = {}, empty = false) {
  const seen: { method: string; path: string; body: unknown }[] = []
  const routes: Record<string, Reply> = {
    'GET /calls': empty ? [] : callsList,
    'GET /alerts': empty ? [] : alertsJson,
    'GET /robots': robotsJson,
    'GET /nurses': nursesJson,
    'GET /metrics': metricsJson,
    'GET /residents': empty ? [] : residentsJson.slice(0, 1),
    'GET /residents/res_margaret/preferences': { resident_id: 'res_margaret', hard_of_hearing: false },
    'GET /residents/res_margaret/memory/all': [],
    'GET /residents/res_margaret/memory/pending': pendingJson,
    'GET /residents/res_margaret/medical': { resident_id: 'res_margaret', conditions: [], allergies: [], medicines: [], mobility: '', diet: '', last_review: null, reviewed_by: '' },
    'GET /residents/res_margaret/care/history': [],
    ...overrides,
  }
  const fetchFn = (async (url: string, init: RequestInit = {}) => {
    const path = new URL(url).pathname
    const method = init.method ?? 'GET'
    seen.push({ method, path, body: init.body ? JSON.parse(String(init.body)) : undefined })
    const hit = routes[`${method} ${path}`] ?? (method === 'GET' ? routes[`GET ${path.replace(/\/[^/]+$/, '')}`] : undefined)
    if (hit === undefined) return new Response(JSON.stringify({ detail: 'not found' }), { status: 404 })
    const value = typeof hit === 'function' ? hit(init) : hit
    if (value instanceof Response) return value
    return new Response(JSON.stringify(value), { status: 200 })
  }) as typeof fetch
  return { fetchFn, seen }
}

const NOW = new Date('2026-10-24T22:00:00Z').getTime()
const quietStream = () => ({ addEventListener() {}, close() {} }) as unknown as EventSource
const make = (b: ReturnType<typeof fakeBackend>) => new LiveStore({ baseUrl: 'http://bellhop.test/', fetchFn: b.fetchFn, now: () => NOW, eventSource: quietStream })

describe('loading', () => {
  it('turns the backend responses into the screens view model', async () => {
    const store = make(fakeBackend())
    await Promise.all([store.loadLive(), store.loadResidents()])
    const snap = store.getSnapshot()
    expect(snap.calls.map((c) => c.id).sort()).toEqual((callsList as { id: string }[]).map((c) => c.id).sort())
    expect(snap.alerts).toHaveLength(alertsJson.length)
    expect(snap.robots[0]).toMatchObject({ id: 'robot_1', battery: 100 })
    expect(snap.nurses).toHaveLength(nursesJson.length)
    expect(snap.metrics).toMatchObject({ resolved_without_nurse: 1 })
    expect(snap.residents[0]).toMatchObject({ id: 'res_margaret', room: '12' })
    expect(snap.residents[0].learned.map((f) => f.status)).toEqual(['pending'])
  })

  it('asks for every call the backend will give, and sends the API key', async () => {
    const b = fakeBackend()
    const store = new LiveStore({ baseUrl: 'http://bellhop.test', apiKey: 'k', fetchFn: ((url: string, init: RequestInit) => {
      expect((init.headers as Record<string, string>)['X-API-Key']).toBe('k')
      return b.fetchFn(url, init)
    }) as typeof fetch, now: () => NOW })
    await store.loadLive()
    expect(b.seen.find((r) => r.path === '/calls')).toBeDefined()
  })

  it('an empty backend is an empty home, not an error', async () => {
    const store = make(fakeBackend({}, true))
    store.start()
    await vi.waitFor(() => expect(store.getSnapshot().connection.state).toBe('live'))
    expect(store.getSnapshot().connection).toMatchObject({ empty: true, problem: null })
    store.stop()
  })
})

describe('connection', () => {
  afterEach(() => vi.useRealTimers())

  it('says so when the backend cannot be reached, and keeps trying', async () => {
    let up = false
    const b = fakeBackend()
    const store = new LiveStore({ baseUrl: 'http://bellhop.test', now: () => NOW, fetchFn: ((url: string, init: RequestInit) => (up ? b.fetchFn(url, init) : Promise.reject(new Error('connection refused')))) as typeof fetch, eventSource: quietStream })
    store.start()
    await vi.waitFor(() => expect(store.getSnapshot().connection.state).toBe('offline'))
    expect(store.getSnapshot().connection.problem).toMatch(/Cannot reach Bellhop at http:\/\/bellhop.test/)
    up = true
    await vi.waitFor(() => expect(store.getSnapshot().connection.state).toBe('live'), { timeout: 6000 })
    expect(store.getSnapshot().connection.problem).toBeNull()
    store.stop()
  })
})

describe('live events', () => {
  it('a resolved call replaces the open one and an alert and robot update land too', async () => {
    const store = make(fakeBackend())
    await store.loadLive()
    const open = callsList[0] as { id: string }
    store.onEvent('call.resolved', { call: { ...callsList[0], status: 'resolved', resolved_at: '2026-10-24T21:50:00Z', resolved_by_robot: false } })
    expect(store.getSnapshot().calls.find((c) => c.id === open.id)?.status).toBe('resolved')
    store.onEvent('alert.raised', { alert: { id: 'a9', call_id: open.id, nurse_id: 'nurse_sam', level: 3, message: 'New', created_at: '2026-10-24T21:51:00Z', acked_at: null } })
    expect(store.getSnapshot().alerts.some((a) => a.id === 'a9')).toBe(true)
    store.onEvent('robot.updated', { robot: { id: 'robot_1', status: 'charging', battery: 0.2, room: 'dock' } })
    expect(store.getSnapshot().robots[0]).toMatchObject({ state: 'charging', battery: 20 })
  })
})

describe('actions', () => {
  it('"on my way" acknowledges the call alert as the nurse it was sent to', async () => {
    const b = fakeBackend({ 'POST /alerts/alert_nurse/ack': {} })
    const store = make(b)
    await store.loadLive()
    store.onEvent('alert.raised', { alert: { id: 'alert_nurse', call_id: 'call_x', nurse_id: 'nurse_sam', level: 3, message: 'Pain', created_at: '2026-10-24T21:51:00Z', acked_at: null } })
    await store.actions.nurseOnMyWay('call_x')
    expect(b.seen.find((r) => r.method === 'POST')).toEqual({ method: 'POST', path: '/alerts/alert_nurse/ack', body: { nurse_id: 'nurse_sam' } })
  })

  it('a broadcast alert is answered by the on-shift nurse with the fewest tasks', async () => {
    const b = fakeBackend({ 'POST /alerts/alert_dab9346d/ack': {}, 'GET /nurses': [{ id: 'busy', name: 'B', on_shift: true, open_tasks: 3 }, { id: 'free', name: 'F', on_shift: true, open_tasks: 0 }, { id: 'off', name: 'O', on_shift: false, open_tasks: 0 }] })
    const store = make(b)
    await store.loadLive()
    await store.actions.nurseOnMyWay((alertsJson[0] as { call_id: string }).call_id)
    expect(b.seen.find((r) => r.method === 'POST')?.body).toEqual({ nurse_id: 'free' })
  })

  it('a failed action is shown to staff instead of being lost', async () => {
    const b = fakeBackend({ 'POST /calls/call_x/resolve': () => new Response(JSON.stringify({ detail: 'illegal state change' }), { status: 409 }) })
    const store = make(b)
    store.start()
    await vi.waitFor(() => expect(store.getSnapshot().connection.state).toBe('live'))
    await store.actions.resolve('call_x')
    expect(store.getSnapshot().connection.problem).toBe('illegal state change')
    store.stop()
  })

  it('driving a robot posts the target, and the answer updates the robot at once', async () => {
    const robot = { id: 'robot_9', status: 'busy', battery: 0.9, room: 'lobby' }
    const b = fakeBackend({ 'POST /robots/robot_9/navigate': robot })
    const store = make(b)
    await store.loadLive()
    expect(await store.actions.driveRobot('robot_9', '104')).toBe(true)
    expect(b.seen.find((r) => r.method === 'POST')).toEqual({ method: 'POST', path: '/robots/robot_9/navigate', body: { target: '104' } })
    expect(store.getSnapshot().robots.find((r) => r.id === 'robot_9')?.state).toBe('en_route')
  })

  it('a robot that refuses the drive says why and returns false', async () => {
    const b = fakeBackend({ 'POST /robots/robot_1/navigate': () => new Response(JSON.stringify({ detail: 'robot robot_1 is not idle' }), { status: 409 }) })
    const store = make(b)
    store.start()
    await vi.waitFor(() => expect(store.getSnapshot().connection.state).toBe('live'))
    expect(await store.actions.driveRobot('robot_1', '104')).toBe(false)
    expect(store.getSnapshot().connection.problem).toBe('robot robot_1 is not idle')
    store.stop()
  })

  it('stopping a robot posts to its stop route and shows it standing by', async () => {
    const b = fakeBackend({ 'POST /robots/robot_9/stop': { id: 'robot_9', status: 'idle', battery: 0.9, room: 'lobby' } })
    const store = make(b)
    await store.loadLive()
    expect(await store.actions.stopRobot('robot_9')).toBe(true)
    expect(b.seen.find((r) => r.method === 'POST')?.path).toBe('/robots/robot_9/stop')
    expect(store.getSnapshot().robots.find((r) => r.id === 'robot_9')?.state).toBe('idle')
  })

  it('a robot the Pi cannot reach reports the failure instead of pretending', async () => {
    const b = fakeBackend({ 'POST /robots/robot_1/stop': () => new Response(JSON.stringify({ detail: 'robot stop command failed' }), { status: 503 }) })
    const store = make(b)
    store.start()
    await vi.waitFor(() => expect(store.getSnapshot().connection.state).toBe('live'))
    expect(await store.actions.stopRobot('robot_1')).toBe(false)
    expect(store.getSnapshot().connection.problem).toBe('robot stop command failed')
    store.stop()
  })

  it('adding a resident posts the resident, saves hearing, and loads them back', async () => {
    const created = { id: 'res_new', name: 'Ada Reyes', room: '21', risk_flags: ['falls'], birth_year: 1941 }
    let residents: unknown[] = []
    const b = fakeBackend({
      'GET /residents': () => residents,
      'POST /residents': () => {
        residents = [created]
        return new Response(JSON.stringify(created), { status: 201 })
      },
      'PUT /residents/res_new/preferences': { resident_id: 'res_new', hard_of_hearing: true },
      'GET /residents/res_new/preferences': { resident_id: 'res_new', hard_of_hearing: true },
      'GET /residents/res_new/memory/all': [],
      'GET /residents/res_new/memory/pending': [],
      'GET /residents/res_new/medical': { resident_id: 'res_new', conditions: [], allergies: [], medicines: [], mobility: '', diet: '', last_review: null, reviewed_by: '' },
      'GET /residents/res_new/care/history': [],
    })
    const store = make(b)
    const id = await store.actions.addResident({ name: 'Ada Reyes', room: '21', birthYear: 1941, riskFlags: ['falls'], hardOfHearing: true })
    expect(id).toBe('res_new')
    const post = b.seen.find((r) => r.method === 'POST')
    expect(post).toEqual({ method: 'POST', path: '/residents', body: { name: 'Ada Reyes', room: '21', risk_flags: ['falls'], birth_year: 1941 } })
    expect(b.seen.some((r) => r.method === 'PUT' && r.path === '/residents/res_new/preferences')).toBe(true)
    expect(store.getSnapshot().residents.map((r) => [r.id, r.room, r.hardOfHearing, r.flags])).toEqual([['res_new', '21', true, ['Fall risk', 'Hard of hearing']]])
  })

  it('a room the backend refuses comes back as the reason, not a banner', async () => {
    const b = fakeBackend({ 'POST /residents': () => new Response(JSON.stringify({ detail: 'room 21 is occupied' }), { status: 409 }) })
    await expect(make(b).actions.addResident({ name: 'Ada', room: '21', birthYear: null, riskFlags: [], hardOfHearing: false })).rejects.toThrow('room 21 is occupied')
  })

  it('moving a resident patches their room and keeps the rest', async () => {
    const b = fakeBackend({
      'PATCH /residents/res_margaret': { id: 'res_margaret', name: 'Margaret', room: '30', risk_flags: ['falls'], birth_year: 1938 },
      'PUT /residents/res_margaret/preferences': { resident_id: 'res_margaret', hard_of_hearing: false },
      'GET /residents': [{ id: 'res_margaret', name: 'Margaret', room: '30', risk_flags: ['falls'], birth_year: 1938 }],
    })
    const store = make(b)
    await store.loadResidents()
    await store.actions.updateResident('res_margaret', { name: 'Margaret', room: '30', birthYear: 1938, riskFlags: ['falls'], hardOfHearing: false })
    expect(b.seen.find((r) => r.method === 'PATCH')).toEqual({ method: 'PATCH', path: '/residents/res_margaret', body: { name: 'Margaret', room: '30', risk_flags: ['falls'], birth_year: 1938 } })
    expect(store.getSnapshot().residents[0].room).toBe('30')
  })

  it('marking a call done resolves it as staff, not as the robot', async () => {
    const b = fakeBackend({ 'POST /calls/call_x/resolve': {} })
    await make(b).actions.resolve('call_x')
    expect(b.seen.find((r) => r.method === 'POST')?.body).toEqual({ by_robot: false })
  })

  it('approving or rejecting a pending fact calls the matching route and reloads the resident', async () => {
    const b = fakeBackend({ 'POST /residents/res_margaret/memory/pending/pending-1/approve': {}, 'POST /residents/res_margaret/memory/pending/pending-1/reject': {} })
    const store = make(b)
    await store.loadResidents()
    await store.actions.reviewFact('res_margaret', 'pending-1', 'approve')
    await store.actions.reviewFact('res_margaret', 'pending-1', 'reject')
    expect(b.seen.filter((r) => r.method === 'POST').map((r) => r.path)).toEqual(['/residents/res_margaret/memory/pending/pending-1/approve', '/residents/res_margaret/memory/pending/pending-1/reject'])
  })

  it('tidying a note asks the backend and returns its wording without saving', async () => {
    const b = fakeBackend({ 'POST /residents/res_margaret/notes/refine': { category: 'condition', text: 'High blood pressure', since: '2015', notes: ['Expanded htn'] } })
    const out = await make(b).actions.refineEntry('res_margaret', { category: 'condition', text: 'htn since 2015' })
    expect(out).toEqual({ category: 'condition', text: 'High blood pressure', since: '2015', notes: ['Expanded htn'] })
    expect(b.seen.filter((r) => r.method === 'POST')).toHaveLength(1)
  })

  it('a like goes to memory as a staff fact, a condition goes to the medical history', async () => {
    const b = fakeBackend({ 'POST /residents/res_margaret/memory': {}, 'POST /residents/res_margaret/medical/entries': {} })
    const store = make(b)
    await store.loadResidents()
    await store.actions.addEntry('res_margaret', { category: 'like', text: 'Likes tea', notes: [] })
    await store.actions.addEntry('res_margaret', { category: 'condition', text: 'COPD', since: '2018', notes: [] })
    const posts = b.seen.filter((r) => r.method === 'POST')
    expect(posts[0]).toEqual({ method: 'POST', path: '/residents/res_margaret/memory', body: { text: 'Likes tea', tags: ['like'], source: 'staff', confidence: 1 } })
    expect(posts[1]).toEqual({ method: 'POST', path: '/residents/res_margaret/medical/entries', body: { category: 'condition', text: 'COPD', since: '2018' } })
  })

  it('a note the backend refuses says why in plain words', async () => {
    const b = fakeBackend({ 'POST /residents/res_margaret/memory': () => new Response(JSON.stringify({ detail: 'duplicate' }), { status: 422 }) })
    const store = make(b)
    store.start()
    await vi.waitFor(() => expect(store.getSnapshot().connection.state).toBe('live'))
    await store.actions.addEntry('res_margaret', { category: 'like', text: 'Likes tea', notes: [] })
    expect(store.getSnapshot().connection.problem).toBe('Bellhop already has that note.')
    store.stop()
  })
})
