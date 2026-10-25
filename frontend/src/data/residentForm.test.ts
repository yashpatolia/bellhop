import { describe, expect, it } from 'vitest'
import { parseYear, residentProblem } from './residentForm'
import type { Resident, ResidentInput } from './types'

const resident = (over: Partial<Resident> = {}): Resident => ({
  id: 'r1', name: 'Walter Brennan', room: '104', age: 91, flags: [], riskFlags: [], birthYear: 1935, hardOfHearing: false,
  mood: [], pain: [], learned: [], medical: { conditions: [], allergies: [], medicines: [], mobility: '', diet: '', lastReview: 0, reviewedBy: '' }, ...over,
})
const input = (over: Partial<ResidentInput> = {}): ResidentInput => ({ name: 'Ada Reyes', room: '105', birthYear: null, riskFlags: [], hardOfHearing: false, ...over })
const others = [resident(), resident({ id: 'r2', name: 'Evelyn Park', room: '106' })]

describe('what is wrong with a resident form', () => {
  it('a name and a free room are fine, with or without a year', () => {
    expect(residentProblem(input(), others)).toBeNull()
    expect(residentProblem(input({ birthYear: 1941 }), others)).toBeNull()
  })

  it('needs a name and a room', () => {
    expect(residentProblem(input({ name: '   ' }), others)).toMatch(/name/)
    expect(residentProblem(input({ room: '' }), others)).toMatch(/room/i)
  })

  it('refuses a room that already belongs to someone, and says who', () => {
    expect(residentProblem(input({ room: '104' }), others)).toBe('Room 104 already belongs to Walter Brennan. Move them first, or choose another room.')
  })

  it('lets a resident keep their own room when editing', () => {
    expect(residentProblem(input({ name: 'Walter B', room: '104' }), others, 'r1')).toBeNull()
  })

  it('a room is the same whatever spaces were typed around it', () => {
    expect(residentProblem(input({ room: ' 105 ' }), others)).toBeNull()
  })

  it.each([1879, 2016, 1941.5, Number.NaN])('year %s is refused', (year) => {
    expect(residentProblem(input({ birthYear: year }), others)).toMatch(/year of birth/i)
  })

  it('limits the lengths the backend limits', () => {
    expect(residentProblem(input({ name: 'x'.repeat(81) }), others)).toMatch(/too long/)
    expect(residentProblem(input({ room: 'x'.repeat(33) }), others)).toMatch(/too long/)
  })

  it('an empty year box means unknown, anything else is read as a number', () => {
    expect(parseYear('')).toBeNull()
    expect(parseYear('  ')).toBeNull()
    expect(parseYear('1941')).toBe(1941)
    expect(Number.isNaN(parseYear('abc'))).toBe(true)
  })
})
