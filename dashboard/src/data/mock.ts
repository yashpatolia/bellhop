import type {
  Alert,
  Call,
  Category,
  CallStatus,
  HandledBy,
  Resident,
  Robot,
  Snapshot,
  TranscriptLine,
  Urgency,
} from './types'
import { DOCK_POINT, FLOOR, ROOMS, roomByNumber } from './layout'

// Everything in this file is dummy data. It is replaced by the real store
// (SpacetimeDB) by swapping the source in source.ts.

const MIN = 60_000

export const RESIDENTS: Resident[] = [
  { id: 'r101', name: 'Margaret Alvarez', room: 101, age: 84, flags: ['Fall risk'], likes: ['Tea, two sugars', 'Her grandson Mateo', 'Old Spanish ballads'], language: 'English, Spanish', mood: [4, 4, 5, 4, 3, 4, 4], pain: [2, 3, 2, 4, 5, 4, 4], aiCostToday: 0, callsToday: 0 },
  { id: 'r102', name: 'Harold Chen', room: 102, age: 79, flags: ['Hard of hearing'], likes: ['Chess', 'Baseball', 'Green tea'], language: 'English, Cantonese', mood: [3, 3, 4, 4, 4, 5, 4], pain: [1, 1, 2, 1, 1, 2, 1], aiCostToday: 0, callsToday: 0 },
  { id: 'r103', name: 'Dorothy Okafor', room: 103, age: 88, flags: ['Dementia', 'Fall risk'], likes: ['Gospel music', 'Her late husband Emeka', 'Crosswords'], language: 'English, Igbo', mood: [4, 3, 3, 2, 3, 3, 2], pain: [3, 3, 3, 4, 3, 3, 3], aiCostToday: 0, callsToday: 0 },
  { id: 'r104', name: 'Walter Brennan', room: 104, age: 91, flags: ['Fall risk', 'Oxygen'], likes: ['Westerns', 'Fishing stories', 'Black coffee'], language: 'English', mood: [3, 3, 3, 3, 2, 3, 3], pain: [4, 4, 5, 5, 6, 5, 5], aiCostToday: 0, callsToday: 0 },
  { id: 'r105', name: 'Evelyn Park', room: 105, age: 76, flags: [], likes: ['Gardening', 'Bingo', 'Jasmine tea'], language: 'English, Korean', mood: [5, 5, 4, 5, 5, 5, 5], pain: [1, 1, 1, 2, 1, 1, 1], aiCostToday: 0, callsToday: 0 },
  { id: 'r106', name: 'George Haddad', room: 106, age: 82, flags: ['Diabetic'], likes: ['Backgammon', 'Arabic poetry', 'Mint tea'], language: 'English, Arabic', mood: [4, 4, 4, 3, 4, 4, 4], pain: [2, 2, 2, 2, 3, 2, 2], aiCostToday: 0, callsToday: 0 },
  { id: 'r107', name: 'Ruth Nakamura', room: 107, age: 86, flags: ['Hard of hearing'], likes: ['Origami', 'Old films', 'Barley tea'], language: 'English, Japanese', mood: [4, 4, 4, 5, 4, 4, 5], pain: [2, 2, 1, 2, 2, 2, 1], aiCostToday: 0, callsToday: 0 },
  { id: 'r108', name: 'Arthur Singh', room: 108, age: 80, flags: ['Fall risk'], likes: ['Cricket', 'His daughter Priya', 'Chai'], language: 'English, Punjabi', mood: [3, 4, 4, 3, 3, 2, 3], pain: [3, 3, 4, 4, 4, 5, 5], aiCostToday: 0, callsToday: 0 },
  { id: 'r109', name: 'Beatrice Moreau', room: 109, age: 93, flags: ['Dementia'], likes: ['Piano music', 'Paris stories', 'Warm milk'], language: 'English, French', mood: [3, 3, 2, 3, 3, 2, 2], pain: [2, 2, 2, 2, 3, 2, 2], aiCostToday: 0, callsToday: 0 },
  { id: 'r110', name: 'Leonard Ivanov', room: 110, age: 77, flags: [], likes: ['Chess', 'Trains', 'Black tea'], language: 'English, Russian', mood: [4, 4, 5, 4, 4, 4, 5], pain: [1, 2, 1, 1, 1, 1, 1], aiCostToday: 0, callsToday: 0 },
  { id: 'r111', name: 'Mabel Johnson', room: 111, age: 89, flags: ['Fall risk', 'Hard of hearing'], likes: ['Quilting', 'Soap operas', 'Peppermints'], language: 'English', mood: [4, 3, 4, 4, 3, 3, 4], pain: [3, 4, 3, 3, 4, 4, 3], aiCostToday: 0, callsToday: 0 },
  { id: 'r112', name: 'Frank Delgado', room: 112, age: 74, flags: ['Diabetic'], likes: ['Salsa music', 'Boxing', 'Cafe con leche'], language: 'English, Spanish', mood: [5, 4, 4, 5, 4, 5, 4], pain: [1, 1, 1, 1, 2, 1, 1], aiCostToday: 0, callsToday: 0 },
]

