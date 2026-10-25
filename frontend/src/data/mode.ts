import { createContext, useContext } from 'react'

// Which backend the dashboard reads. "live" is the real home; "demo" is a second backend that the
// simulator feeds with example residents and bell presses. The dashboard holds no mock data either way.
export type Mode = 'live' | 'demo'

export const DEMO_URL = (import.meta.env.VITE_BELLHOP_DEMO_URL as string | undefined) ?? 'http://127.0.0.1:8001'

const KEY = 'bellhop.mode'

export function readMode(): Mode {
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
