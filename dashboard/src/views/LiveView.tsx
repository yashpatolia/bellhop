import { useState } from 'react'
import { motion } from 'motion/react'
import type { BellhopData } from '../data/types'
import { Bars, HBars } from '../components/Charts'
import { CallDetail, CallQueue, Fleet, UrgencyChip } from '../components/CallParts'
import { FloorMap } from '../components/FloorMap'
import { MIN_SAVED_PER_CALL, categoryCounts, clock, computeKpis, elapsed, isOpen, money } from '../lib'
import { CATEGORY_LABEL } from '../lib'

export function Kpis({ data }: { data: BellhopData }) {
  const k = computeKpis(data)
  const mm = Math.floor(k.medianResponseSec / 60)
  const ss = String(k.medianResponseSec % 60).padStart(2, '0')
  const items = [
    { label: 'Handled by the robot', value: `${k.byRobot}`, sub: `of ${k.total} calls today` },
    { label: 'Nurse minutes saved', value: `${k.minutesSaved}`, sub: `assumes ${MIN_SAVED_PER_CALL} min per call` },
    { label: 'Median first response', value: `${mm}:${ss}`, sub: 'minutes, bell to a voice' },
    { label: 'Answered within 10 min', value: `${Math.round(k.within10 * 100)}%`, sub: 'target is 80%', good: k.within10 >= 0.8 },
    { label: 'AI cost today', value: money(k.costToday), sub: `${money(k.costPerCall)} per call` },
  ]
  return (
    <div className="kpis">
      {items.map((it, i) => (
        <motion.div key={it.label} className="kpi" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.05 * i, duration: 0.4 }}>
          <div className="kpi-label">{it.label}</div>
          <div className="kpi-value">{it.value}</div>
          <div className={`kpi-sub ${it.good ? 'good' : ''}`}>{it.sub}</div>
        </motion.div>
      ))}
    </div>
  )
}

export function LiveView({ data }: { data: BellhopData }) {
  const open = data.calls.filter(isOpen).sort((a, b) => b.urgency - a.urgency || a.createdAt - b.createdAt)
  const [picked, setPicked] = useState<string | null>(null)
  const selected = data.calls.find((c) => c.id === picked) ?? open[0]
  const recent = data.calls.filter((c) => !isOpen(c)).sort((a, b) => (b.resolvedAt ?? 0) - (a.resolvedAt ?? 0)).slice(0, 5)
  const hours = Array.from({ length: 12 }, (_, i) => {
    const h = (new Date(data.now).getHours() - 11 + i + 24) % 24
    return h === 0 ? '12a' : h < 12 ? `${h}a` : h === 12 ? '12p' : `${h - 12}p`
  })
  return (
    <>
      <Kpis data={data} />
      <div className="live-grid">
        <CallQueue data={data} selectedId={selected?.id ?? null} onSelect={setPicked} />
        <section className="panel map-panel" aria-label="Floor view">
          <header className="panel-head">
            <h2>Floor view</h2>
            <span className="legend">
              {[1, 2, 3, 4].map((u) => (
                <span key={u} className={`lg u${u}`}>
                  <i />
                  {u}
                </span>
              ))}
            </span>
          </header>
          <FloorMap data={data} selectedRoom={selected?.room ?? null} onSelect={(room) => setPicked(open.find((c) => c.room === room)?.id ?? null)} />
          <Fleet data={data} />
        </section>
        <CallDetail call={selected} data={data} />
      </div>
      <div className="bottom-grid">
        <section className="panel">
          <header className="panel-head">
            <h2>Calls per hour</h2>
            <span className="muted">last 12 hours</span>
          </header>
          <Bars values={data.hourly} labels={hours} highlight={11} height={120} />
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>Why the robot was called</h2>
            <span className="muted">today</span>
          </header>
          <HBars rows={categoryCounts(data.calls).slice(0, 6)} />
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>Recently resolved</h2>
          </header>
          <ul className="recent">
            {recent.map((c) => {
              const r = data.residents.find((x) => x.id === c.residentId)!
              return (
                <li key={c.id}>
                  <UrgencyChip u={c.urgency} />
                  <span className="r-name">
                    {r.name} · {CATEGORY_LABEL[c.category]}
                  </span>
                  <span className="mono muted">{c.resolvedAt ? clock(c.resolvedAt) : ''}</span>
                  <span className="mono muted">{c.firstResponseSec ? elapsed(0, c.firstResponseSec * 1000) : ''}</span>
                </li>
              )
            })}
          </ul>
        </section>
      </div>
    </>
  )
}
