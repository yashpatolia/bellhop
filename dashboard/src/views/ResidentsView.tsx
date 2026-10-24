import type { BellhopData } from '../data/types'
import { Sparkline } from '../components/Charts'
import { initials, money } from '../lib'

export function ResidentsView({ data }: { data: BellhopData }) {
  return (
    <div className="resident-grid">
      {data.residents.map((r) => {
        const open = data.calls.find((c) => c.residentId === r.id && c.status !== 'resolved')
        const moodDrop = r.mood[r.mood.length - 1] < r.mood[0] - 1
        const painUp = r.pain[r.pain.length - 1] > r.pain[0] + 2
        return (
          <article key={r.id} className={`panel resident ${open ? `has-u${open.urgency}` : ''}`}>
            <header className="res-head">
              <span className="avatar">{initials(r.name)}</span>
              <div>
                <h3>{r.name}</h3>
                <span className="muted">Room {r.room} · {r.age} · {r.language}</span>
              </div>
            </header>
            <div className="flags">
              {r.flags.map((f) => (
                <span key={f} className="flag">
                  {f}
                </span>
              ))}
              {moodDrop && <span className="flag watch">Quieter than usual</span>}
              {painUp && <span className="flag watch">Pain rising</span>}
            </div>
            <div className="trend-row">
              <span>Mood, 7 days</span>
              <Sparkline values={r.mood} min={1} max={5} color="var(--u1)" />
            </div>
            <div className="trend-row">
              <span>Pain, 7 days</span>
              <Sparkline values={r.pain} min={0} max={10} color="var(--u3)" />
            </div>
            <div className="res-foot">
              <span>
                <strong className="mono">{r.callsToday}</strong> calls today
              </span>
              <span>
                <strong className="mono">{money(r.aiCostToday)}</strong> AI cost
              </span>
            </div>
          </article>
        )
      })}
    </div>
  )
}
