import { useMemo, useState, useSyncExternalStore } from 'react'
import type { BellhopData, Call } from '../data/types'
import { isOpen } from '../lib'

export const ROBOT_WORDS: Record<string, string> = { idle: 'Standing by', en_route: 'Driving', with_resident: 'With a resident', charging: 'Charging', fault: 'Needs attention' }

export const NAV = [
  { id: 'live', label: 'Live', href: '#/live' },
  { id: 'dispatch', label: 'Dispatch', href: '#/dispatch' },
  { id: 'insights', label: 'Insights', href: '#/insights' },
  { id: 'residents', label: 'Residents', href: '#/residents' },
]

/** Open calls, most urgent first, and the one currently selected (defaults to the most urgent). */
export function useBoard(data: BellhopData) {
  const [picked, setPicked] = useState<string | null>(null)
  const open = useMemo(() => data.calls.filter(isOpen).sort((a, b) => b.urgency - a.urgency || a.createdAt - b.createdAt), [data.calls])
  const selected = data.calls.find((c) => c.id === picked) ?? open[0]
  return { open, selected, pick: setPicked }
}

export const residentOf = (data: BellhopData, c: Call) => data.residents.find((r) => r.id === c.residentId)

/** Robots driven from the Dispatch tab during this visit to the dashboard, newest first. */
export interface Dispatched {
  robotId: string
  room: string
  at: number
}

let dispatched: Dispatched[] = []
const watchers = new Set<() => void>()

export function recordDispatch(entry: Dispatched) {
  dispatched = [entry, ...dispatched]
  for (const fn of watchers) fn()
}

export function useDispatched(): Dispatched[] {
  return useSyncExternalStore(
    (fn) => {
      watchers.add(fn)
      return () => watchers.delete(fn)
    },
    () => dispatched,
  )
}
