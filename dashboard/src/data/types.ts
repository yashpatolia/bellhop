// Shapes match the "interfaces to agree early" on the overview page.
// When the real SpacetimeDB store exists, only src/data/source.ts changes.

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
  | 'robot_en_route'
  | 'robot_with_resident'
  | 'nurse_notified'
  | 'nurse_en_route'
  | 'resolved'

export type HandledBy = 'robot' | 'aide' | 'kitchen' | 'nurse'

export interface TranscriptLine {
  who: 'resident' | 'robot' | 'nurse'
  text: string
}

export interface Call {
  id: string
  residentId: string
  room: number
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
  sbar: { s: string; b: string; a: string; r: string }
  transcript: TranscriptLine[]
  confidence: number // triage confidence, 0 to 1
  costUsd: number
  feedback: 1 | 2 | 3 | 4 | 5 | null
}

export interface Resident {
  id: string
  name: string
  room: number
  age: number
  flags: string[]
  likes: string[]
  language: string
  mood: number[] // last 7 days, 1 to 5
  pain: number[] // last 7 days, 0 to 10
  aiCostToday: number
  callsToday: number
}

export type RobotState = 'idle' | 'en_route' | 'with_resident' | 'charging'

export interface Robot {
  id: string
  name: string
  state: RobotState
  battery: number // percent
  x: number
  y: number
  targetRoom: number | null
  callId: string | null
}

export interface Room {
  number: number
  x: number
  y: number
  w: number
  h: number
  door: { x: number; y: number }
}

export interface Alert {
  id: string
  callId: string | null
  room: number | null
  urgency: Urgency
  message: string
  createdAt: number // epoch ms
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
  nurses: { id: string; name: string; status: 'free' | 'busy' | 'with_resident' }[]
  hourly: number[] // 24 buckets of calls today
  alerts: Alert[]
  metrics: Metrics | null
}

export interface Actions {
  nurseOnMyWay: (callId: string) => void
  resolve: (callId: string) => void
}

export interface BellhopData extends Snapshot {
  actions: Actions
}
