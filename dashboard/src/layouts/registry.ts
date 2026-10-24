import type { ComponentType } from 'react'
import type { BellhopData } from '../data/types'
import type { View } from '../components/Header'

export interface LayoutProps {
  data: BellhopData
  view: View
  theme: string
  preview: boolean
  residentId?: string // set on #/residents/<id>
  callId?: string // set on #/residents/<id>/<callId>
}

// Each theme can ship its own layout: src/layouts/<theme id>/Layout.tsx with a default export.
// Anything without one falls back to the shared default Screen.
const mods = import.meta.glob<{ default: ComponentType<LayoutProps> }>('./*/Layout.tsx', { eager: true })

export const LAYOUTS: Record<string, ComponentType<LayoutProps>> = {}
for (const [path, mod] of Object.entries(mods)) {
  const id = path.split('/')[1]
  LAYOUTS[id] = mod.default
}
