import { motion } from 'motion/react'
import type { BellhopData } from '../data/types'
import { Bars, HBars, Ring } from '../components/Charts'
import { MIN_SAVED_PER_CALL, URGENCY_LABEL, categoryCounts, clock, computeKpis, formatMetric, humanizeKey } from '../lib'

function Kpis({ data }: { data: BellhopData }) {
  const k = computeKpis(data)
  const mm = Math.floor(k.medianResponseSec / 60)
  const ss = String(k.medianResponseSec % 60).padStart(2, '0')
  const items = [
    { label: 'Handled by the robot', value: `${k.byRobot}`, sub: `of ${k.total} calls today` },
    { label: 'Nurse minutes saved', value: `${k.minutesSaved}`, sub: `assumes ${MIN_SAVED_PER_CALL} min per call` },
    { label: 'Median first response', value: `${mm}:${ss}`, sub: 'minutes, bell to a voice' },
    { label: 'Answered within 10 min', value: `${Math.round(k.within10 * 100)}%`, sub: 'target is 80%', good: k.within10 >= 0.8 },
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

export function InsightsView({ data }: { data: BellhopData }) {
  const k = computeKpis(data)
  const hours = Array.from({ length: 12 }, (_, i) => {
    const h = (new Date(data.now).getHours() - 11 + i + 24) % 24
    return h === 0 ? '12a' : h < 12 ? `${h}a` : h === 12 ? '12p' : `${h - 12}p`
  })
  const last12 = Array.from({ length: 12 }, (_, i) => data.hourly[(new Date(data.now).getHours() - 11 + i + 24) % 24])
  const levels = [1, 2, 3, 4].map((u) => ({ label: ['Level 1 robot resolves', 'Level 2 staff task', 'Level 3 needs a nurse', 'Level 4 emergency'][u - 1], value: data.calls.filter((c) => c.urgency === u).length }))
  const alerts = data.alerts.slice().sort((a, b) => b.createdAt - a.createdAt).slice(0, 8)
  return (
    <>
      <Kpis data={data} />
      <div className="insight-grid">
        <section className="panel">
          <header className="panel-head">
            <h2>Response time target</h2>
          </header>
          <Ring value={k.within10} target={0.8} label="Answered within 10 minutes" sub="The goal is 8 in every 10 calls answered within 10 minutes." />
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>Calls per hour</h2>
            <span className="muted">last 12 hours</span>
          </header>
          <Bars values={last12} labels={hours} highlight={11} height={130} />
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>Why the robot was called</h2>
          </header>
          {data.calls.length === 0 ? <p className="note">No calls yet today.</p> : <HBars rows={categoryCounts(data.calls)} />}
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>Calls by level</h2>
          </header>
          <HBars rows={levels} />
        </section>
        {data.metrics && (
          <section className="panel wide">
            <header className="panel-head">
              <h2>System metrics</h2>
              <span className="muted">from the Bellhop backend, all time</span>
            </header>
            <div className="metric-grid">
              {Object.entries(data.metrics).map(([key, value]) => (
                <div key={key} className="kpi">
                  <div className="kpi-label">{humanizeKey(key)}</div>
                  <div className="kpi-value">{formatMetric(value, key)}</div>
                </div>
              ))}
            </div>
          </section>
        )}
        <section className="panel wide">
          <header className="panel-head">
            <h2>Alerts</h2>
            <span className="muted">{data.alerts.filter((a) => !a.acknowledged).length} active</span>
          </header>
          {alerts.length === 0 ? (
            <p className="note">No alerts raised yet.</p>
          ) : (
            <ul className="alert-list">
              {alerts.map((a) => (
                <li key={a.id}>
                  <span className={`chip u${a.urgency}`}>{URGENCY_LABEL[a.urgency]}</span>
                  <strong>{a.room ? `Room ${a.room}` : 'Alert'}</strong>
                  <span>{a.message}</span>
                  <span className="alert-state">
                    {clock(a.createdAt)} · {a.acknowledged ? 'Handled' : 'Needs attention'}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </>
  )
}
