import type { EntryCategory, EntryDraft, FactKind, RefinedEntry, Resident } from './types'

// Staff add notes in their own words. A tidy step (a stand-in for Claude on the backend) rewrites
// the text cleanly and says what it changed, then staff review it before it is saved.
// refineLocally is the offline stand-in: simple rules, no network. When the backend has a refine
// route, only the source's `refineEntry` action changes.

export const ENTRY_LABEL: Record<EntryCategory, string> = {
  like: 'Like',
  dislike: 'Dislike',
  person: 'Person in their life',
  routine: 'Routine',
  style: 'How to talk with them',
  condition: 'Medical condition',
  allergy: 'Allergy',
  medicine: 'Medicine',
  mobility: 'Mobility',
  diet: 'Diet',
}

const FACT_CATEGORIES: EntryCategory[] = ['like', 'dislike', 'person', 'routine', 'style']
export const isFactCategory = (c: EntryCategory) => FACT_CATEGORIES.includes(c)

const SHORTHAND: [RegExp, string][] = [
  [/\bhtn\b/gi, 'high blood pressure'],
  [/\b(?:dm2|t2dm)\b/gi, 'type 2 diabetes'],
  [/\bdm\b/gi, 'diabetes'],
  [/\bcopd\b/gi, 'COPD'],
  [/\boa\b/gi, 'osteoarthritis'],
  [/\bafib\b/gi, 'atrial fibrillation'],
  [/\bnkda\b/gi, 'no known drug allergies'],
  [/\bbp\b/gi, 'blood pressure'],
  [/\bmeds\b/gi, 'medicines'],
  [/\bc\/o\b/gi, 'complains of'],
  [/\bpt\b/gi, 'the resident'],
]

const PRONOUN_VERB = /^(?:she|he|they|the resident|resident)\s+(likes|loves|enjoys|prefers|dislikes|hates)\b\s*/i
const DOSE = /\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|units?|iu)\b/gi
const TIMING = /\b(?:once a day|twice a day|twice daily|three times a day|daily|nightly|at night|in the morning|bd|od|tds|qds|prn|as needed)\b/gi

const sentenceCase = (t: string) => (t ? t[0].toUpperCase() + t.slice(1) : t)

export async function refineLocally(draft: EntryDraft, now: number = Date.now()): Promise<RefinedEntry> {
  const notes: string[] = []
  let text = draft.text.replace(/\s+/g, ' ').trim().replace(/^["']+|["']+$/g, '')
  if (!text) throw new Error('Nothing to add. Type a note first.')

  const letters = text.replace(/[^A-Za-z]/g, '')
  if (letters.length > 3 && letters.replace(/[^A-Z]/g, '').length / letters.length > 0.6) {
    text = text.toLowerCase()
    notes.push('Rewrote the capital letters in normal case')
  }

  for (const [pattern, full] of SHORTHAND) {
    text = text.replace(pattern, (m) => {
      if (m.toLowerCase() === full.toLowerCase()) return full
      notes.push(`Wrote "${m}" as "${full}"`)
      return full
    })
  }

  let since: string | undefined
  if (draft.category === 'condition') {
    const year = text.match(/\b(?:since|from)\s+((?:19|20)\d{2})\b/i)
    const years = text.match(/\bfor\s+(\d{1,2})\s+years?\b/i)
    if (year) {
      since = year[1]
      text = text.replace(year[0], '')
    } else if (years) {
      since = String(new Date(now).getUTCFullYear() - Number(years[1]))
      text = text.replace(years[0], '')
    }
    if (since) notes.push(`Recorded the start as ${since}`)
  }

  if (draft.category === 'medicine') {
    const stripped = text.replace(DOSE, '').replace(TIMING, '')
    if (stripped !== text) {
      text = stripped
      notes.push('Dose and timing removed: only the medicine name is kept')
    }
  }

  if (isFactCategory(draft.category)) {
    const lead = text.match(PRONOUN_VERB)
    if (lead) {
      text = sentenceCase(lead[1].toLowerCase()) + ' ' + text.slice(lead[0].length)
      notes.push('Wrote it as a short third-person note')
    }
  }

  text = text.replace(/\s+/g, ' ').replace(/[\s,;.]+$/, '').trim()
  const cased = sentenceCase(text)
  if (cased !== text) notes.push('Fixed capitalisation')
  text = cased
  if (!text) throw new Error('Nothing to add. Type a note first.')
  return { category: draft.category, text, since, notes }
}

const KIND: Partial<Record<EntryCategory, FactKind>> = { like: 'like', dislike: 'dislike', person: 'person', routine: 'routine', style: 'style' }

const same = (a: string, b: string) => a.trim().toLowerCase() === b.trim().toLowerCase()
const EMPTY = /^none (?:known|recorded)$/i

/** Returns a new resident with the entry added. Staff entries are trusted, so facts start active at full confidence. */
export function applyEntry(resident: Resident, entry: RefinedEntry, now: number): Resident {
  const kind = KIND[entry.category]
  if (kind) {
    const n = resident.learned.filter((f) => f.source === 'staff').length + 1
    return {
      ...resident,
      learned: [
        ...resident.learned,
        {
          id: `${resident.id}-s${n}-${now}`,
          kind,
          text: entry.text,
          source: 'staff',
          confidence: 1,
          quote: null,
          learnedAt: now,
          lastConfirmed: now,
          timesSeen: 1,
          status: 'active',
        },
      ],
    }
  }
  const m = resident.medical
  const next = { ...m, lastReview: now, reviewedBy: 'Staff' }
  if (entry.category === 'condition') next.conditions = [...m.conditions, { name: entry.text, since: entry.since ?? 'recently' }]
  if (entry.category === 'allergy') {
    const kept = m.allergies.filter((a) => !EMPTY.test(a))
    next.allergies = kept.some((a) => same(a, entry.text)) ? kept : [...kept, entry.text]
  }
  if (entry.category === 'medicine') next.medicines = m.medicines.some((x) => same(x, entry.text)) ? m.medicines : [...m.medicines, entry.text]
  if (entry.category === 'mobility') next.mobility = entry.text
  if (entry.category === 'diet') next.diet = entry.text
  return { ...resident, medical: next }
}
