import type { Resident, ResidentInput } from './types'

export const MIN_BIRTH_YEAR = 1880
export const MAX_BIRTH_YEAR = 2015

/** The first thing wrong with what staff typed, in plain words, or null. `self` is the resident being edited. */
export function residentProblem(input: ResidentInput, residents: Resident[], self?: string): string | null {
  const name = input.name.trim()
  const room = input.room.trim()
  if (!name) return 'Type the resident\'s name.'
  if (name.length > 80) return 'That name is too long (80 letters at most).'
  if (!room) return 'Choose a room.'
  if (room.length > 32) return 'That room name is too long (32 letters at most).'
  const holder = residents.find((r) => r.id !== self && r.room === room)
  if (holder) return `Room ${room} already belongs to ${holder.name}. Move them first, or choose another room.`
  if (input.birthYear !== null && (!Number.isInteger(input.birthYear) || input.birthYear < MIN_BIRTH_YEAR || input.birthYear > MAX_BIRTH_YEAR)) {
    return `Year of birth must be between ${MIN_BIRTH_YEAR} and ${MAX_BIRTH_YEAR}, or left empty.`
  }
  return null
}

/** The year box as typed: empty means unknown. Anything that is not a whole year stays NaN so it is reported. */
export function parseYear(text: string): number | null {
  const t = text.trim()
  return t === '' ? null : Number(t)
}

export const cleaned = (input: ResidentInput): ResidentInput => ({ ...input, name: input.name.trim(), room: input.room.trim() })
