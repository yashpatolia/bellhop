import { describe, expect, it } from 'vitest'
import callsList from '../../../contracts/examples/calls_list.json'
import resolvedByRobot from '../../../contracts/examples/call_resolved_by_robot.json'
import alertsJson from '../../../contracts/examples/alerts.json'
import robotsJson from '../../../contracts/examples/robots.json'
import metricsJson from '../../../contracts/examples/metrics.json'
import nursesJson from '../../../contracts/examples/nurses_list.json'
import pendingJson from '../../../contracts/examples/memory_pending.json'
import residentsJson from '../../../contracts/examples/residents_list.json'
import type { ApiAlert, ApiCall, ApiCare, ApiFact, ApiMedical, ApiRobot } from '../api/types'
import { categoryOf, dailySeries, flagsOf, handledByOf, hourlyCounts, kindOf, sourceOf, splitCalls, statusOf, toAlert, toCall, toFact, toMedical, toMetrics, toNurse, toPending, toResident, toRobot, urgencyOf } from './adapt'

const NOW = new Date(2026, 9, 24, 15, 0, 0).getTime()
const DAY = 86_400_000

const alertsList = alertsJson as ApiAlert[]
const call = (over: Partial<ApiCall> = {}): ApiCall => ({ ...(callsList[0] as ApiCall), ...over })

describe('a call from the contract', () => {
  it('reads the escalated emergency from calls_list.json', () => {
    const c = toCall(callsList[0] as ApiCall)
    expect(c).toMatchObject({ room: '12', residentId: 'res_margaret', urgency: 4, category: 'fall', status: 'nurse_notified', handledBy: 'nurse', robotId: null, resolvedAt: null })
    expect(c.createdAt).toBe(Date.parse((callsList[0] as ApiCall).created_at))
  })

  it('reads a call the robot resolved', () => {
    const c = toCall(resolvedByRobot as ApiCall)
    expect(c.status).toBe('resolved')
    expect(c.resolvedByRobot).toBe(true)
    expect(c.category).toBe('chat') // the triage model wrote "social"
    expect(c.handledBy).toBe('robot')
    expect(c.resolvedAt).not.toBeNull()
  })

  it('turns first_response_at into seconds from the bell', () => {
    const c = toCall(call({ created_at: '2026-10-24T10:00:00Z', first_response_at: '2026-10-24T10:01:30Z' }))
    expect(c.firstResponseSec).toBe(90)
  })

  it('keeps the transcript speakers the screens know about', () => {
    const c = toCall(call({ transcript: [{ speaker: 'resident', text: 'hi', at: '' }, { speaker: 'robot', text: 'hello', at: '' }, { speaker: 'nurse', text: 'on my way', at: '' }, { speaker: 'aide', text: '?', at: '' }] }))
    expect(c.transcript.map((t) => t.who)).toEqual(['resident', 'robot', 'nurse', 'robot'])
  })
})

describe('status', () => {
  it.each([
    [{ status: 'ringing', robot_id: null, nurse_tasks: [] }, 'waiting'],
    [{ status: 'ringing', robot_id: null, nurse_tasks: ['n1'] }, 'nurse_notified'],
    [{ status: 'assigned', robot_id: 'r1', nurse_tasks: [] }, 'robot_en_route'],
    [{ status: 'robot_en_route', robot_id: 'r1' }, 'robot_en_route'],
    [{ status: 'in_visit', robot_id: 'r1' }, 'robot_with_resident'],
    [{ status: 'escalated' }, 'nurse_notified'],
    [{ status: 'nurse_acked' }, 'nurse_en_route'],
    [{ status: 'resolved' }, 'resolved'],
    [{ status: 'closed' }, 'resolved'],
  ] as const)('%j is %s', (over, expected) => {
    expect(statusOf(call(over as Partial<ApiCall>))).toBe(expected)
  })

  it('a call nobody has scored yet is level 1, never an escalation', () => {
    expect(urgencyOf(null)).toBe(1)
    expect(urgencyOf(undefined)).toBe(1)
    expect(urgencyOf(4)).toBe(4)
  })

  it('who handles it follows the level, and a robot-less call belongs to a nurse', () => {
    expect(handledByOf(call({ urgency: 1, robot_id: 'r1', nurse_tasks: [] }))).toBe('robot')
    expect(handledByOf(call({ urgency: 2, robot_id: 'r1', nurse_tasks: [] }))).toBe('staff')
    expect(handledByOf(call({ urgency: 3, robot_id: 'r1' }))).toBe('nurse')
    expect(handledByOf(call({ urgency: 1, robot_id: null, nurse_tasks: ['n1'] }))).toBe('nurse')
  })

  it('categories the model invents show as other', () => {
    expect(categoryOf('Social')).toBe('chat')
    expect(categoryOf('bathroom')).toBe('toileting')
    expect(categoryOf('something odd')).toBe('other')
    expect(categoryOf(null)).toBe('other')
  })
})

