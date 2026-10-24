import { DOCK, FLOOR, NURSE_STATION, ROOMS } from '../data/layout'
import type { BellhopData } from '../data/types'
import { isOpen } from '../lib'

const ROBOT_LED: Record<string, string> = {
  idle: 'var(--ink-3)',
  en_route: 'var(--u2)',
  with_resident: 'var(--u1)',
  charging: 'var(--ink-3)',
}

export function FloorMap({ data, selectedRoom, onSelect }: { data: BellhopData; selectedRoom: number | null; onSelect: (room: number) => void }) {
  const open = data.calls.filter(isOpen)
  const byRoom = new Map(open.map((c) => [c.room, c]))
  return (
    <svg className="floor" viewBox={`0 0 ${FLOOR.w} ${FLOOR.h}`} role="img" aria-label="Floor plan showing rooms with open calls and robot positions">
      <rect x="130" y="176" width="800" height="108" className="corridor" rx="6" />
      <text x="535" y="236" textAnchor="middle" className="map-note">
        corridor
      </text>

      <g>
        <rect {...NURSE_STATION} rx="8" className="station" />
        <text x={NURSE_STATION.x + 50} y={NURSE_STATION.y + 36} textAnchor="middle" className="map-label">
          Nurse
        </text>
        <text x={NURSE_STATION.x + 50} y={NURSE_STATION.y + 54} textAnchor="middle" className="map-label">
          station
        </text>
        <rect {...DOCK} rx="8" className="station dock" />
        <text x={DOCK.x + 35} y={DOCK.y + 31} textAnchor="middle" className="map-label">
          Dock
        </text>
      </g>

      {ROOMS.map((r) => {
        const call = byRoom.get(r.number)
        const res = data.residents.find((x) => x.room === r.number)
        const cls = ['room', call ? `u${call.urgency}` : '', selectedRoom === r.number ? 'sel' : '', call && call.urgency === 4 ? 'pulse' : ''].join(' ')
        return (
          <g key={r.number} className={cls} onClick={() => call && onSelect(r.number)} style={{ cursor: call ? 'pointer' : 'default' }}>
            <rect x={r.x} y={r.y} width={r.w} height={r.h} rx="8" className="room-box" />
            <text x={r.x + 12} y={r.y + 24} className="room-num">
              {r.number}
            </text>
            <text x={r.x + 12} y={r.y + 44} className="room-name">
              {res?.name.split(' ')[1]}
            </text>
            {call && (
              <g transform={`translate(${r.x + r.w - 30} ${r.y + 22})`}>
                <circle r="13" className="room-badge" />
                <text textAnchor="middle" y="5" className="room-badge-text">
                  {call.urgency}
                </text>
              </g>
            )}
          </g>
        )
      })}

      {data.robots.map((b) => (
        <g key={b.id} className="robot" style={{ transform: `translate(${b.x}px, ${b.y}px)` }}>
          <circle r="19" className="robot-halo" />
          <circle r="12" className="robot-body" />
          <circle r="4.5" fill={ROBOT_LED[b.state]} className={b.state === 'with_resident' ? 'blink' : ''} />
          <text y="-24" textAnchor="middle" className="robot-name">
            {b.name.replace('Bellhop ', 'B')}
          </text>
        </g>
      ))}
    </svg>
  )
}
