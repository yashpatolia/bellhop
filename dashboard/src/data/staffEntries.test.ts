import { describe, expect, it } from 'vitest'
import { applyEntry, applyReview, refineLocally } from './staffEntries'
import type { Resident } from './types'

const NOW = Date.UTC(2026, 9, 24, 12, 0, 0)

const resident = (): Resident => ({
  id: 'r1',
  name: 'Test Resident',
  room: 101,
  age: 80,
  flags: [],
  likes: [],
  language: 'English',
  mood: [3, 3, 3, 3, 3, 3, 3],
  pain: [1, 1, 1, 1, 1, 1, 1],
  aiCostToday: 0,
  callsToday: 0,
  learned: [],
  medical: {
    conditions: [],
    allergies: ['None known'],
    medicines: [],
    mobility: 'Walks independently',
    diet: 'Regular',
    lastReview: NOW - 86_400_000,
    reviewedBy: 'Nurse Okoro',
  },
})

describe('refineLocally', () => {
  it('trims, capitalises and drops the trailing full stop', async () => {
    const out = await refineLocally({ category: 'like', text: '  enjoys the garden.  ' }, NOW)
    expect(out.text).toBe('Enjoys the garden')
    expect(out.notes.join(' ')).toMatch(/capital/i)
  })

  it('turns "he likes ..." into a third-person fact', async () => {
    const out = await refineLocally({ category: 'like', text: 'he likes his tea strong' }, NOW)
    expect(out.text).toBe('Likes his tea strong')
  })

  it('expands shorthand and says so', async () => {
    const out = await refineLocally({ category: 'condition', text: 'htn since 2015' }, NOW)
    expect(out.text).toBe('High blood pressure')
    expect(out.since).toBe('2015')
    expect(out.notes.join(' ')).toContain('high blood pressure')
  })

  it('reads "for N years" as a start year', async () => {
    const out = await refineLocally({ category: 'condition', text: 'COPD for 8 years' }, NOW)
    expect(out.since).toBe('2018')
    expect(out.text).toBe('COPD')
  })

  it('keeps only the medicine name and removes dose and timing', async () => {
    const out = await refineLocally({ category: 'medicine', text: 'metformin 500mg twice daily' }, NOW)
    expect(out.text).toBe('Metformin')
    expect(out.notes.join(' ')).toMatch(/dose/i)
  })

  it('rewrites shouting text in normal case', async () => {
    const out = await refineLocally({ category: 'dislike', text: 'LOUD TELEVISION AT NIGHT' }, NOW)
    expect(out.text).toBe('Loud television at night')
  })

  it('rejects empty text', async () => {
    await expect(refineLocally({ category: 'like', text: '   ' }, NOW)).rejects.toThrow(/nothing/i)
  })
})

describe('applyEntry', () => {
  it('adds a staff-sourced fact at full confidence and does not touch the original', () => {
    const before = resident()
    const after = applyEntry(before, { category: 'like', text: 'Enjoys the garden', notes: [] }, NOW)
    expect(before.learned).toHaveLength(0)
    expect(after.learned).toHaveLength(1)
    expect(after.learned[0]).toMatchObject({ kind: 'like', text: 'Enjoys the garden', source: 'staff', confidence: 1, status: 'active', quote: null })
  })

  it('adds a condition with its start year and refreshes the review stamp', () => {
    const after = applyEntry(resident(), { category: 'condition', text: 'COPD', since: '2018', notes: [] }, NOW)
    expect(after.medical.conditions).toEqual([{ name: 'COPD', since: '2018' }])
    expect(after.medical.lastReview).toBe(NOW)
    expect(after.medical.reviewedBy).toBe('Staff')
  })

  it('replaces "None known" when adding an allergy, and does not add it twice', () => {
    const once = applyEntry(resident(), { category: 'allergy', text: 'Penicillin', notes: [] }, NOW)
    const twice = applyEntry(once, { category: 'allergy', text: 'penicillin', notes: [] }, NOW)
    expect(twice.medical.allergies).toEqual(['Penicillin'])
  })

  it('lists a medicine once', () => {
    const once = applyEntry(resident(), { category: 'medicine', text: 'Metformin', notes: [] }, NOW)
    const twice = applyEntry(once, { category: 'medicine', text: 'Metformin', notes: [] }, NOW)
    expect(twice.medical.medicines).toEqual(['Metformin'])
  })

  it('replaces the mobility and diet notes', () => {
    const after = applyEntry(resident(), { category: 'mobility', text: 'Walks with a frame', notes: [] }, NOW)
    expect(after.medical.mobility).toBe('Walks with a frame')
    expect(applyEntry(after, { category: 'diet', text: 'Soft foods', notes: [] }, NOW).medical.diet).toBe('Soft foods')
  })
})

describe('applyReview', () => {
  const withPending = (): Resident => {
    const base = resident()
    const fact = (id: string, status: 'active' | 'pending') => ({
      id, kind: 'like' as const, text: id, source: 'resident' as const, confidence: 0.5,
      quote: null, learnedAt: 0, lastConfirmed: 0, timesSeen: 1, status,
    })
    return { ...base, learned: [fact('a', 'pending'), fact('b', 'pending'), fact('c', 'active')] }
  }

  it('approving makes only that fact active and stamps it confirmed', () => {
    const after = applyReview(withPending(), 'a', 'approve', NOW)
    expect(after.learned.map((f) => [f.id, f.status])).toEqual([['a', 'active'], ['b', 'pending'], ['c', 'active']])
    expect(after.learned[0].lastConfirmed).toBe(NOW)
  })

  it('rejecting removes only that pending fact', () => {
    const after = applyReview(withPending(), 'a', 'reject', NOW)
    expect(after.learned.map((f) => f.id)).toEqual(['b', 'c'])
  })

  it('never removes an already active fact', () => {
    expect(applyReview(withPending(), 'c', 'reject', NOW).learned).toHaveLength(3)
  })
})
