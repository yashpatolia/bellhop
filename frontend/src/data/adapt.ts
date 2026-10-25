import type {
  ApiAlert,
  ApiCall,
  ApiCare,
  ApiFact,
  ApiMedical,
  ApiNurse,
  ApiPending,
  ApiPrefs,
  ApiResident,
  ApiRobot,
} from '../api/types'
import type {
  Alert,
  Call,
  CallStatus,
  Category,
  FactKind,
  FactSource,
  HandledBy,
  LearnedFact,
  MedicalHistory,
  Metrics,
  Resident,
  Robot,
  RobotState,
  Snapshot,
  Urgency,
} from './types'

// The only place that knows the backend's wire format (contracts/openapi.json). Pure functions:
// no network, no clock except what is passed in, so each one is tested against the contract examples.

const ms = (iso: string | null | undefined): number | null => (iso ? Date.parse(iso) : null)

const CATEGORY_ALIASES: Record<string, Category> = {
  chat: 'chat',
  social: 'chat',
  company: 'chat',
  'comfort item': 'comfort item',
  comfort: 'comfort item',
  toileting: 'toileting',
  bathroom: 'toileting',
  pain: 'pain',
  medication: 'medication',
  breathing: 'breathing',
  fall: 'fall',
  confusion: 'confusion',
}

/** The backend keeps the category the triage model wrote. Anything unknown shows as "other". */
export function categoryOf(raw: string | null | undefined): Category {
  return CATEGORY_ALIASES[(raw ?? '').trim().toLowerCase()] ?? 'other'
}

const URGENCIES: Urgency[] = [1, 2, 3, 4]

/** A call that is not scored yet counts as level 1: nothing is escalated on a guess. */
export function urgencyOf(raw: number | null | undefined): Urgency {
  return URGENCIES.includes(raw as Urgency) ? (raw as Urgency) : 1
}

export function statusOf(c: ApiCall): CallStatus {
  switch (c.status) {
    case 'resolved':
    case 'closed':
      return 'resolved'
    case 'nurse_acked':
      return 'nurse_en_route'
    case 'escalated':
      return 'nurse_notified'
    case 'in_visit':
      return 'robot_with_resident'
    default:
      // ringing, assigned, robot_en_route
      if (c.robot_id) return 'robot_en_route'
      return (c.nurse_tasks?.length ?? 0) > 0 ? 'nurse_notified' : 'waiting'
  }
}

export function handledByOf(c: ApiCall): HandledBy {
  const urgency = urgencyOf(c.urgency)
  if (urgency >= 3 || (!c.robot_id && (c.nurse_tasks?.length ?? 0) > 0)) return 'nurse'
  return urgency === 2 ? 'staff' : 'robot'
}

export function toCall(c: ApiCall): Call {
  const created = Date.parse(c.created_at)
  const firstVoice = ms(c.first_response_at)
  const resolvedAt = ms(c.resolved_at)
  const status = statusOf(c)
  return {
    id: c.id,
    residentId: c.resident_id ?? null,
    room: c.room,
    urgency: urgencyOf(c.urgency),
    category: categoryOf(c.category),
    status,
    handledBy: handledByOf(c),
    robotId: c.robot_id ?? null,
    createdAt: created,
    firstResponseSec: firstVoice === null ? null : Math.max(0, Math.round((firstVoice - created) / 1000)),
    resolvedAt,
    resolvedByRobot: status === 'resolved' && (c.resolved_by_robot ?? false),
    summary: c.summary ?? '',
    transcript: (c.transcript ?? []).map((t) => ({
      who: t.speaker === 'resident' || t.speaker === 'nurse' ? t.speaker : 'robot',
      text: t.text,
    })),
  }
}

export function toAlert(a: ApiAlert, calls: Map<string, Call>): Alert {
  const call = calls.get(a.call_id)
  const cleared = call?.status === 'resolved' ? call.resolvedAt : null
  return {
    id: a.id,
    callId: a.call_id,
    room: call?.room ?? null,
    urgency: urgencyOf(a.level),
    message: a.message,
    createdAt: Date.parse(a.created_at),
    nurseId: a.nurse_id ?? null,
    acknowledged: a.acked_at != null,
    clearedAt: cleared ?? ms(a.acked_at),
  }
}

export function toRobot(r: ApiRobot, calls: Call[]): Robot {
  const call = calls.find((c) => c.robotId === r.id && c.status !== 'resolved')
  let state: RobotState = 'idle'
  if (r.status === 'charging') state = 'charging'
  else if (r.status === 'fault') state = 'fault'
  else if (call) state = call.status === 'robot_en_route' ? 'en_route' : 'with_resident'
  else if (r.status === 'busy') state = 'en_route'
  return {
    id: r.id,
    name: r.id
      .replace(/[_-]+/g, ' ')
      .replace(/\b\w/g, (m) => m.toUpperCase()),
    state,
    battery: Math.round((r.battery ?? 0) * 100),
    room: r.room ?? null,
    targetRoom: call?.room ?? null,
    callId: call?.id ?? null,
  }
}

export function toNurse(n: ApiNurse): Snapshot['nurses'][number] {
  return { id: n.id, name: n.name, onShift: n.on_shift, openTasks: n.open_tasks }
}

const FACT_KINDS: FactKind[] = ['like', 'dislike', 'person', 'routine', 'health', 'style', 'event']
const FACT_SOURCES: FactSource[] = ['resident', 'staff', 'family', 'inferred']

export function kindOf(tags: string[] | undefined): FactKind {
  return (tags ?? []).find((t): t is FactKind => FACT_KINDS.includes(t as FactKind)) ?? 'like'
}

