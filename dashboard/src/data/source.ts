import { createContext, useContext, useEffect, useMemo, useSyncExternalStore } from 'react'
import type { BellhopData, Snapshot } from './types'
import { createLiveSource } from './store'

// The one place that decides where data comes from: the Bellhop backend (contracts/openapi.json).
// With nothing in the backend you get an empty home; with the simulator running (see
// simulator/README.md) you get a populated one. The screens cannot tell the difference.

export interface DataSource {
  subscribe: (fn: () => void) => () => void
  getSnapshot: () => Snapshot
  actions: BellhopData['actions']
  start: () => void
  stop: () => void
}

export const API_URL = (import.meta.env.VITE_BELLHOP_API_URL as string | undefined) ?? 'http://127.0.0.1:8000'

export const createSource = (): DataSource => createLiveSource({ baseUrl: API_URL, apiKey: import.meta.env.VITE_BELLHOP_API_KEY as string | undefined })

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
