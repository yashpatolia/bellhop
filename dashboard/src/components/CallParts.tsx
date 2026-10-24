import { AnimatePresence, motion } from 'motion/react'
import type { BellhopData, Call, Robot } from '../data/types'
import { CATEGORY_LABEL, URGENCY_LABEL, clock, elapsed, initials, isOpen, money, statusText } from '../lib'
import { Stars } from './Charts'

export function UrgencyChip({ u }: { u: 1 | 2 | 3 | 4 }) {
  return <span className={`chip u${u}`}>{URGENCY_LABEL[u]}</span>
}

export function CallCard({ call, data, selected, onSelect }: { call: Call; data: BellhopData; selected: boolean; onSelect: () => void }) {
  const res = data.residents.find((r) => r.id === call.residentId)!
  const canAct = call.status === 'nurse_notified'
  const nurseCall = call.handledBy === 'nurse'
  return (
    <motion.li
      layout
      initial={{ opacity: 0, y: 14, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: -20 }}
      transition={{ type: 'spring', stiffness: 380, damping: 32 }}
      className={`call u${call.urgency} ${selected ? 'sel' : ''}`}
    >
      <button className="call-main" onClick={onSelect} aria-pressed={selected}>
        <span className="avatar">{initials(res.name)}</span>
        <span className="call-body">
          <span className="call-top">
            <strong>
              Room {call.room} · {res.name}
            </strong>
            <span className="mono timer">{elapsed(call.createdAt, data.now)}</span>
          </span>
          <span className="call-mid">
            <UrgencyChip u={call.urgency} />
            <span className="why">{CATEGORY_LABEL[call.category]}</span>
          </span>
          <span className="call-status">{statusText(call)}</span>
        </span>
      </button>
      {canAct && (
        <div className="call-actions">
          {nurseCall ? (
            <button className="btn primary" onClick={() => data.actions.nurseOnMyWay(call.id)}>
              I'm on my way
            </button>
          ) : (
            <button className="btn" onClick={() => data.actions.resolve(call.id)}>
              Mark done
            </button>
          )}
        </div>
      )}
    </motion.li>
  )
}

export function CallQueue({ data, selectedId, onSelect }: { data: BellhopData; selectedId: string | null; onSelect: (id: string) => void }) {
  const open = data.calls.filter(isOpen).sort((a, b) => b.urgency - a.urgency || a.createdAt - b.createdAt)
  return (
    <section className="panel queue" aria-label="Open calls">
      <header className="panel-head">
        <h2>Open calls</h2>
        <span className="count">{open.length}</span>
      </header>
      {open.length === 0 ? (
        <p className="empty">All quiet. The robots are on standby.</p>
      ) : (
        <ul className="calls">
          <AnimatePresence initial={false}>
            {open.map((c) => (
              <CallCard key={c.id} call={c} data={data} selected={c.id === selectedId} onSelect={() => onSelect(c.id)} />
            ))}
          </AnimatePresence>
        </ul>
      )}
    </section>
  )
}

export function CallDetail({ call, data }: { call: Call | undefined; data: BellhopData }) {
  if (!call) {
    return (
      <section className="panel detail">
        <header className="panel-head">
          <h2>Call details</h2>
        </header>
        <p className="empty">Select a call to see why the robot was called, the nurse summary and the conversation.</p>
      </section>
    )
  }
  const res = data.residents.find((r) => r.id === call.residentId)!
  return (
    <section className="panel detail" aria-label="Call details">
      <header className="panel-head">
        <h2>
          Room {call.room} · {res.name}
        </h2>
        <UrgencyChip u={call.urgency} />
      </header>
      <div className="detail-meta">
        <span className="why-big">{CATEGORY_LABEL[call.category]}</span>
        <span className="mono">Triage confidence {Math.round(call.confidence * 100)}%</span>
        <span className="mono">Called {clock(call.createdAt)}</span>
      </div>
      {res.flags.length > 0 && (
        <div className="flags">
          {res.flags.map((f) => (
            <span key={f} className="flag">
              {f}
            </span>
          ))}
        </div>
      )}
      <h3>Nurse summary</h3>
      <dl className="sbar">
        <dt>Situation</dt>
        <dd>{call.sbar.s}</dd>
        <dt>Background</dt>
        <dd>{call.sbar.b}</dd>
        <dt>Assessment</dt>
        <dd>{call.sbar.a}</dd>
        <dt>Recommendation</dt>
        <dd>{call.sbar.r}</dd>
      </dl>
      <h3>Conversation</h3>
      <div className="transcript">
        {call.transcript.map((t, i) => (
          <p key={i} className={`bubble ${t.who}`}>
            <span className="who">{t.who === 'resident' ? res.name.split(' ')[0] : 'Bellhop'}</span>
            {t.text}
          </p>
        ))}
      </div>
      <h3>What Bellhop remembers</h3>
      <ul className="memory">
        {res.likes.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
      {call.status === 'resolved' && call.feedback && (
        <div className="feedback-row">
          <span>Resident feedback</span>
          <Stars value={call.feedback} />
        </div>
      )}
      <div className="detail-cost mono">AI cost for this call {money(call.costUsd)}</div>
    </section>
  )
}

const ROBOT_STATE: Record<Robot['state'], string> = {
  idle: 'Standing by',
  en_route: 'Driving',
  with_resident: 'With a resident',
  charging: 'Charging',
}

export function Fleet({ data }: { data: BellhopData }) {
  return (
    <div className="fleet">
      {data.robots.map((r) => (
        <div key={r.id} className="robot-card">
          <div className="robot-top">
            <strong>{r.name}</strong>
            <span className={`dot ${r.state}`} aria-hidden="true" />
          </div>
          <div className="robot-state">{ROBOT_STATE[r.state]}{r.targetRoom ? ` · room ${r.targetRoom}` : ''}</div>
          <div className="battery" role="img" aria-label={`Battery ${Math.round(r.battery)} percent`}>
            <span className={r.battery < 30 ? 'low' : ''} style={{ width: `${r.battery}%` }} />
          </div>
          <div className="mono tiny">{Math.round(r.battery)}%</div>
        </div>
      ))}
    </div>
  )
}
