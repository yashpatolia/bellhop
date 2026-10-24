import type { LayoutProps } from '../registry'
import { InsightsView } from '../../views/InsightsView'
import { clock } from '../../lib'
import { Activity, Detail, Earlier, Nav, Numbers, Robots, Summary, useBoard } from '../shared'
import { ResidentsPage } from './ResidentsPage'
import './layout.css'

export default function Layout({ data, view, preview, residentId, callId }: LayoutProps) {
  const { selected, pick } = useBoard(data)
  return (
    <div className={'lx lx-sumi' + (preview ? ' screen' : '')} data-theme="sumi">
      <div className="sm-shell">
        <header className="sm-top">
          <a className="sm-brand" href="#/">
            Bellhop<small>Maple Court, East Wing</small>
          </a>
          <Nav view={view} />
          <span className="sm-clock">{clock(data.now)}</span>
        </header>
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
          <div className="sm-plain">{view === 'insights' ? <InsightsView data={data} /> : <ResidentsPage data={data} residentId={residentId} callId={callId} />}</div>
        )}
      </div>
    </div>
  )
}
