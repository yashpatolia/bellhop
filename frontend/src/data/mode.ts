import { createContext, useContext } from 'react'

// Which backend the dashboard reads. "live" is the real home; "demo" is a second backend that the
// simulator feeds with example residents and bell presses. The dashboard holds no mock data either way.
export type Mode = 'live' | 'demo'

export const DEMO_URL = (import.meta.env.VITE_BELLHOP_DEMO_URL as string | undefined) ?? 'http://127.0.0.1:8001'

const KEY = 'bellhop.mode'

export function readMode(): Mode {
  // A shared link like /?mode=demo#/live opens the demo; the choice is remembered and the
  // parameter dropped from the address, so Exit demo still works after a reload.
  const asked = new URLSearchParams(window.location?.search ?? '').get('mode')
  if (asked === 'demo' || asked === 'live') {
    saveMode(asked)
    window.history?.replaceState(null, '', window.location.pathname + window.location.hash)
    return asked
  }
  try {
    return window.localStorage.getItem(KEY) === 'demo' ? 'demo' : 'live'
  } catch {
    return 'live'
  }
}

export function saveMode(mode: Mode): void {
  try {
    window.localStorage.setItem(KEY, mode)
  } catch {
    // private window or blocked storage: the choice just lasts until reload
  }
}

export const ModeContext = createContext<{ mode: Mode; setMode: (m: Mode) => void }>({ mode: 'live', setMode: () => {} })

export const useMode = () => useContext(ModeContext)
