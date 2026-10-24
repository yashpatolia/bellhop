import type { BellhopData } from '../data/types'

export type View = 'live' | 'dispatch' | 'insights' | 'residents'

export interface LayoutProps {
  data: BellhopData
  view: View
  residentId?: string // set on #/residents/<id>
  callId?: string // set on #/residents/<id>/<callId>
  room?: string // set on #/dispatch/<room>
}
