import { useState, type ReactNode } from 'react'
import type { BellhopData, Call, Resident, Urgency } from '../data/types'
import { useMode } from '../data/mode'
import { Bars, HBars, Sparkline } from '../components/Charts'
import {
  CATEGORY_LABEL,
  MIN_SAVED_PER_CALL,
  URGENCY_LABEL,
  categoryCounts,
  clock,
  computeKpis,
  elapsed,
  activeAlerts,
  isOpen,
  statusText,
} from '../lib'
import { NAV, ROBOT_WORDS, residentOf } from './board'
import './shared.css'

/** A few of the things Bellhop has learned and is using, as one plain sentence. */
function known(r: Resident): string {
  const facts = r.learned.filter((f) => f.status === 'active' && f.kind !== 'health').slice(0, 3)
  return facts.length ? facts.map((f) => f.text).join('. ') + '.' : 'Nothing learned about them yet.'
}

/** What Bellhop learned from this conversation, saved or waiting for a nurse, newest last. */
function learnedIn(call: Call, r: Resident | undefined) {
  return r ? r.learned.filter((f) => f.callId === call.id) : []
}

export function Chip({ u }: { u: Urgency }) {
  return <span className={`sb-chip u${u}`}>{URGENCY_LABEL[u]}</span>
}

/** A nurse call can be answered the moment it exists. Staff tasks wait until they are handed over. */
export function Action({ call, data, big }: { call: Call; data: BellhopData; big?: boolean }) {
  const [busy, setBusy] = useState(false)
  if (call.status === 'resolved') return null
  const nurse = call.handledBy === 'nurse'
  let label = ''
  let run: () => Promise<void> = async () => {}
  let primary = false
  if (nurse && call.status !== 'nurse_en_route') {
    label = 'I’m on my way'
    primary = true
    run = () => data.actions.nurseOnMyWay(call.id)
  } else if (nurse || call.status === 'nurse_notified') {
    label = 'Mark done'
    run = () => data.actions.resolve(call.id)
  } else return null
  return (
    <button
      className={`sb-btn ${primary ? 'primary' : ''} ${big ? 'big' : ''}`}
      onClick={(e) => {
        e.stopPropagation()
        if (busy) return
        setBusy(true)
        void run().finally(() => setBusy(false))
      }}
      disabled={busy}
    >
      {busy ? 'Saving…' : label}
    </button>
  )
}

export function Nav({ view }: { view: string }) {
  return (
    <nav className="sb-nav" aria-label="Dashboard views">
      {NAV.map((n) => (
        <a key={n.id} href={n.href} aria-current={view === n.id ? 'page' : undefined}>
          {n.label}
        </a>
      ))}
    </nav>
  )
}

function Battery({ pct, charging }: { pct: number; charging: boolean }) {
  const level = Math.max(0, Math.min(100, pct))
  return (
    <svg className="sb-battery" viewBox="0 0 28 14" width="28" height="14" aria-hidden="true">
      <rect x="0.75" y="0.75" width="23.5" height="12.5" rx="2.5" fill="none" stroke="currentColor" strokeWidth="1.5" />
      <rect x="25" y="4.5" width="2.25" height="5" rx="1" fill="currentColor" />
      <rect x="2.75" y="2.75" width={(level / 100) * 19.5} height="8.5" rx="1" fill="currentColor" />
      {charging && <path d="M13.5 2 L9 7.5 H12.5 L11 12 L16.5 6 H13 Z" fill="var(--bg)" stroke="currentColor" strokeWidth="0.6" />}
    </svg>
  )
}

export function Robots({ data }: { data: BellhopData }) {
  return (
    <ul className="sb-robots" aria-label="Robots">
      {data.robots.map((r) => {
        const offline = r.state === 'offline'
        const low = r.battery < 30 && r.state !== 'charging' && !offline
        return (
          <li key={r.id} className={low ? 'low' : ''}>
            <b>{r.name}</b>
            <span>
              {ROBOT_WORDS[r.state]}
              {r.targetRoom ? `, room ${r.targetRoom}` : ''}
            </span>
            {offline ? (
              <em>No battery report</em>
            ) : (
              <em>
                <Battery pct={r.battery} charging={r.state === 'charging'} />
                {Math.round(r.battery)}%{low ? ' low' : ''}
              </em>
            )}
          </li>
        )
      })}
    </ul>
  )
}