interface Scenario {
  category: Category
  urgency: Urgency
  handledBy: HandledBy
  resident: string
  robot: string
  summary: string
  s: string
  a: string
  r: string
}

const SCENARIOS: Scenario[] = [
  { category: 'chat', urgency: 1, handledBy: 'robot', resident: 'Could we just talk for a bit? It is quiet today.', robot: 'Of course. Last time you told me about your garden. Did the roses come back?', summary: 'Wanted company. Chatted about family and garden.', s: 'Rang the bell for company, no distress.', a: 'No medical need. Mood slightly low but normal.', r: 'No action. Robot visit logged.' },
  { category: 'comfort item', urgency: 1, handledBy: 'kitchen', resident: 'Could I have a cup of tea, please?', robot: 'Absolutely. I will ask the kitchen right now. Your usual?', summary: 'Asked for tea. Task sent to the kitchen.', s: 'Requested a hot drink.', a: 'Routine request.', r: 'Kitchen task created.' },
  { category: 'comfort item', urgency: 1, handledBy: 'aide', resident: 'I am cold. Could I have another blanket?', robot: 'Let me get someone to bring you a blanket. Are you comfortable otherwise?', summary: 'Cold. Extra blanket task sent to an aide.', s: 'Reports feeling cold.', a: 'No other symptoms mentioned.', r: 'Aide to bring blanket.' },
  { category: 'toileting', urgency: 2, handledBy: 'aide', resident: 'I need the bathroom, but I do not want to walk alone.', robot: 'Stay seated, I will get an aide to walk with you. I am right here.', summary: 'Needs help to the bathroom. Aide requested.', s: 'Needs assistance to the bathroom.', a: 'Fall risk, should not walk alone.', r: 'Aide to assist now.' },
  { category: 'confusion', urgency: 2, handledBy: 'aide', resident: 'Where is my husband? He should be home by now.', robot: 'You are safe here. Would you like to tell me about him while we wait together?', summary: 'Confused about location. Calmed with conversation.', s: 'Asking for late husband, disoriented.', a: 'Known dementia. Mild distress, responding to calm voice.', r: 'Aide check-in within 10 minutes.' },
  { category: 'pain', urgency: 3, handledBy: 'nurse', resident: 'My hip has been aching since last night.', robot: 'I am sorry. Where exactly, and how bad is it from one to ten?', summary: 'Hip pain, 6 out of 10, since last night.', s: 'Hip pain reported as 6 out of 10 since last night.', a: 'Pain trend rising over three days. No fall reported.', r: 'Nurse to assess and consider pain relief.' },
  { category: 'medication', urgency: 3, handledBy: 'nurse', resident: 'I think I missed my morning pills. Should I take them now?', robot: 'Good question. I will ask your nurse to check. Please do not take anything yet.', summary: 'Unsure whether morning medication was taken.', s: 'Believes morning dose may have been missed.', a: 'No symptoms. Needs chart check.', r: 'Nurse to verify dose on the chart.' },
  { category: 'pain', urgency: 3, handledBy: 'nurse', resident: 'My chest feels tight when I climb out of bed.', robot: 'I am staying with you. I am telling your nurse now. Please sit still and breathe slowly.', summary: 'Chest tightness on standing. Escalated to nurse.', s: 'Chest tightness when getting out of bed.', a: 'Reported once today. No breathlessness at rest.', r: 'Nurse to assess soon.' },
  { category: 'fall', urgency: 4, handledBy: 'nurse', resident: 'I have fallen and I cannot get up.', robot: 'Help is coming right now. Do not try to move. I am staying right here with you.', summary: 'Resident has fallen and cannot get up.', s: 'Fall in room, cannot get up.', a: 'High fall risk. Conscious and talking.', r: 'Nurse needed immediately.' },
  { category: 'breathing', urgency: 4, handledBy: 'nurse', resident: 'I cannot catch my breath.', robot: 'I am alerting your nurse right now. Breathe slowly with me. I am not leaving.', summary: 'Struggling to breathe. Emergency alert sent.', s: 'Difficulty breathing, speaking in short phrases.', a: 'On oxygen. Possible oxygen interruption.', r: 'Nurse immediately. Check oxygen.' },
]

