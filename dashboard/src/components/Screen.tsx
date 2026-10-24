import type { BellhopData } from '../data/types'
import { Header, type View } from './Header'
import { LiveView } from '../views/LiveView'
import { InsightsView } from '../views/InsightsView'
import { ResidentsView } from '../views/ResidentsView'
import { LAYOUTS } from '../layouts/registry'

export function Screen({
  data,
  view,
  theme,
  preview = false,
  residentId,
  callId,
}: {
  data: BellhopData
  view: View
  theme: string
  preview?: boolean
  residentId?: string
  callId?: string
}) {
  const Layout = LAYOUTS[theme]
  if (Layout) return <Layout data={data} view={view} theme={theme} preview={preview} residentId={residentId} callId={callId} />
  return (
    <div className={preview ? 'app screen' : 'app'} data-theme={theme}>
      <Header data={data} view={view} />
      <main className="main-area">
        {view === 'live' && <LiveView data={data} />}
        {view === 'insights' && <InsightsView data={data} />}
        {view === 'residents' && <ResidentsView data={data} />}
      </main>
    </div>
  )
}