export function Numbers({ data }: { data: BellhopData }) {
  const k = computeKpis(data)
  const mm = Math.floor(k.medianResponseSec / 60)
  const ss = String(k.medianResponseSec % 60).padStart(2, '0')
  const items = [
    { v: `${k.byRobot} of ${k.total}`, l: 'calls handled by the robot' },
    { v: `${k.minutesSaved} min`, l: `nurse time saved (${MIN_SAVED_PER_CALL} min per call)` },
    { v: `${mm}:${ss}`, l: 'median time to a first voice' },
    { v: `${Math.round(k.within10 * 100)}%`, l: `answered within 10 min (target 80%)` },
  ]
  return (
    <dl className="sb-numbers" aria-label="Today in numbers">
      {items.map((it) => (
        <div key={it.l}>
          <dt>{it.l}</dt>
          <dd>{it.v}</dd>
        </div>
      ))}
    </dl>
  )
}

export function Summary({ data }: { data: BellhopData }) {
  const open = data.calls.filter(isOpen)
  const n = (u: Urgency) => open.filter((c) => c.urgency === u).length
  return (
    <p className="sb-summary">
      <b>{n(4)}</b> {n(4) === 1 ? 'emergency' : 'emergencies'}, <b>{n(3)}</b> {n(3) === 1 ? 'needs' : 'need'} a nurse, <b>{n(2)}</b> staff {n(2) === 1 ? 'task' : 'tasks'}, <b>{n(1)}</b> robot {n(1) === 1 ? 'chat' : 'chats'}
    </p>
  )
}

export function Detail({ call, data, empty }: { call: Call | undefined; data: BellhopData; empty?: ReactNode }) {
  if (!call) {
    return (
      <div className="sb-detail sb-quiet">
        <h2>All clear</h2>
        <p>{empty ?? 'No open calls. The robots are standing by.'}</p>
      </div>
    )
  }
  const r = residentOf(data, call)
  const talked = call.status !== 'robot_en_route'
  return (
    <article className={`sb-detail u${call.urgency}`} key={call.id}>
      <header className="sb-detail-head">
        <div>
          <h2>
            Room {call.room}, {r?.name}
          </h2>
          <p className="sb-sub">
            {CATEGORY_LABEL[call.category]}, called {clock(call.createdAt)}, {call.resolvedAt ? `resolved after ${elapsed(call.createdAt, call.resolvedAt)}` : `waiting ${elapsed(call.createdAt, data.now)}`}
          </p>
        </div>
        <Chip u={call.urgency} />
      </header>
      <p className="sb-status">{statusText(call)}</p>
      <Action call={call} data={data} big />

      <h3>Nurse summary</h3>
      {call.summary ? (
        <p className="sb-summary-text">{call.summary}</p>
      ) : (
        <p className="sb-wait">{talked ? 'Bellhop is still working out what is needed.' : 'The summary appears once Bellhop has talked with the resident.'}</p>
      )}
      {r && (
        <p className="sb-know">
          <strong>Background. </strong>
          {r.name}{r.age ? `, ${r.age}` : ''}. {r.flags.length ? r.flags.join(', ') : 'No flags'}.
        </p>
      )}

      {call.transcript.length === 0 && isOpen(call) && (
        <>
          <h3>Conversation</h3>
          <p className="sb-wait">
            {data.robots.some((b) => b.callId === call.id) ? 'The conversation starts when the robot reaches the room.' : 'Waiting for a free robot. The conversation starts when one arrives.'}
          </p>
        </>
      )}
      {call.transcript.length > 0 && (
        <>
          <h3>Conversation</h3>
          <div className="sb-talk">
            {call.transcript.map((t, i) => (
              <p key={i} className={t.who}>
                <span>{t.who === 'resident' ? r?.name.split(' ')[0] : t.who === 'robot' ? 'Bellhop' : 'Nurse'}</span>
                {t.text}
              </p>
            ))}
            {learnedIn(call, r).map((f) => (
              <p key={f.id} className="learned">
                <span>Bellhop</span>
                <b>Learned about {r?.name.split(' ')[0]}:</b> {f.text}
                <em>{f.status === 'pending' ? 'Waiting for a nurse to confirm' : 'Saved to their profile'}</em>
              </p>
            ))}
            <p className="sb-end">
              {call.status === 'resolved' ? `Conversation ended${call.resolvedAt ? `, ${clock(call.resolvedAt)}` : ''}` : 'Conversation in progress'}
            </p>
          </div>
        </>
      )}

      {r && (
        <>
          <h3>What Bellhop knows</h3>
          <p className="sb-know">{known(r)}</p>
        </>
      )}
    </article>
  )
}

