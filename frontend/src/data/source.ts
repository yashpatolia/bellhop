import { createContext, useContext, useEffect, useMemo, useSyncExternalStore } from 'react'
import type { BellhopData, Snapshot } from './types'
import { createLiveSource } from './store'
import { DEMO_URL, type Mode } from './mode'

// The one place that decides where data comes from: the Bellhop backend (contracts/openapi.json).
// With nothing in the backend you get an empty home; with the simulator running (see
// artifacts/components/simulator.md) you get a populated one. The screens cannot tell the difference.

export interface DataSource {
  subscribe: (fn: () => void) => () => void
  getSnapshot: () => Snapshot
  actions: BellhopData['actions']
  start: () => void
  stop: () => void
}

/**
 * `auto` lets one Vite dashboard serve both the laptop and a touchscreen over Tailscale.
 * Loopback is correct for the laptop browser; a remote screen reaches the backend at the same
 * tailnet host from which it loaded the dashboard. An explicit URL always wins for deployments.
 */
export function apiUrlForHost(hostname: string, configured?: string): string {
  if (configured && configured !== 'auto') return configured
  if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '::1') {
    return 'http://127.0.0.1:8000'
  }
  return configured === 'auto' && hostname ? `http://${hostname}:8000` : 'http://127.0.0.1:8000'
}

const configuredApi = import.meta.env.VITE_BELLHOP_API_URL as string | undefined
const browserHost = typeof window === 'undefined' ? '' : window.location.hostname
export const API_URL = apiUrlForHost(browserHost, configuredApi)

export const createSource = (mode: Mode = 'live'): DataSource =>
  mode === 'demo'
    ? createLiveSource({ baseUrl: DEMO_URL })
    : createLiveSource({ baseUrl: API_URL, apiKey: import.meta.env.VITE_BELLHOP_API_KEY as string | undefined })

export const DataContext = createContext<BellhopData | null>(null)

export function useLiveData(source: DataSource): BellhopData {
  useEffect(() => {
    source.start()
    return () => source.stop()
  }, [source])
  const snap = useSyncExternalStore(source.subscribe, source.getSnapshot)
  return useMemo(() => ({ ...snap, actions: source.actions }), [snap, source])
}

export function useData(): BellhopData {
  const d = useContext(DataContext)
  if (!d) throw new Error('DataContext missing')
  return d
}
