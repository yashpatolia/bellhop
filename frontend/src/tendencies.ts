import type { Call, Category } from './data/types'

// Repeated behaviour across visits, found from a resident's call history. These are observations
// for staff, not diagnoses: each one says what was seen and how often.

export interface Tendency {
  id: string
  text: string
  evidence: string
}

const DAY = 86_400_000
const WINDOW_DAYS = 14
const MIN_CALLS = 3

const OFTEN: Record<Category, string> = {
  chat: 'Often asks for company',
  'comfort item': 'Often asks for comfort items',
  toileting: 'Often needs help with the bathroom',
  pain: 'Often calls about pain',
  medication: 'Often calls about medication',
  breathing: 'Often calls about breathing',
  fall: 'Often calls after a fall',
  confusion: 'Often calls feeling confused',
  other: 'Often calls for other reasons',
}

const NOUN: Record<Category, string> = {
  chat: 'conversation',
  'comfort item': 'comfort',
  toileting: 'bathroom help',
  pain: 'pain',
  medication: 'medication questions',
  breathing: 'breathing',
  fall: 'falls',
  confusion: 'confusion',
  other: 'other issues',
}

const hourOf = (c: Call) => new Date(c.createdAt).getHours()

function hourLabel(h: number): string {
  const hh = ((h % 24) + 24) % 24
  const suffix = hh < 12 ? 'AM' : 'PM'
  return `${hh % 12 === 0 ? 12 : hh % 12} ${suffix}`
}

function dayKey(ms: number): string {
  const d = new Date(ms)
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

function repeatedReason(calls: Call[]): Tendency[] {
  const counts = new Map<Category, number>()
  for (const c of calls) counts.set(c.category, (counts.get(c.category) ?? 0) + 1)
  return [...counts.entries()]
    .filter(([, n]) => n >= 3)
    .sort((a, b) => b[1] - a[1])
    .map(([cat, n]) => ({ id: `reason-${cat}`, text: OFTEN[cat], evidence: `${n} of ${calls.length} calls in the last ${WINDOW_DAYS} days` }))
}

function repeatedTime(calls: Call[]): Tendency[] {
  let best: { start: number; inside: Call[]; days: number } | null = null
  for (let start = 0; start < 24; start++) {
    const inside = calls.filter((c) => ((hourOf(c) - start + 24) % 24) < 3)
    const days = new Set(inside.map((c) => dayKey(c.createdAt))).size
    if (!best || inside.length > best.inside.length || (inside.length === best.inside.length && days > best.days)) best = { start, inside, days }
  }
  if (!best || best.days < 3 || best.inside.length < calls.length / 2) return []
  return [
    {
      id: 'time',
      text: `Often rings between ${hourLabel(best.start)} and ${hourLabel(best.start + 3)}`,
      evidence: `${best.inside.length} calls on ${best.days} different days in the last ${WINDOW_DAYS}`,
    },
  ]
}

function repeatedEscalation(calls: Call[]): Tendency[] {
  const counts = new Map<Category, number>()
  for (const c of calls) if (c.urgency >= 3) counts.set(c.category, (counts.get(c.category) ?? 0) + 1)
  return [...counts.entries()]
    .filter(([, n]) => n >= 2)
    .sort((a, b) => b[1] - a[1])
    .map(([cat, n]) => ({ id: `escalation-${cat}`, text: `Repeatedly needs a nurse for ${NOUN[cat]}`, evidence: `${n} nurse calls in the last ${WINDOW_DAYS} days` }))
}

function trend(calls: Call[], now: number): Tendency[] {
  const last = calls.filter((c) => now - c.createdAt <= 7 * DAY).length
  const before = calls.length - last
  if (last >= before * 1.5 && last - before >= 2) {
    return [{ id: 'trend', text: 'Calling more than last week', evidence: `${last} calls this week, ${before} the week before` }]
  }
  return []
}

function robotSettles(calls: Call[]): Tendency[] {
  const resolved = calls.filter((c) => c.status === 'resolved')
  const byRobot = resolved.filter((c) => c.resolvedByRobot).length
  if (resolved.length >= 4 && byRobot / resolved.length >= 0.7) {
    return [{ id: 'robot', text: 'Usually settles with the robot', evidence: `${byRobot} of ${resolved.length} resolved by the robot` }]
  }
  return []
}

/** Observations from calls in the last 14 days, strongest first. Needs at least 3 calls. */
export function findTendencies(allCalls: Call[], now: number): Tendency[] {
  const calls = allCalls.filter((c) => now - c.createdAt <= WINDOW_DAYS * DAY && c.createdAt <= now)
  if (calls.length < MIN_CALLS) return []
  return [...repeatedEscalation(calls), ...repeatedTime(calls), ...repeatedReason(calls), ...trend(calls, now), ...robotSettles(calls)].slice(0, 5)
}