/** Secondary material, kept below the first screen. */
export function Earlier({ data }: { data: BellhopData }) {
  const hours = Array.from({ length: 12 }, (_, i) => {
    const h = (new Date(data.now).getHours() - 11 + i + 24) % 24
    return h === 0 ? '12a' : h < 12 ? `${h}a` : h === 12 ? '12p' : `${h - 12}p`
  })
  const recent = data.calls
    .filter((c) => !isOpen(c))
    .sort((a, b) => (b.resolvedAt ?? 0) - (a.resolvedAt ?? 0))
    .slice(0, 6)
  return (
    <section className="sb-earlier" aria-label="Earlier today">
      <div>
        <h3>Calls per hour</h3>
        <Bars values={data.hourly} labels={hours} highlight={11} height={90} />
      </div>
      <div>
        <h3>Why the robot was called</h3>
        <HBars rows={categoryCounts(data.calls).slice(0, 5)} />
      </div>
      <div>
        <h3>Recently resolved</h3>
        <ul className="sb-recent">
          {recent.map((c) => (
            <li key={c.id}>
              <span>
                {residentOf(data, c)?.name}, {CATEGORY_LABEL[c.category].toLowerCase()}
              </span>
              <time>{c.resolvedAt ? clock(c.resolvedAt) : ''}</time>
            </li>
          ))}
        </ul>
      </div>
    </section>
  )
}

export function Mood({ values }: { values: number[] }) {
  return <Sparkline values={values} min={1} max={5} w={110} h={26} />
}

/** One open call as a plain row: who, why, how long, status, and the action. */
export function CallRow({ call, data, selected, onPick, showChip = true }: { call: Call; data: BellhopData; selected: boolean; onPick: (id: string) => void; showChip?: boolean }) {
  const r = residentOf(data, call)
  return (
    <li className={`sb-row u${call.urgency} ${selected ? 'sel' : ''}`}>
      <button className="sb-row-main" onClick={() => onPick(call.id)} aria-pressed={selected}>
        <span className="sb-row-top">
          {showChip && <Chip u={call.urgency} />}
          <b>Room {call.room}</b>
          <span className="sb-row-name">{r?.name}</span>
          <time>{elapsed(call.createdAt, data.now)}</time>
        </span>
        <span className="sb-row-why">
          {CATEGORY_LABEL[call.category]}. {statusText(call)}
        </span>
      </button>
      <Action call={call} data={data} />
    </li>
  )
}

type LogTab = 'open' | 'all' | 'done'
type LogLevel = 'all' | 4 | 3 | 2

interface LogEvent {
  id: string
  at: number
  urgency: Urgency
  room: string | null
  text: string
  open: boolean
  callId?: string
}

/** One time-ordered feed of what happened: calls raised and resolved, alerts raised and cleared. */
function buildLog(data: BellhopData): LogEvent[] {
  const ev: LogEvent[] = []
  const stillActive = new Set(activeAlerts(data).map((a) => a.id))
  for (const c of data.calls) {
    const who = residentOf(data, c)?.name ?? 'Resident'
    const what = `${who}, ${CATEGORY_LABEL[c.category].toLowerCase()}`
    if (c.status === 'resolved') {
      const by = c.resolvedByRobot ? 'Resolved by the robot' : 'Resolved by staff'
      ev.push({ id: `c-${c.id}`, at: c.resolvedAt ?? c.createdAt, urgency: c.urgency, room: c.room, text: `${what}. ${by}`, open: false, callId: c.id })
    } else {
      ev.push({ id: `c-${c.id}`, at: c.createdAt, urgency: c.urgency, room: c.room, text: what, open: true, callId: c.id })
    }
  }
  for (const a of data.alerts) {
    ev.push({ id: `a-${a.id}`, at: a.createdAt, urgency: a.urgency, room: a.room, text: a.message, open: stillActive.has(a.id) })
    if (!stillActive.has(a.id) && a.clearedAt) ev.push({ id: `x-${a.id}`, at: a.clearedAt, urgency: a.urgency, room: a.room, text: `Cleared. ${a.message}`, open: false })
  }
  return ev.sort((a, b) => b.at - a.at).slice(0, 80)
}