describe('alerts and robots', () => {
  it('an alert knows its room from its call and whether it was answered', () => {
    const calls = new Map((callsList as ApiCall[]).map((c) => [c.id, toCall(c)]))
    const a = toAlert(alertsList[0], calls)
    expect(a).toMatchObject({ urgency: 4, room: '12', acknowledged: false, nurseId: null })
  })

  it('an alert is cleared when its call is resolved', () => {
    const resolved = toCall(call({ status: 'resolved', resolved_at: '2026-10-24T10:05:00Z' }))
    const a = toAlert({ ...alertsList[0], call_id: resolved.id }, new Map([[resolved.id, resolved]]))
    expect(a.clearedAt).toBe(Date.parse('2026-10-24T10:05:00Z'))
  })

  it('a busy robot with a call in the room is with the resident, battery as a percent', () => {
    const robot = robotsJson[0] as ApiRobot
    const calls = [toCall(call({ status: 'in_visit', robot_id: robot.id, room: '12' }))]
    expect(toRobot(robot, calls)).toMatchObject({ id: 'robot_1', name: 'Robot 1', state: 'with_resident', battery: 100, targetRoom: '12', callId: calls[0].id })
  })

  it('charging and fault come straight from the robot', () => {
    expect(toRobot({ id: 'b', status: 'charging', battery: 0.3, room: 'dock' }, []).state).toBe('charging')
    expect(toRobot({ id: 'b', status: 'fault', battery: 0.3, room: null }, []).state).toBe('fault')
    expect(toRobot({ id: 'b', status: 'offline', battery: 0, room: null }, []).state).toBe('offline')
  })

  it('a nurse keeps the shift and task count', () => {
    expect(toNurse(nursesJson[0])).toEqual({ id: 'nurse_priya', name: 'Priya', onShift: true, openTasks: 1 })
  })

  it('metrics keep the numbers and drop the nested breakdowns', () => {
    const m = toMetrics(metricsJson)
    expect(m).toMatchObject({ resolved_without_nurse: 1, minutes_saved: 4 })
    expect(m).not.toHaveProperty('calls_by_hour')
    expect(toMetrics({})).toBeNull()
  })
})

