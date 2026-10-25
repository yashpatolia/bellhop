import type { Call, Category, Robot, Snapshot, Urgency } from './data/types'

export const URGENCY_LABEL: Record<Urgency, string> = {
  1: 'Robot resolving',
  2: 'Staff task',
  3: 'Needs a nurse',
  4: 'Emergency',
}

export const URGENCY_SHORT: Record<Urgency, string> = {
  1: 'Level 1',
  2: 'Level 2',
  3: 'Level 3',
  4: 'Level 4',
}

export const CATEGORY_LABEL: Record<Category, string> = {
  chat: 'Wants company',
  'comfort item': 'Comfort request',
  toileting: 'Bathroom help',
  pain: 'Pain',
  medication: 'Medication',
  breathing: 'Breathing',
  fall: 'Fall',
  confusion: 'Confusion',
  other: 'Other',
}

export function statusText(c: Call): string {
  switch (c.status) {
    case 'waiting':
      return 'Waiting for a free robot or a nurse'
    case 'robot_en_route':
      return 'Robot is on the way'
    case 'robot_with_resident':
      return 'Robot is talking with them'
    case 'nurse_notified':
      if (c.urgency === 4) return 'Alert sent. Robot is staying with them'
      return c.handledBy === 'nurse' ? 'Waiting for a nurse' : 'Staff has been asked'
    case 'nurse_en_route':
      return 'Nurse is on the way'
    case 'resolved':
      return c.resolvedByRobot ? 'Resolved by the robot' : 'Resolved by staff'
  }
}

export const isOpen = (c: Call) => c.status !== 'resolved'

export function elapsed(from: number, now: number): string {
  const s = Math.max(0, Math.round((now - from) / 1000))
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

export function clock(ms: number): string {
  return new Date(ms).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

const MIN_SAVED_PER_CALL = 4
export { MIN_SAVED_PER_CALL }

export interface Kpis {
  total: number
  byRobot: number
  open: number
  minutesSaved: number
  medianResponseSec: number
  within10: number
}

export function computeKpis(s: Snapshot): Kpis {
  const resolved = s.calls.filter((c) => c.status === 'resolved')
  const byRobot = resolved.filter((c) => c.resolvedByRobot).length
  const times = s.calls.map((c) => c.firstResponseSec).filter((x): x is number => x != null).sort((a, b) => a - b)
  const median = times.length ? times[Math.floor(times.length / 2)] : 0
  const within = times.length ? times.filter((t) => t <= 600).length / times.length : 1
  return {
    total: s.calls.length,
    byRobot,
    open: s.calls.length - resolved.length,
    minutesSaved: byRobot * MIN_SAVED_PER_CALL,
    medianResponseSec: median,
    within10: within,
  }
}

export function categoryCounts(calls: Call[]): { label: string; value: number }[] {
  const m = new Map<string, number>()
  for (const c of calls) m.set(CATEGORY_LABEL[c.category], (m.get(CATEGORY_LABEL[c.category]) ?? 0) + 1)
  return [...m.entries()].map(([label, value]) => ({ label, value })).sort((a, b) => b.value - a.value)
}

export const initials = (name: string) =>
  name
    .split(' ')
    .map((p) => p[0])
    .join('')
    .slice(0, 2)

export function humanizeKey(key: string): string {
  const words = key
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .trim()
    .toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

/** Shares (share_*) come from the backend as 0 to 1 and read as percentages. */
export function formatMetric(v: number | string, key = ''): string {
  if (typeof v === 'string') return v
  if (key.startsWith('share')) return `${Math.round(v * 100)}%`
  return Number.isInteger(v) ? String(v) : v.toFixed(2)
}

/** Alerts that still need a person: not acknowledged and the linked call (if known) is still open. */
export function activeAlerts(s: Snapshot): Snapshot['alerts'] {
  const open = new Set(s.calls.filter(isOpen).map((c) => c.id))
  return s.alerts
    .filter((a) => !a.acknowledged && (a.callId === null || open.has(a.callId) || !s.calls.some((c) => c.id === a.callId)))
    .sort((a, b) => b.urgency - a.urgency || b.createdAt - a.createdAt)
}

/** Recently cleared alerts, newest first. */
export function clearedAlerts(s: Snapshot, limit = 12): Snapshot['alerts'] {
  const active = new Set(activeAlerts(s).map((a) => a.id))
  return s.alerts
    .filter((a) => !active.has(a.id))
    .sort((a, b) => (b.clearedAt ?? b.createdAt) - (a.clearedAt ?? a.createdAt))
    .slice(0, limit)
}

/** Below this charge staff are warned before driving a robot (percent). The backend does not refuse. */
export const LOW_BATTERY = 20

/** Whether a robot can take a manual drive now, in words. The backend accepts only an idle robot. */
export function robotAvailability(r: Robot): { free: boolean; words: string } {
  if (r.state === 'fault') return { free: false, words: 'Needs attention' }
  if (r.state === 'charging') return { free: false, words: 'Charging' }
  if (r.state === 'en_route') return { free: false, words: r.targetRoom ? `Driving, room ${r.targetRoom}` : 'Driving' }
  if (r.state === 'with_resident') return { free: false, words: r.targetRoom ? `With a resident, room ${r.targetRoom}` : 'With a resident' }
  if (r.battery < LOW_BATTERY) return { free: true, words: `Free, low battery (${Math.round(r.battery)}%)` }
  return { free: true, words: 'Free' }
}

/** A free robot already in the room, otherwise the free one with the most charge. */
export function closestFreeRobot(robots: Robot[], room: string): Robot | undefined {
  const free = robots.filter((r) => robotAvailability(r).free)
  return free.find((r) => r.room === room) ?? free.sort((a, b) => b.battery - a.battery)[0]
}

/** The next id in the fleet's own pattern: robot_3 after robot_1 and robot_2. */
export function nextRobotId(ids: string[]): string {
  let prefix = 'robot_'
  let max = 0
  for (const id of ids) {
    const m = /^(.*?)(\d+)$/.exec(id)
    if (m && Number(m[2]) >= max) {
      prefix = m[1]
      max = Number(m[2])
    }
  }
  return `${prefix}${max + 1}`
}
