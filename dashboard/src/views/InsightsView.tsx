import type { BellhopData } from '../data/types'
import { Bars, HBars, Ring, Stars } from '../components/Charts'
import { Kpis } from './LiveView'
import { URGENCY_LABEL, categoryCounts, clock, computeKpis, formatMetric, humanizeKey, money } from '../lib'

export function InsightsView({ data }: { data: BellhopData }) {
  const k = computeKpis(data)
  const hours = Array.from({ length: 12 }, (_, i) => {
    const h = (new Date(data.now).getHours() - 11 + i + 24) % 24
    return h === 0 ? '12a' : h < 12 ? `${h}a` : h === 12 ? '12p' : `${h - 12}p`
  })
  const cost = k.costToday
  const split = [
    { label: 'Claude (conversation, summary)', value: +(cost * 0.56).toFixed(2) },
    { label: 'Text to speech (Cartesia Sonic)', value: +(cost * 0.38).toFixed(2) },
    { label: 'Speech to text (Cartesia Ink)', value: +(cost * 0.05).toFixed(2) },
    { label: 'Triage scoring (Jev)', value: +(cost * 0.01).toFixed(2) },
  ]
  const perResident = data.residents.slice().sort((a, b) => b.aiCostToday - a.aiCostToday).slice(0, 8).map((r) => ({ label: `${r.name.split(' ')[0]} (${r.room})`, value: r.aiCostToday }))
  const levels = [1, 2, 3, 4].map((u) => ({ label: ['Level 1 robot resolves', 'Level 2 staff task', 'Level 3 needs a nurse', 'Level 4 emergency'][u - 1], value: data.calls.filter((c) => c.urgency === u).length }))
  const feedback = [5, 4, 3].map((n) => ({ label: `${n} stars`, value: data.calls.filter((c) => c.feedback === n).length }))
  const lowConf = data.calls.filter((c) => c.confidence < 0.85).length
  return (
    <>
      <Kpis data={data} />
      <div className="insight-grid">
        <section className="panel">
          <header className="panel-head">
            <h2>Response time target</h2>
          </header>
          <Ring value={k.within10} target={0.8} label="Answered within 10 minutes" sub="Target: 80% of calls. This is the 80/10 service level." />
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>Calls per hour</h2>
            <span className="muted">last 12 hours</span>
          </header>
          <Bars values={data.hourly} labels={hours} highlight={11} height={130} />
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>Why the robot was called</h2>
          </header>
          <HBars rows={categoryCounts(data.calls)} />
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>Calls by level</h2>
          </header>
          <HBars rows={levels} />
          <p className="note">{lowConf} calls had triage confidence under 85%, so Bellhop leaned toward escalating.</p>
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>Resident feedback</h2>
          </header>
          <div className="feedback-big">
            <span className="kpi-value">{k.avgFeedback ? k.avgFeedback.toFixed(1) : 'n/a'}</span>
            <Stars value={k.avgFeedback} size={22} />
          </div>
          <HBars rows={feedback} />
          <p className="note">Asked after each visit: "Did that help?"</p>
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>AI cost by service</h2>
            <span className="muted">today</span>
          </header>
          <HBars rows={split.map((s) => ({ label: s.label, value: s.value }))} unit="" />
          <p className="note">Total {money(cost)} for {k.total} calls. Staff time for the same calls would be about {money(k.byRobot * 4 * 0.413)}.</p>
        </section>
        {data.metrics && (
          <section className="panel wide">
            <header className="panel-head">
              <h2>System metrics</h2>
              <span className="muted">from the Bellhop backend</span>
            </header>
            <div className="metric-grid">
              {Object.entries(data.metrics).map(([key, value]) => (
                <div key={key} className="kpi">
                  <div className="kpi-label">{humanizeKey(key)}</div>
                  <div className="kpi-value">{formatMetric(value)}</div>
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
          {data.alerts.length === 0 ? (
            <p className="note">No alerts raised yet.</p>
          ) : (
            <ul className="alert-list">
              {data.alerts
                .slice()
                .sort((a, b) => b.createdAt - a.createdAt)
                .slice(0, 8)
                .map((a) => (
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
        <section className="panel wide">
          <header className="panel-head">
            <h2>AI cost per resident</h2>
            <span className="muted">today, top 8</span>
          </header>
          <HBars rows={perResident} />
        </section>
      </div>
    </>
  )
}
