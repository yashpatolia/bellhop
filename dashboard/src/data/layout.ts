import type { Room } from './types'

// A 24-room East Wing in a 1360 x 460 viewBox. Corridor runs through the middle.
export const FLOOR = { w: 1360, h: 460, corridorY: 230 }

const northNumbers = Array.from({ length: 12 }, (_, i) => 101 + i)
const southNumbers = Array.from({ length: 12 }, (_, i) => 113 + i)

const roomW = 84
const startX = 150
const gap = 8

export const ROOMS: Room[] = [
  ...northNumbers.map((n, i) => {
    const x = startX + i * (roomW + gap)
    return { number: n, x, y: 40, w: roomW, h: 130, door: { x: x + roomW / 2, y: 230 } }
  }),
  ...southNumbers.map((n, i) => {
    const x = startX + i * (roomW + gap)
    return { number: n, x, y: 290, w: roomW, h: 130, door: { x: x + roomW / 2, y: 230 } }
  }),
]

export const NURSE_STATION = { x: 24, y: 190, w: 100, h: 80 }
export const DOCK = { x: 1270, y: 205, w: 70, h: 50 }
export const DOCK_POINT = { x: 1305, y: 230 }

export const roomByNumber = (n: number) => ROOMS.find((r) => r.number === n)!
