import type { EntryCategory, FactKind } from './types'

// What staff can add to a resident's profile. The tidy step itself runs on the backend
// (POST /residents/{id}/notes/refine); this file only names the categories.

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

/** The first five categories become facts Bellhop uses in conversation; the rest are medical history. */
export const FACT_KIND_OF: Partial<Record<EntryCategory, FactKind>> = { like: 'like', dislike: 'dislike', person: 'person', routine: 'routine', style: 'style' }

export const isFactCategory = (c: EntryCategory) => c in FACT_KIND_OF