let seq = 1000
const rand = (a: number, b: number) => a + Math.random() * (b - a)
const pick = <T,>(xs: T[]) => xs[Math.floor(Math.random() * xs.length)]

// Later turns of each scripted conversation, in SCENARIOS order: resident, robot, resident, robot.
const FOLLOW_UPS: [string, string, string, string][] = [
  ['Yes, they did. The red ones are blooming.', 'That is lovely. Tell me more about them.', 'My late husband planted them. I should get back to my show now.', 'Of course. Ring whenever you want to chat again. Take care.'],
  ['Yes, my usual please.', 'Done. The kitchen will bring it in about ten minutes.', 'Thank you, dear.', 'You are welcome. Ring any time if you need anything else.'],
  ['My feet are cold too.', 'I will mention it. An aide is bringing a blanket and warm socks.', 'That would be wonderful, thank you.', 'Glad to help. Ring if you need anything else.'],
  ['Yes please, I will wait here.', 'An aide is on the way. It should be about two minutes.', 'All right, thank you for staying.', 'Of course. The aide is here now, so I will step aside.'],
  ['He always comes home at six.', 'That sounds like a good routine. What does he like for dinner?', 'Stew, always stew. I feel better talking about it.', 'I am glad. An aide is coming to sit with you for a while.'],
  ['The right side. About a six. It is worse when I stand.', 'Thank you. I am telling your nurse so they can check and consider pain relief.', 'Will it take long?', 'A nurse is on the way. I will stay with you until they arrive.'],
  ['I always take them after breakfast.', 'Understood. Please wait. Your nurse will check the chart and tell you.', 'All right, I will wait.', 'The nurse has checked the chart. Thank you for waiting.'],
  ['It started when I stood up. It is a little better sitting.', 'Please stay seated. Your nurse is on the way and I am staying with you.', 'Okay. I am a bit scared.', 'I know. I am right here. The nurse will be with you very soon.'],
  ['My leg hurts and I am on the floor by the bed.', 'Do not move. A nurse has been alerted and is coming now.', 'Please hurry.', 'They are coming. I am staying right here with you.'],
  ['It is hard to talk.', 'Do not talk, just breathe slowly with me. In through the nose, out through the mouth.', 'A little better. Is someone coming?', 'Yes, the nurse has been alerted and is on the way. I am here.'],
]

function transcriptFor(sc: Scenario): TranscriptLine[] {
  const more = FOLLOW_UPS[SCENARIOS.indexOf(sc)] ?? ['Thank you.', 'You are welcome.', 'Thank you again.', 'I am here if you need anything.']
  return [
    { who: 'resident', text: sc.resident },
    { who: 'robot', text: sc.robot },
    { who: 'resident', text: more[0] },
    { who: 'robot', text: more[1] },
    { who: 'resident', text: more[2] },
    { who: 'robot', text: more[3] },
  ]
}

