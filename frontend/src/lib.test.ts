import { describe, expect, it } from 'vitest'
import { closestFreeRobot, nextRobotId, robotAvailability } from './lib'
import type { Robot } from './data/types'

const robot = (over: Partial<Robot> = {}): Robot => ({ id: 'b1', name: 'Bellhop 1', state: 'idle', battery: 80, room: 'dock', targetRoom: null, callId: null, ...over })
describe('which robots can be driven by hand', () => {
  it('a standing by robot is free', () => {
    expect(robotAvailability(robot())).toEqual({ free: true, words: 'Free' })
  })

  it.each([
    [{ state: 'charging' as const }, 'Charging'],
    [{ state: 'fault' as const }, 'Needs attention'],
    [{ state: 'en_route' as const, targetRoom: '111' }, 'Driving, room 111'],
    [{ state: 'en_route' as const }, 'Driving'],
    [{ state: 'with_resident' as const, targetRoom: '104' }, 'With a resident, room 104'],
  ])('%j is not free: %s', (over, words) => {
    expect(robotAvailability(robot(over))).toEqual({ free: false, words })
  })

  it('a low battery is a warning, not a refusal, because the backend accepts any idle robot', () => {
    expect(robotAvailability(robot({ battery: 19 }))).toEqual({ free: true, words: 'Free, low battery (19%)' })
    expect(robotAvailability(robot({ battery: 20 })).words).toBe('Free')
  })

  it('the closest free robot is one already in the room, else the one with the most charge', () => {
    const robots = [robot({ id: 'a', room: 'dock', battery: 50 }), robot({ id: 'b', room: '104', battery: 30 }), robot({ id: 'c', state: 'charging' }), robot({ id: 'd', room: 'dock', battery: 90 })]
    expect(closestFreeRobot(robots, '104')?.id).toBe('b')
    expect(closestFreeRobot(robots, '210')?.id).toBe('d')
    expect(closestFreeRobot([robot({ state: 'charging' })], '104')).toBeUndefined()
  })
})

describe('nextRobotId', () => {
  it('follows the fleet pattern', () => {
    expect(nextRobotId(['bellhop_1', 'bellhop_3'])).toBe('bellhop_4')
    expect(nextRobotId([])).toBe('robot_1')
    expect(nextRobotId(['scout'])).toBe('robot_1')
  })
})
