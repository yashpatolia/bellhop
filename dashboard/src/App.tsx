import { useEffect, useMemo, useState } from 'react'
import { createSource, useLiveData } from './data/source'
import { Screen } from './components/Screen'
import type { View } from './components/Header'

const THEME = 'sumi'

function readRoute(): string {
  return window.location.hash.replace(/^#\/?/, '').split('?')[0]
}

export default function App() {
  const source = useMemo(() => createSource(), [])
  const data = useLiveData(source)
  const [route, setRoute] = useState(readRoute)

  useEffect(() => {
    const on = () => setRoute(readRoute())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = THEME
  }, [])

  const [page, residentId, callId] = route.split('/')
  const view: View = page === 'insights' ? 'insights' : page === 'residents' ? 'residents' : 'live'
  return <Screen data={data} view={view} theme={THEME} residentId={residentId || undefined} callId={callId || undefined} />
}