/** How much of the conversation exists yet: none before the robot arrives, all of it once resolved. */
function linesSoFar(status: CallStatus): number {
  switch (status) {
    case 'robot_en_route':
      return 0
    case 'robot_with_resident':
      return 3
    case 'nurse_notified':
      return 4
    case 'nurse_en_route':
      return 5
    case 'resolved':
      return 6
  }
}

function makeCall(
  sc: Scenario,
  resident: Resident,
  createdAt: number,
  status: CallStatus,
  robotId: string | null,
): Call {
  const resolved = status === 'resolved'
  const handledByRobot = sc.handledBy === 'robot'
  return {
    id: `c${seq++}`,
    residentId: resident.id,
    room: resident.room,
    urgency: sc.urgency,
    category: sc.category,
    status,
    handledBy: sc.handledBy,
    robotId,
    createdAt,
    firstResponseSec: resolved ? Math.round(rand(35, 140)) : null,
    resolvedAt: resolved ? createdAt + rand(2, 9) * MIN : null,
    resolvedByRobot: resolved && handledByRobot,
    summary: sc.summary,
    sbar: {
      s: sc.s,
      b: `${resident.name}, ${resident.age}. ${resident.flags.join(', ') || 'No flags'}.`,
      a: sc.a,
      r: sc.r,
    },
    transcript: transcriptFor(sc),
    confidence: sc.urgency >= 3 ? rand(0.72, 0.97) : rand(0.86, 0.99),
    costUsd: +rand(0.08, 0.19).toFixed(3),
    feedback: resolved && Math.random() > 0.35 ? ((Math.ceil(rand(3.2, 5)) as 3 | 4 | 5)) : null,
  }
}

function initialRobots(): Robot[] {
  return [
    { id: 'b1', name: 'Bellhop 1', state: 'idle', battery: 82, x: 520, y: 230, targetRoom: null, callId: null },
    { id: 'b2', name: 'Bellhop 2', state: 'idle', battery: 27, x: 300, y: 230, targetRoom: null, callId: null },
    { id: 'b3', name: 'Bellhop 3', state: 'charging', battery: 38, x: DOCK_POINT.x, y: DOCK_POINT.y, targetRoom: null, callId: null },
  ]
}

export function seedCalls(now: number): Call[] {
  const calls: Call[] = []
  const times = [11, 24, 38, 55, 71, 96, 118, 142, 170, 201, 233, 268, 305, 340, 395, 450]
  times.forEach((m, i) => {
    const sc = SCENARIOS[(i * 3 + 1) % (SCENARIOS.length - 2)]
    calls.push(makeCall(sc, RESIDENTS[(i * 5) % RESIDENTS.length], now - m * MIN, 'resolved', 'b' + (1 + (i % 3))))
  })
  return calls
}

const WAIT_ALERT_MS = 40_000 // mock only: a real ward would escalate after minutes

interface Waypoint {
  x: number
  y: number
}

export class Simulator {
  calls: Call[]
  robots: Robot[]
  nurses: Snapshot['nurses']
  private paths = new Map<string, Waypoint[]>()
  private phaseAt = new Map<string, number>()
  private alertLog = new Map<string, Alert>()
  private snapshot!: Snapshot
  private listeners = new Set<() => void>()
  private timer: number | undefined
  private nextCallIn = 4

  readonly live: boolean

  constructor(live = true) {
    this.live = live
    const now = Date.now()
    this.calls = seedCalls(now)
    this.robots = initialRobots()
    this.nurses = [
      { id: 'n1', name: 'Nurse Okoro', status: 'free' },
      { id: 'n2', name: 'Nurse Patel', status: 'with_resident' },
      { id: 'n3', name: 'Nurse Lindqvist', status: 'free' },
    ]
    this.seedAlertHistory(now)
    this.rebuild()
  }