/** "conversation" is what the learner writes: it means the resident said it. */
export function sourceOf(raw: string): FactSource {
  if (raw === 'conversation') return 'resident'
  return FACT_SOURCES.includes(raw as FactSource) ? (raw as FactSource) : 'inferred'
}

export function toFact(f: ApiFact): LearnedFact {
  const learned = Date.parse(f.created_at)
  return {
    id: f.id,
    kind: kindOf(f.tags),
    text: f.text,
    source: sourceOf(f.source),
    confidence: f.confidence,
    quote: f.quote ?? null,
    callId: f.call_id ?? null,
    learnedAt: learned,
    lastConfirmed: ms(f.last_confirmed) ?? learned,
    timesSeen: f.times_seen,
    status: 'active',
  }
}

/** Pending facts carry no dates from the backend, so they show as seen just now. */
export function toPending(p: ApiPending, now: number): LearnedFact {
  return {
    id: p.id,
    kind: kindOf(p.tags),
    text: p.text,
    source: sourceOf(p.source ?? 'conversation'),
    confidence: p.confidence ?? 0,
    quote: p.quote ?? null,
    callId: p.call_id ?? null,
    learnedAt: now,
    lastConfirmed: now,
    timesSeen: 1,
    status: 'pending',
  }
}

export function toMedical(m: ApiMedical): MedicalHistory {
  return {
    conditions: (m.conditions ?? []).map((c) => ({ name: c.name, since: c.since, ...(c.note ? { note: c.note } : {}) })),
    allergies: m.allergies ?? [],
    medicines: m.medicines ?? [],
    mobility: m.mobility ?? '',
    diet: m.diet ?? '',
    lastReview: ms(m.last_review) ?? 0,
    reviewedBy: m.reviewed_by ?? '',
  }
}

const RISK_LABEL: Record<string, string> = { falls: 'Fall risk', dementia: 'Dementia', oxygen: 'Oxygen', diabetic: 'Diabetic' }

/** The risk flags staff can set, as the backend stores them, with the words shown for each. */
export const RISK_CHOICES = Object.entries(RISK_LABEL).map(([code, label]) => ({ code, label }))

export function flagsOf(riskFlags: string[], prefs: ApiPrefs | null): string[] {
  const flags = riskFlags.map((f) => RISK_LABEL[f.toLowerCase()] ?? f.charAt(0).toUpperCase() + f.slice(1))
  if (prefs?.hard_of_hearing) flags.push('Hard of hearing')
  return flags
}

const dayKey = (t: number) => {
  const d = new Date(t)
  return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`
}

/** Daily average of one kind of reading over the last `days` days, oldest first. Days with no reading are left out. */
export function dailySeries(entries: ApiCare[], kind: 'mood' | 'pain', now: number, days = 7): number[] {
  const since = now - days * 86_400_000
  const byDay = new Map<string, { at: number; sum: number; n: number }>()
  for (const e of entries) {
    const at = Date.parse(e.at)
    if (e.kind !== kind || e.value == null || at < since || at > now) continue
    const key = dayKey(at)
    const day = byDay.get(key) ?? { at, sum: 0, n: 0 }
    byDay.set(key, { at: Math.min(day.at, at), sum: day.sum + e.value, n: day.n + 1 })
  }
  return [...byDay.values()].sort((a, b) => a.at - b.at).map((d) => +(d.sum / d.n).toFixed(1))
}

export interface ResidentParts {
  prefs: ApiPrefs | null
  facts: ApiFact[]
  pending: ApiPending[]
  medical: ApiMedical | null
  care: ApiCare[]
}

export const EMPTY_MEDICAL: MedicalHistory = { conditions: [], allergies: [], medicines: [], mobility: '', diet: '', lastReview: 0, reviewedBy: '' }

export function toResident(r: ApiResident, parts: ResidentParts, now: number): Resident {
  return {
    id: r.id,
    name: r.name,
    room: r.room,
    age: r.birth_year ? new Date(now).getFullYear() - r.birth_year : null,
    flags: flagsOf(r.risk_flags ?? [], parts.prefs),
    riskFlags: r.risk_flags ?? [],
    birthYear: r.birth_year ?? null,
    hardOfHearing: parts.prefs?.hard_of_hearing ?? false,
    mood: dailySeries(parts.care, 'mood', now),
    pain: dailySeries(parts.care, 'pain', now),
    learned: [...parts.facts.map(toFact), ...parts.pending.map((p) => toPending(p, now))],
    medical: parts.medical ? toMedical(parts.medical) : EMPTY_MEDICAL,
  }
}

/** Calls created today, by local hour (24 buckets). */
export function hourlyCounts(calls: Call[], now: number): number[] {
  const today = dayKey(now)
  const buckets = new Array<number>(24).fill(0)
  for (const c of calls) if (dayKey(c.createdAt) === today) buckets[new Date(c.createdAt).getHours()] += 1
  return buckets
}

/** Calls from today and anything still open are "live"; older resolved calls are history. */
export function splitCalls(calls: Call[], now: number): { today: Call[]; past: Call[] } {
  const today = dayKey(now)
  const live: Call[] = []
  const past: Call[] = []
  for (const c of calls) (dayKey(c.createdAt) === today || c.status !== 'resolved' ? live : past).push(c)
  return { today: live, past }
}

export function toMetrics(raw: Record<string, unknown>): Metrics | null {
  const out: Metrics = {}
  for (const [k, v] of Object.entries(raw)) if (typeof v === 'number' || typeof v === 'string') out[k] = v
  return Object.keys(out).length ? out : null
}
