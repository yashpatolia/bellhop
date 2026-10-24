import { createContext, useContext, useEffect, useMemo, useSyncExternalStore } from 'react'
import type { BellhopData, Snapshot } from './types'
import { Simulator, staticSnapshot } from './mock'
import { refineLocally } from './staffEntries'
import { createLiveSource, liveEnabled } from './live'

// The one place that decides where data comes from. Today it is the mock
// simulator. To go live, return a source backed by SpacetimeDB that exposes
// the same subscribe / getSnapshot / actions shape.

export interface DataSource {
  subscribe: (fn: () => void) => () => void
  getSnapshot: () => Snapshot
  actions: BellhopData['actions']
  start: () => void
  stop: () => void
}

export function createMockSource(): DataSource {
  const sim = new Simulator(true)
  if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('demo') === 'busy') sim.demoBusy()
  return {
    subscribe: sim.subscribe,
    getSnapshot: sim.getSnapshot,
    actions: { nurseOnMyWay: sim.nurseOnMyWay, resolve: sim.resolve, refineEntry: sim.refineEntry, addEntry: sim.addEntry, reviewFact: sim.reviewFact },
    start: () => sim.start(),
    stop: () => sim.stop(),
  }
}

export const createSource = (): DataSource => (liveEnabled ? createLiveSource() : createMockSource())

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

const noop = () => {}
export function useStaticData(): BellhopData {
  return useMemo(() => ({ ...staticSnapshot(), actions: { nurseOnMyWay: noop, resolve: noop, refineEntry: refineLocally, addEntry: noop, reviewFact: noop } }), [])
}