  private seedAlertHistory(now: number) {
    const past = (id: string, room: number | null, urgency: 2 | 3 | 4, message: string, minsAgo: number, clearedAfterMin: number): void => {
      this.alertLog.set(id, { id, callId: null, room, urgency, message, createdAt: now - minsAgo * MIN, acknowledged: true, clearedAt: now - (minsAgo - clearedAfterMin) * MIN })
    }
    past('h1', 104, 3, 'Still waiting for a nurse. Please respond.', 52, 3)
    past('h2', null, 2, 'Bellhop 3 battery is low (24%). Heading to the dock.', 87, 6)
    past('h3', 111, 3, 'Still waiting for a nurse. Please respond.', 140, 2)
    past('h4', null, 2, 'Bellhop 1 battery is low (28%). Heading to the dock.', 203, 5)
  }

  start() {
    if (!this.live || this.timer) return
    this.timer = window.setInterval(() => this.tick(), 1000)
  }
  stop() {
    if (this.timer) window.clearInterval(this.timer)
    this.timer = undefined
  }

  subscribe = (fn: () => void) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }
  getSnapshot = () => this.snapshot

  nurseOnMyWay = (id: string) => {
    this.update(id, (c) => ({ ...c, status: 'nurse_en_route' }))
    this.phaseAt.set(id, Date.now() + 12_000)
  }
  resolve = (id: string) => {
    this.finish(id)
  }

  private update(id: string, fn: (c: Call) => Call) {
    this.calls = this.calls.map((c) => (c.id === id ? fn(c) : c))
    this.rebuild()
  }

  private finish(id: string) {
    const call = this.calls.find((c) => c.id === id)
    if (!call) return
    const robot = this.robots.find((r) => r.callId === id)
    if (robot) {
      robot.state = 'idle'
      robot.callId = null
      robot.targetRoom = null
    }
    this.update(id, (c) => ({
      ...c,
      status: 'resolved',
      resolvedAt: Date.now(),
      resolvedByRobot: c.handledBy === 'robot',
      feedback: Math.random() > 0.3 ? (Math.ceil(rand(3.2, 5)) as 3 | 4 | 5) : null,
    }))
  }

  /** Seeds a busy moment (one emergency, two nurse calls, a task, a chat) for demos and layout checks. */
  demoBusy() {
    for (const u of [4, 3, 3, 2, 1]) this.spawnCall(pick(SCENARIOS.filter((s) => s.urgency === u)))
  }

  private spawnCall(forced?: Scenario) {
    const busy = new Set(this.calls.filter((c) => c.status !== 'resolved').map((c) => c.residentId))
    const free = RESIDENTS.filter((r) => !busy.has(r.id))
    if (!free.length) return
    const r = pick(free)
    const roll = Math.random()
    const pool = roll < 0.08 ? SCENARIOS.filter((s) => s.urgency === 4) : roll < 0.36 ? SCENARIOS.filter((s) => s.urgency === 3) : SCENARIOS.filter((s) => s.urgency < 3)
    const sc = forced ?? pick(pool)
    const call = makeCall(sc, r, Date.now(), 'robot_en_route', null)
    this.calls = [call, ...this.calls]
    this.phaseAt.set(call.id, Date.now())
    this.dispatchWaiting()
    this.rebuild()
  }

  /** Sends a free robot to each call that is still waiting for one, oldest call first. */
  private dispatchWaiting() {
    const waiting = this.calls.filter((c) => c.status === 'robot_en_route' && !this.robots.some((r) => r.callId === c.id)).reverse()
    for (const call of waiting) {
      const robot = this.robots.find((x) => x.state === 'idle' && x.battery > 25 && !this.paths.has(x.id))
      if (!robot) return
      robot.state = 'en_route'
      robot.targetRoom = call.room
      robot.callId = call.id
      this.paths.set(robot.id, this.routeTo(robot, call.room))
      this.calls = this.calls.map((c) => (c.id === call.id ? { ...c, robotId: robot.id } : c))
    }
  }

  private routeTo(robot: Robot, room: number): Waypoint[] {
    const rm = roomByNumber(room)
    const north = rm.y < FLOOR.corridorY
    const stopY = north ? rm.y + rm.h - 28 : rm.y + 28
    return [
      { x: robot.x, y: FLOOR.corridorY },
      { x: rm.door.x, y: FLOOR.corridorY },
      { x: rm.door.x, y: stopY },
    ]
  }

  private routeHome(robot: Robot): Waypoint[] {
    return [
      { x: robot.x, y: FLOOR.corridorY },
      { x: DOCK_POINT.x, y: FLOOR.corridorY },
    ]
  }

  private moveRobots() {
    for (const r of this.robots) {
      const path = this.paths.get(r.id)
      if (path && path.length) {
        const speed = 70
        let budget = speed
        while (budget > 0 && path.length) {
          const t = path[0]
          const dx = t.x - r.x
          const dy = t.y - r.y
          const d = Math.hypot(dx, dy)
          if (d <= budget) {
            r.x = t.x
            r.y = t.y
            budget -= d
            path.shift()
          } else {
            r.x += (dx / d) * budget
            r.y += (dy / d) * budget
            budget = 0
          }
        }
        if (!path.length) {
          this.paths.delete(r.id)
          if (r.callId) {
            r.state = 'with_resident'
            this.phaseAt.set(r.callId, Date.now())
            this.update(r.callId, (c) => ({ ...c, status: c.urgency >= 3 ? 'nurse_notified' : 'robot_with_resident', firstResponseSec: Math.round((Date.now() - c.createdAt) / 1000) }))
          } else if (Math.abs(r.x - DOCK_POINT.x) < 2) {
            r.state = 'charging'
          }
        }
      }
      if (r.state === 'charging') r.battery = Math.min(100, r.battery + 0.4)
      else if (r.state !== 'idle') r.battery = Math.max(5, r.battery - 0.05)
    }
  }

  private tick() {
    this.nextCallIn -= 1
    if (this.nextCallIn <= 0 && this.calls.filter((c) => c.status !== 'resolved').length < 4) {
      this.spawnCall()
      this.nextCallIn = Math.round(rand(14, 26))
    }
    this.moveRobots()
    this.dispatchWaiting()
    const now = Date.now()
    for (const c of this.calls) {
      if (c.status === 'resolved') continue
      const at = this.phaseAt.get(c.id) ?? now
      if (c.status === 'robot_with_resident' && now - at > (c.handledBy === 'robot' ? 14_000 : 9_000)) {
        if (c.handledBy === 'robot') this.finish(c.id)
        else this.update(c.id, (x) => ({ ...x, status: 'nurse_notified' }))
        this.phaseAt.set(c.id, now)
      } else if (c.status === 'nurse_notified' && c.handledBy !== 'nurse' && now - at > 14_000) {
        this.finish(c.id)
      } else if (c.status === 'nurse_en_route' && now >= at) {
        this.finish(c.id)
      }
    }
    for (const r of this.robots) {
      if (r.state === 'idle' && !this.paths.has(r.id) && Math.abs(r.x - DOCK_POINT.x) > 2 && r.battery < 55) {
        this.paths.set(r.id, this.routeHome(r))
        r.state = 'en_route'
      }
    }
    this.rebuild()
  }


  /** Keeps a log of alerts that are not simply a call (calls have their own list): escalations and robot problems. Cleared ones stay for history. */
  private reconcileAlerts(now: number): Alert[] {
    const log = this.alertLog
    const live = new Set<string>()
    const put = (a: Omit<Alert, 'clearedAt'>, clearedAt: number) => {
      const prev = log.get(a.id)
      live.add(a.id)
      log.set(a.id, { ...a, createdAt: prev?.createdAt ?? a.createdAt, clearedAt: a.acknowledged ? prev?.clearedAt ?? clearedAt : null })
    }
    for (const c of this.calls) {
      if (c.urgency < 3) continue
      const cleared = c.status === 'resolved' || c.status === 'nurse_en_route'
      const waiting = c.handledBy === 'nurse' && !cleared && now - c.createdAt > WAIT_ALERT_MS
      if (waiting) {
        put({ id: `w-${c.id}`, callId: c.id, room: c.room, urgency: 3, message: 'Still waiting for a nurse. Please respond.', createdAt: c.createdAt + WAIT_ALERT_MS, acknowledged: false }, now)
      }
    }
    for (const r of this.robots) {
      if (r.battery < 30 && r.state !== 'charging') {
        put({ id: `b-${r.id}`, callId: null, room: null, urgency: 2, message: `${r.name} battery is low (${Math.round(r.battery)}%). Heading to the dock.`, createdAt: now, acknowledged: false }, now)
      }
    }
    for (const [id, a] of log) {
      if (!live.has(id) && !a.acknowledged) log.set(id, { ...a, acknowledged: true, clearedAt: now })
    }
    return [...log.values()].sort((a, b) => b.createdAt - a.createdAt)
  }

  private rebuild() {
    const now = Date.now()
    const residents = RESIDENTS.map((r) => {
      const mine = this.calls.filter((c) => c.residentId === r.id)
      return { ...r, callsToday: mine.length, aiCostToday: +mine.reduce((s, c) => s + c.costUsd, 0).toFixed(2) }
    })
    const hourly = Array.from({ length: 12 }, () => 0)
    for (const c of this.calls) {
      const h = Math.floor((now - c.createdAt) / (60 * MIN))
      if (h >= 0 && h < 12) hourly[11 - h] += 1
    }
    const alerts = this.reconcileAlerts(now)
    const done = this.calls.filter((c) => c.status === 'resolved')
    const metrics = {
      calls_today: this.calls.length,
      resolved_by_robot: done.filter((c) => c.resolvedByRobot).length,
      open_calls: this.calls.length - done.length,
      robots_online: this.robots.length,
    }
    this.snapshot = {
      now,
      alerts,
      metrics,
      calls: this.calls.map((c) => ({ ...c, transcript: c.transcript.slice(0, linesSoFar(c.status)) })),
      residents,
      robots: this.robots.map((r) => ({ ...r })),
      nurses: this.nurses,
      hourly,
    }
    this.listeners.forEach((l) => l())
  }
}