/** The activity log side panel. Open items can be picked; with `actions` they also carry their action button. */
export function Activity({ data, onPick, selectedId, actions, startOn = 'all' }: { data: BellhopData; onPick?: (id: string) => void; selectedId?: string; actions?: boolean; startOn?: LogTab }) {
  const [tab, setTab] = useState<LogTab>(startOn)
  const [level, setLevel] = useState<LogLevel>('all')
  const all = buildLog(data)
  const openCount = all.filter((e) => e.open).length
  let shown = all.filter((e) => (tab === 'all' ? true : tab === 'open' ? e.open : !e.open))
  shown = shown.filter((e) => level === 'all' || (level === 2 ? e.urgency <= 2 : e.urgency === level))
  if (tab === 'open') shown = shown.sort((a, b) => b.urgency - a.urgency || a.at - b.at)
  const hot = all.some((e) => e.open && e.urgency === 4)
  const tabs: { id: LogTab; label: string; n?: number }[] = [
    { id: 'open', label: 'Open', n: openCount },
    { id: 'all', label: 'All' },
    { id: 'done', label: 'Done' },
  ]
  const levels: { id: LogLevel; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 4, label: 'Emergency' },
    { id: 3, label: 'Nurse' },
    { id: 2, label: 'Other' },
  ]
  return (
    <section className={`sb-act ${hot ? 'hot' : ''}`} role="region" aria-label="Activity log">
      <h2>Activity</h2>
      <div className="sb-seg" role="group" aria-label="Show">
        {tabs.map((t) => (
          <button key={t.id} className={tab === t.id ? 'on' : ''} aria-pressed={tab === t.id} onClick={() => setTab(t.id)}>
            {t.label}
            {t.n !== undefined && <b>{t.n}</b>}
          </button>
        ))}
      </div>
      <div className="sb-seg slim" role="group" aria-label="Filter by level">
        {levels.map((l) => (
          <button key={String(l.id)} className={level === l.id ? 'on' : ''} aria-pressed={level === l.id} onClick={() => setLevel(l.id)}>
            {l.label}
          </button>
        ))}
      </div>
      {shown.length === 0 ? (
        <p className="sb-act-none">Nothing here.</p>
      ) : (
        <ul>
          {shown.map((e) => {
            const call = e.callId && e.open ? data.calls.find((c) => c.id === e.callId) : undefined
            return (
              <li key={e.id} className={`u${e.urgency} ${e.open ? 'open' : 'done'} ${e.callId && e.callId === selectedId ? 'sel' : ''}`}>
                <Chip u={e.urgency} />
                <time>{clock(e.at)}</time>
                <b>{e.room ? `Room ${e.room}` : 'Robot'}</b>
                {onPick && e.callId ? (
                  <button className="sb-act-text" onClick={() => onPick(e.callId!)} aria-label={`Show ${e.text}`}>
                    {e.text}
                  </button>
                ) : (
                  <span>{e.text}</span>
                )}
                {call && <small>{statusText(call)}</small>}
                {call && actions && <Action call={call} data={data} />}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

/** Says plainly when the screens are not showing live data, when an action failed, or when the home is empty. */
export function ConnectionBanner({ data }: { data: BellhopData }) {
  const { mode, setMode } = useMode()
  const { state, problem, empty } = data.connection
  if (mode === 'demo') {
    const down = state === 'offline' || Boolean(problem)
    return (
      <p className={`sb-banner demo ${down ? 'bad' : ''}`} role={down ? 'alert' : 'status'}>
        {down
          ? 'The demo is not running. Start it with scripts/dev.sh demo, or go back to the real home.'
          : 'Demo mode: these are made-up residents and calls, not your real home.'}{' '}
        <button type="button" className="sb-link" onClick={() => setMode('live')}>
          Exit demo
        </button>
      </p>
    )
  }
  if (state === 'connecting') return <p className="sb-banner" role="status">Connecting to Bellhop...</p>
  if (problem) {
    return (
      <p className={`sb-banner ${state === 'offline' ? 'bad' : ''}`} role="alert">
        {problem}
      </p>
    )
  }
  if (empty) {
    return (
      <p className="sb-banner" role="status">
        This home is empty. Add residents on the Residents tab and robots on the Dispatch tab, or press Demo to look around an example home.
      </p>
    )
  }
  return null
}
