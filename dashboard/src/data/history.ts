import type { Call, Category, Resident } from './types'

// Dummy call history for the 14 days before today, with a pattern per resident so the
// tendencies on the Residents page have something real to find. Fictional data.
// Replaced by the backend's call list when the live source covers residents.

type Pattern = [category: Category, count: number, hourFrom: number, hourTo: number]

// hourTo above 24 wraps past midnight, so 22 to 26 means 10 PM to 2 AM.
const PATTERNS: Record<string, Pattern[]> = {
  r101: [['comfort item', 6, 18, 21], ['chat', 3, 14, 16]],
  r102: [['chat', 4, 14, 16], ['comfort item', 2, 9, 10]],
  r103: [['confusion', 8, 17, 20], ['toileting', 3, 2, 4], ['fall', 1, 21, 22]],
  r104: [['breathing', 4, 22, 26], ['pain', 3, 1, 3], ['chat', 2, 10, 11]],
  r105: [['chat', 3, 9, 11]],
  r106: [['medication', 4, 7, 8], ['pain', 2, 15, 16]],
  r107: [['comfort item', 3, 14, 16], ['chat', 1, 10, 11]],
  r108: [['toileting', 5, 2, 4], ['pain', 2, 10, 12]],
  r109: [['confusion', 6, 17, 20], ['chat', 3, 15, 17]],
  r110: [['chat', 2, 19, 21]],
  r111: [['toileting', 4, 5, 7], ['pain', 2, 6, 8]],
  r112: [['chat', 2, 13, 15], ['comfort item', 1, 9, 10]],
}

const DAY = 86_400_000

/** `make` builds one resolved call for a category at a time; the caller owns the scenario text. */
export function buildPastCalls(now: number, residents: Resident[], make: (category: Category, resident: Resident, at: number, k: number) => Call): Call[] {
  const out: Call[] = []
  residents.forEach((resident, idx) => {
    ;(PATTERNS[resident.id] ?? []).forEach(([category, count, from, to], p) => {
      const span = Math.max(1, to - from)
      for (let k = 0; k < count; k++) {
        const day = 1 + ((k * 2 + idx + p * 5) % 14)
        const at = new Date(now - day * DAY)
        at.setHours((from + ((k * 7) % span)) % 24, (k * 17 + idx * 11) % 60, 0, 0)
        out.push(make(category, resident, at.getTime(), k))
      }
    })
  })
  return out.sort((a, b) => a.createdAt - b.createdAt)
}
