import type { LayoutProps } from '../registry'
import { InsightsView } from '../../views/InsightsView'
import { clock } from '../../lib'
import { Activity, ConnectionBanner, Detail, Earlier, Nav, Numbers, Robots, Summary } from '../shared'
import { useBoard } from '../board'
import { useMode } from '../../data/mode'
import { LogoMark } from '../../components/Logo'
import { DispatchPage } from './DispatchPage'
import { ResidentsPage } from './ResidentsPage'
import './layout.css'

export default function Layout({ data, view, residentId, callId, room }: LayoutProps) {
  const { selected, pick } = useBoard(data)
  const { mode, setMode } = useMode()
  return (
    <div className="lx lx-sumi" data-theme="sumi">
      <div className="sm-shell">
        <header className="sm-top">
          <a className="sm-brand" href="#/" title="Bellhop home page">
            <LogoMark size={30} />
            Bellhop<small>Maple Court, East Wing</small>
          </a>
          <Nav view={view} />
          <button type="button" className="sm-demo" aria-pressed={mode === 'demo'} onClick={() => setMode(mode === 'demo' ? 'live' : 'demo')}>
            {mode === 'demo' ? 'Exit demo' : 'Demo'}
          </button>
          <span className="sm-clock">{clock(data.now)}</span>
        </header>
        <ConnectionBanner data={data} />
        {view === 'live' ? (
          <>
            <section className="sm-first">
              <div className="sm-main">
                <section className="sm-focus" aria-label="Most urgent call">
                  <Summary data={data} />
                  <Detail call={selected} data={data} />
                </section>
                <aside className="sm-side">
                  <div className="sm-log">
                    <Activity data={data} onPick={pick} selectedId={selected?.id} actions startOn="open" />
                  </div>
                  <div className="sm-bots">
                    <h2>Robots</h2>
                    <Robots data={data} />
                  </div>
                </aside>
              </div>
              <footer className="sm-strip">
                <Numbers data={data} />
              </footer>
            </section>
            <section className="sm-earlier">
              <h2>Earlier today</h2>
              <Earlier data={data} />
            </section>
          </>
        ) : (
          <div className="sm-plain">{view === 'insights' ? <InsightsView data={data} /> : view === 'dispatch' ? <DispatchPage data={data} room={room} /> : <ResidentsPage data={data} residentId={residentId} callId={callId} />}</div>
        )}
      </div>
    </div>
  )
}
