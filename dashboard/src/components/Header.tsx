import type { BellhopData } from '../data/types'
import { clock } from '../lib'

export type View = 'live' | 'insights' | 'residents'

const TABS: { id: View; label: string; href: string }[] = [
  { id: 'live', label: 'Live', href: '#/' },
  { id: 'insights', label: 'Insights', href: '#/insights' },
  { id: 'residents', label: 'Residents', href: '#/residents' },
]

export function Header({ data, view }: { data: BellhopData; view: View }) {
  return (
    <header className="topbar">
      <a className="brand" href="#/">
        <span className="brand-word">Bell<span>hop</span></span>
        <small>Maple Court, East Wing</small>
      </a>
      <nav className="tabs" aria-label="Dashboard views">
        {TABS.map((t) => (
          <a key={t.id} className="tab" href={t.href} aria-current={view === t.id ? 'page' : undefined}>
            {t.label}
          </a>
        ))}
      </nav>
      <div className="nurses" aria-label="Staff on duty">
        {data.nurses.map((n) => (
          <span key={n.id} className={`nurse ${n.status}`}>
            <i aria-hidden="true" />
            {n.name.replace('Nurse ', '')}
          </span>
        ))}
      </div>
      <span className="live-pill">
        <i aria-hidden="true" />
        Live · {clock(data.now)}
      </span>
    </header>
  )
}
