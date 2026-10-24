import { describe, expect, it } from 'vitest'
import { findTendencies } from './tendencies'
import type { Call, Category, Urgency } from './data/types'

const DAY = 86_400_000
const NOW = new Date(2026, 9, 24, 12, 0, 0).getTime() // local noon

let n = 0
function call(daysAgo: number, hour: number, category: Category, urgency: Urgency = 1, byRobot = true): Call {
  const at = new Date(NOW - daysAgo * DAY)
  at.setHours(hour, 15, 0, 0)
  return {
    id: `c${n++}`,
    residentId: 'r1',
    room: 101,
    urgency,
    category,
    status: 'resolved',
    handledBy: urgency >= 3 ? 'nurse' : 'robot',
    robotId: null,
    createdAt: at.getTime(),
    firstResponseSec: 60,
    resolvedAt: at.getTime() + 300_000,
    resolvedByRobot: byRobot,
    summary: '',
    sbar: { s: '', b: '', a: '', r: '' },
    transcript: [],
    confidence: 0.9,
    costUsd: 0.1,
    feedback: null,
  }
}

const texts = (calls: Call[]) => findTendencies(calls, NOW).map((t) => t.text)

describe('findTendencies', () => {
  it('says nothing when there is too little history', () => {
    expect(findTendencies([call(1, 19, 'chat'), call(2, 19, 'chat')], NOW)).toEqual([])
  })

  it('spots a repeated reason', () => {
    const calls = [call(1, 9, 'pain'), call(3, 14, 'pain'), call(5, 20, 'pain'), call(6, 11, 'chat')]
    expect(texts(calls)).toContain('Often calls about pain')
  })

  it('spots a repeated time of day across different days', () => {
    const calls = [call(1, 19, 'confusion'), call(2, 20, 'chat'), call(4, 19, 'confusion'), call(6, 21, 'confusion'), call(8, 9, 'pain')]
    const found = findTendencies(calls, NOW).find((t) => t.id === 'time')
    expect(found?.text).toBe('Often rings between 7 PM and 10 PM')
    expect(found?.evidence).toContain('4')
  })

  it('does not call it a time pattern when calls are spread through the day', () => {
    const calls = [call(1, 2, 'chat'), call(2, 8, 'chat'), call(3, 13, 'chat'), call(4, 19, 'chat')]
    expect(findTendencies(calls, NOW).find((t) => t.id === 'time')).toBeUndefined()
  })

  it('treats a window that wraps past midnight as one window', () => {
    const calls = [call(1, 23, 'pain'), call(2, 0, 'pain'), call(3, 1, 'pain'), call(4, 23, 'pain')]
    expect(findTendencies(calls, NOW).find((t) => t.id === 'time')?.text).toBe('Often rings between 11 PM and 2 AM')
  })

  it('spots repeated nurse escalations for the same reason', () => {
    const calls = [call(1, 3, 'breathing', 3, false), call(4, 2, 'breathing', 4, false), call(7, 22, 'chat'), call(9, 10, 'chat')]
    expect(texts(calls)).toContain('Repeatedly needs a nurse for breathing')
  })

  it('notices calling more than last week', () => {
    const calls = [call(1, 9, 'chat'), call(2, 10, 'chat'), call(3, 11, 'chat'), call(4, 15, 'chat'), call(10, 9, 'chat')]
    expect(texts(calls)).toContain('Calling more than last week')
  })

  it('notes when the robot usually settles things', () => {
    const calls = [call(1, 9, 'chat'), call(2, 15, 'chat'), call(3, 21, 'chat'), call(5, 11, 'chat'), call(6, 17, 'chat')]
    expect(texts(calls)).toContain('Usually settles with the robot')
  })

  it('ignores calls older than 14 days', () => {
    const calls = [call(20, 9, 'pain'), call(22, 9, 'pain'), call(25, 9, 'pain'), call(30, 9, 'pain')]
    expect(findTendencies(calls, NOW)).toEqual([])
  })
})