// A frozen snapshot with a few open calls, for theme previews and screenshots.
export function staticSnapshot(): Snapshot {
  const sim = new Simulator(false)
  const now = Date.now()
  const open: [number, CallStatus][] = [[8, 'nurse_notified'], [3, 'robot_with_resident'], [7, 'robot_en_route']]
  const open2: Call[] = []
  const wanted = [SCENARIOS[8], SCENARIOS[5], SCENARIOS[1]]
  open.forEach(([ri, status], i) => {
    const c = makeCall(wanted[i], RESIDENTS[ri], now - (i * 2 + 1) * MIN, status, 'b' + (i + 1))
    c.firstResponseSec = status === 'robot_en_route' ? null : 52
    open2.push(c)
  })
  sim.calls = [...open2, ...sim.calls]
  const robots: Robot[] = [
    { id: 'b1', name: 'Bellhop 1', state: 'with_resident', battery: 81, x: roomByNumber(109).door.x, y: roomByNumber(109).y + 28, targetRoom: 109, callId: open2[0].id },
    { id: 'b2', name: 'Bellhop 2', state: 'with_resident', battery: 63, x: roomByNumber(104).door.x, y: roomByNumber(104).y + roomByNumber(104).h - 28, targetRoom: 104, callId: open2[1].id },
    { id: 'b3', name: 'Bellhop 3', state: 'en_route', battery: 41, x: 640, y: 230, targetRoom: 108, callId: open2[2].id },
  ]
  sim.robots = robots
  // reuse the private rebuild through a cheap tick without timers
  ;(sim as unknown as { rebuild: () => void }).rebuild()
  return sim.getSnapshot()
}

export { ROOMS }
