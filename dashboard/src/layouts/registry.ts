import type { BellhopData } from '../data/types'

export type View = 'live' | 'insights' | 'residents'

export interface LayoutProps {
  data: BellhopData
  view: View
  residentId?: string // set on #/residents/<id>
  callId?: string // set on #/residents/<id>/<callId>
}
