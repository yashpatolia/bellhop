import { describe, expect, it } from 'vitest'
import { closestFreeRobot, openCallIn, robotAvailability } from './lib'
import type { Call, Robot } from './data/types'

const robot = (over: Partial<Robot> = {}): Robot => ({ id: 'b1', name: 'Bellhop 1', state: 'idle', battery: 80, room: 'dock', targetRoom: null, callId: null, ...over })
const call = (over: Partial<Call> = {}): Call => ({
  id: 'c1', residentId: 'r1', room: '104', urgency: 1, category: 'chat', status: 'robot_en_route', handledBy: 'robot', robotId: 'b1',
  createdAt: 0, firstResponseSec: null, resolvedAt: null, resolvedByRobot: false, summary: '', transcript: [], ...over,
})

describe('which robots can be sent', () => {
  it('a standing by robot with charge is free', () => {
    expect(robotAvailability(robot())).toEqual({ free: true, words: 'Free' })
  })

  it.each([
    [{ state: 'charging' as const }, 'Charging'],
    [{ state: 'fault' as const }, 'Needs attention'],
    [{ state: 'en_route' as const, targetRoom: '111' }, 'Busy, room 111'],
    [{ state: 'with_resident' as const }, 'Busy'],
    [{ battery: 19 }, 'Battery too low (19%)'],
  ])('%j is not free: %s', (over, words) => {
    expect(robotAvailability(robot(over))).toEqual({ free: false, words })
  })

  it('exactly 20 percent is still enough, like the backend', () => {
    expect(robotAvailability(robot({ battery: 20 })).free).toBe(true)
  })

  it('the closest free robot is one already in the room, else the first free one', () => {
    const robots = [robot({ id: 'a', room: 'dock' }), robot({ id: 'b', room: '104' }), robot({ id: 'c', state: 'charging' })]
    expect(closestFreeRobot(robots, '104')?.id).toBe('b')
    expect(closestFreeRobot(robots, '210')?.id).toBe('a')
    expect(closestFreeRobot([robot({ state: 'charging' })], '104')).toBeUndefined()
  })
})

describe('a room that already has a call', () => {
  it('finds the open call, and ignores resolved ones', () => {
    expect(openCallIn([call({ status: 'resolved' }), call({ id: 'c2' })], '104')?.id).toBe('c2')
    expect(openCallIn([call({ status: 'resolved' })], '104')).toBeUndefined()
    expect(openCallIn([call()], '105')).toBeUndefined()
  })
})