describe('what Bellhop knows', () => {
  const fact = (over: Partial<ApiFact> = {}): ApiFact => ({
    id: 'f1', resident_id: 'r1', text: 'Takes tea with two sugars', tags: ['like'], created_at: '2026-10-01T10:00:00Z',
    source: 'conversation', confidence: 0.9, quote: 'two sugars', call_id: 'c1', last_confirmed: '2026-10-20T10:00:00Z', times_seen: 4, ...over,
  })

  it('a learned fact keeps its provenance', () => {
    expect(toFact(fact())).toEqual({
      id: 'f1', kind: 'like', text: 'Takes tea with two sugars', source: 'resident', confidence: 0.9, quote: 'two sugars', callId: 'c1',
      learnedAt: Date.parse('2026-10-01T10:00:00Z'), lastConfirmed: Date.parse('2026-10-20T10:00:00Z'), timesSeen: 4, status: 'active',
    })
  })

  it('a fact remembers the call it was learned in', () => {
    expect(toFact({ ...fact(), call_id: 'call_9' }).callId).toBe('call_9')
  })

  it('the kind is the first tag it knows, and source "conversation" means the resident said it', () => {
    expect(kindOf(['tea', 'health'])).toBe('health')
    expect(kindOf([])).toBe('like')
    expect(sourceOf('conversation')).toBe('resident')
    expect(sourceOf('staff')).toBe('staff')
    expect(sourceOf('mystery')).toBe('inferred')
  })

  it('a pending fact waits for review and shows as seen now', () => {
    const p = toPending(pendingJson[0], NOW)
    expect(p).toMatchObject({ id: 'pending-1', status: 'pending', source: 'resident', confidence: 0.3, lastConfirmed: NOW })
  })

  it('medical history copes with missing parts', () => {
    const m = toMedical({ resident_id: 'r1', conditions: [{ name: 'COPD', since: '2018', note: null }], allergies: [], medicines: [], mobility: '', diet: '', last_review: null, reviewed_by: '' } as ApiMedical)
    expect(m.conditions).toEqual([{ name: 'COPD', since: '2018' }])
    expect(m.lastReview).toBe(0)
  })
})

describe('a resident', () => {
  const care = (kind: 'mood' | 'pain', daysAgo: number, value: number, hour = 10): ApiCare => ({
    id: `${kind}${daysAgo}${hour}`, resident_id: 'r1', kind, value, note: '', at: new Date(NOW - daysAgo * DAY + (hour - 15) * 3_600_000).toISOString(), call_id: null,
  })

  it('daily averages, oldest first, skipping days without a reading', () => {
    const entries = [care('mood', 3, 4), care('mood', 1, 2, 9), care('mood', 1, 4, 11), care('pain', 1, 5), care('mood', 20, 1)]
    expect(dailySeries(entries, 'mood', NOW)).toEqual([4, 3])
    expect(dailySeries(entries, 'pain', NOW)).toEqual([5])
  })

  it('flags use words, and hearing comes from the preferences', () => {
    expect(flagsOf(['falls', 'dementia', 'custom'], { resident_id: 'r', hard_of_hearing: true } as never)).toEqual(['Fall risk', 'Dementia', 'Custom', 'Hard of hearing'])
    expect(flagsOf([], null)).toEqual([])
  })

  it('is built from the resident plus what is known about them', () => {
    const r = toResident(residentsJson[0], { prefs: null, facts: [], pending: [pendingJson[0]], medical: null, care: [] }, NOW)
    expect(r).toMatchObject({ id: 'res_margaret', room: '12', age: 2026 - 1938, flags: ['Fall risk'], mood: [], pain: [] })
    expect(r.learned.map((f) => f.status)).toEqual(['pending'])
    expect(r.medical.conditions).toEqual([])
  })
})

describe('calls over time', () => {
  const at = (daysAgo: number, hour: number) => new Date(NOW - daysAgo * DAY).setHours(hour, 0, 0, 0)
  const view = (daysAgo: number, hour: number, status: ApiCall['status'] = 'resolved') => toCall(call({ id: `c${daysAgo}${hour}`, status, created_at: new Date(at(daysAgo, hour)).toISOString() }))

  it('counts today by local hour', () => {
    const buckets = hourlyCounts([view(0, 9), view(0, 9), view(0, 14), view(1, 9)], NOW)
    expect(buckets).toHaveLength(24)
    expect([buckets[9], buckets[14], buckets.reduce((a, b) => a + b)]).toEqual([2, 1, 3])
  })

  it('today and anything still open are live, older resolved calls are history', () => {
    const { today, past } = splitCalls([view(0, 9), view(3, 9), view(3, 10, 'escalated')], NOW)
    expect(today.map((c) => c.id).sort()).toEqual(['c09', 'c310'])
    expect(past.map((c) => c.id)).toEqual(['c39'])
  })
})
