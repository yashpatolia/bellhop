// The view model the screens read. src/data/adapt.ts builds it from the backend's responses
// (see contracts/openapi.json); nothing else knows about the wire format.

export type Urgency = 1 | 2 | 3 | 4

export type Category =
  | 'chat'
  | 'comfort item'
  | 'toileting'
  | 'pain'
  | 'medication'
  | 'breathing'
  | 'fall'
  | 'confusion'
  | 'other'

export type CallStatus =
  | 'waiting'
  | 'robot_en_route'
  | 'robot_with_resident'
  | 'nurse_notified'
  | 'nurse_en_route'
  | 'resolved'

export type HandledBy = 'robot' | 'staff' | 'nurse'

export interface TranscriptLine {
  who: 'resident' | 'robot' | 'nurse'
  text: string
}

export interface Call {
  id: string
  residentId: string | null
  room: string
  urgency: Urgency
  category: Category
  status: CallStatus
  handledBy: HandledBy
  robotId: string | null
  createdAt: number // epoch ms
  firstResponseSec: number | null
  resolvedAt: number | null
  resolvedByRobot: boolean
  summary: string
  transcript: TranscriptLine[]
}

export type FactKind = 'like' | 'dislike' | 'person' | 'routine' | 'health' | 'style' | 'event'
export type FactSource = 'resident' | 'staff' | 'family' | 'inferred'

/** Something Bellhop has learned about a resident, with where it came from. */
export interface LearnedFact {
  id: string
  kind: FactKind
  text: string
  source: FactSource
  confidence: number // 0 to 1
  quote: string | null // the resident's own words, when heard from them
  learnedAt: number // epoch ms
  lastConfirmed: number // epoch ms
  timesSeen: number
  status: 'active' | 'pending' // pending: waiting for a nurse to review
}

/** Entered by staff, not learned by Bellhop. */
export interface MedicalHistory {
  conditions: { name: string; since: string; note?: string }[]
  allergies: string[]
  medicines: string[] // names only, as listed by staff
  mobility: string
  diet: string
  lastReview: number // epoch ms
  reviewedBy: string
}

/** What staff can add to a resident's profile. The first five become learned facts, the rest medical history. */
export type EntryCategory = 'like' | 'dislike' | 'person' | 'routine' | 'style' | 'condition' | 'allergy' | 'medicine' | 'mobility' | 'diet'

export interface EntryDraft {
  category: EntryCategory
  text: string
}

/** A draft after the AI tidy step: cleaner wording plus notes on what changed or was removed. */
export interface RefinedEntry {
  category: EntryCategory
  text: string
  since?: string // conditions only
  notes: string[]
}

export interface Resident {
  id: string
  name: string
  room: string
  age: number | null
  flags: string[]
  mood: number[] // daily average, oldest first, 1 to 5; days without a reading are skipped
  pain: number[] // daily average, oldest first, 1 (none) to 5 (severe)
  learned: LearnedFact[]
  medical: MedicalHistory
}

export type RobotState = 'idle' | 'en_route' | 'with_resident' | 'charging' | 'fault'

export interface Robot {
  id: string
  name: string
  state: RobotState
  battery: number // percent
  room: string | null // where it reports being
  targetRoom: string | null // the room it is working on, when it has a call
  callId: string | null
}

export interface Alert {
  id: string
  callId: string | null
  room: string | null
  urgency: Urgency
  message: string
  createdAt: number // epoch ms
  nurseId: string | null // null: sent to every nurse on shift
  acknowledged: boolean
  clearedAt?: number | null // epoch ms, when it stopped needing a person
}

// Backend rollup numbers. Shape is open: any top level number or string.
export type Metrics = Record<string, number | string>

export interface Snapshot {
  now: number
  calls: Call[]
  residents: Resident[]
  robots: Robot[]
  nurses: { id: string; name: string; onShift: boolean; openTasks: number }[]
  hourly: number[] // 24 buckets of calls today
  alerts: Alert[]
  metrics: Metrics | null
  pastCalls: Call[] // calls from before today, for history and tendencies
  connection: Connection
}

/** Whether the screens are showing live data, and what to tell staff when they are not. */
export interface Connection {
  state: 'connecting' | 'live' | 'offline'
  /** Set while the backend cannot be reached, or after an action failed. */
  problem: string | null
  /** True once the backend answered and it holds no residents: show the empty-home guidance. */
  empty: boolean
}

export type ReviewDecision = 'approve' | 'reject'

export interface Actions {
  /** Send this robot to a room (POST /robots/{id}/dispatch). Returns the new call's id, or null if it failed. */
  sendRobot: (robotId: string, room: string) => Promise<string | null>
  /** Acknowledge the call's alert, so the nurse shows as on the way. */
  nurseOnMyWay: (callId: string) => Promise<void>
  /** Mark a call done by staff. */
  resolve: (callId: string) => Promise<void>
  /** Tidy staff-written text into a clean entry for review. Nothing is saved yet. */
  refineEntry: (residentId: string, draft: EntryDraft) => Promise<RefinedEntry>
  /** Save a reviewed entry to the resident's profile. */
  addEntry: (residentId: string, entry: RefinedEntry) => Promise<void>
  /** A nurse approves (Bellhop starts using the fact) or rejects (it is forgotten) a pending fact. */
  reviewFact: (residentId: string, factId: string, decision: ReviewDecision) => Promise<void>
}

export interface BellhopData extends Snapshot {
  actions: Actions
}
