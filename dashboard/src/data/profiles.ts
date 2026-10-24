import type { FactKind, FactSource, LearnedFact, MedicalHistory } from './types'

// Dummy learned facts and staff-entered medical history. Fictional, no real patient data.
// Replaced by the backend (memory facts, care records) when the live source covers residents.

const DAY = 86_400_000
const NOW = Date.now()

type Row = [FactKind, string, FactSource, number, string | null, number, number, number, ('active' | 'pending')?]

const rows = (id: string, list: Row[]): LearnedFact[] =>
  list.map(([kind, text, source, confidence, quote, learned, confirmed, seen, status], i) => ({
    id: `${id}-f${i + 1}`,
    kind,
    text,
    source,
    confidence,
    quote,
    learnedAt: NOW - learned * DAY,
    lastConfirmed: NOW - confirmed * DAY,
    timesSeen: seen,
    status: status ?? 'active',
  }))

const LEARNED: Record<string, LearnedFact[]> = {
  r101: rows('r101', [
    ['like', 'Takes tea with two sugars', 'resident', 0.95, 'I take two sugars, always have', 20, 1, 6],
    ['person', 'Grandson Mateo visits on Sundays', 'family', 0.92, null, 30, 3, 5],
    ['like', 'Enjoys old Spanish ballads', 'resident', 0.88, 'Put on those old Spanish songs', 14, 5, 3],
    ['style', 'Prefers to be called Margaret', 'staff', 0.9, null, 40, 10, 2],
    ['routine', 'Likes the radio on in the evening', 'inferred', 0.62, null, 4, 1, 2],
    ['dislike', 'Dislikes loud television', 'resident', 0.55, 'That television is far too loud', 2, 2, 1, 'pending'],
  ]),
  r102: rows('r102', [
    ['like', 'Plays chess, prefers white', 'resident', 0.93, 'I always play white', 25, 2, 5],
    ['like', 'Follows baseball, a Giants fan', 'resident', 0.9, 'Is the game on? I follow the Giants', 18, 4, 4],
    ['like', 'Drinks green tea', 'resident', 0.85, null, 12, 3, 3],
    ['style', 'Hard of hearing: speak slowly and face him', 'staff', 0.97, null, 60, 1, 8],
    ['routine', 'Reads the sports page after breakfast', 'resident', 0.6, 'I read the sports page first thing', 3, 3, 1, 'pending'],
  ]),
  r103: rows('r103', [
    ['person', 'Late husband Emeka, sang gospel with him', 'family', 0.9, null, 45, 6, 4],
    ['like', 'Loves gospel music', 'resident', 0.82, 'Play me some gospel', 20, 2, 7],
    ['like', 'Does crosswords', 'resident', 0.7, 'I do my crossword', 9, 4, 2],
    ['style', 'Calmer when spoken to gently; do not correct her about dates', 'staff', 0.95, null, 50, 2, 6],
    ['routine', 'Asks about Emeka most evenings', 'inferred', 0.58, null, 6, 1, 3, 'pending'],
  ]),
  r104: rows('r104', [
    ['like', 'Enjoys westerns and fishing stories', 'resident', 0.9, 'Tell me a fishing story', 22, 3, 5],
    ['like', 'Takes coffee black', 'resident', 0.94, 'Black, no sugar', 17, 2, 6],
    ['style', 'Short answers are fine; likes it when the robot lets him tell the story', 'inferred', 0.64, null, 8, 2, 3],
    ['health', 'Gets breathless when walking to the bathroom', 'resident', 0.5, 'It takes my breath going to the bathroom', 3, 3, 2, 'pending'],
  ]),
  r105: rows('r105', [
    ['like', 'Loves gardening, grows jasmine', 'resident', 0.93, 'My jasmine is blooming', 28, 5, 5],
    ['like', 'Plays bingo on Thursdays', 'resident', 0.86, 'Bingo day is Thursday', 21, 6, 3],
    ['like', 'Drinks jasmine tea', 'resident', 0.88, null, 16, 4, 4],
    ['person', 'Talks about her sister in Seoul', 'resident', 0.72, 'My sister in Seoul rings at Christmas', 10, 10, 2],
  ]),
  r106: rows('r106', [
    ['like', 'Plays backgammon, wins most games', 'resident', 0.92, 'I never lose at backgammon', 24, 3, 5],
    ['like', 'Enjoys Arabic poetry read aloud', 'resident', 0.84, 'Read me some Darwish', 15, 5, 3],
    ['like', 'Drinks mint tea without sugar', 'resident', 0.9, 'Mint tea, no sugar, I am diabetic', 13, 2, 4],
    ['dislike', 'Dislikes being offered sweets', 'staff', 0.9, null, 35, 8, 3],
  ]),
  r107: rows('r107', [
    ['like', 'Folds origami and gives pieces away', 'resident', 0.94, 'I made another crane for you', 26, 2, 6],
    ['like', 'Likes old films, especially musicals', 'resident', 0.83, 'Put on an old musical', 19, 4, 3],
    ['like', 'Drinks barley tea', 'resident', 0.86, null, 14, 3, 3],
    ['style', 'Hard of hearing: use short sentences, face her', 'staff', 0.97, null, 70, 1, 9],
  ]),
  r108: rows('r108', [
    ['person', 'Daughter Priya rings on Fridays', 'family', 0.93, null, 33, 4, 5],
    ['like', 'Follows cricket, watches test matches', 'resident', 0.9, 'Is the cricket on?', 21, 3, 5],
    ['like', 'Drinks chai with milk', 'resident', 0.88, 'Chai please, with milk', 17, 2, 4],
    ['dislike', 'Dislikes being rushed to the dining room', 'resident', 0.66, 'Do not hurry me along', 5, 5, 2],
  ]),
  r109: rows('r109', [
    ['like', 'Calms down listening to piano music', 'staff', 0.92, null, 40, 2, 7],
    ['like', 'Enjoys stories about Paris', 'resident', 0.78, 'I lived in Paris after the war', 18, 3, 5],
    ['like', 'Drinks warm milk before bed', 'resident', 0.8, null, 15, 1, 4],
    ['style', 'Speaks French when anxious; a few French words help', 'inferred', 0.7, null, 12, 2, 4],
    ['person', 'Says her husband is coming to collect her', 'inferred', 0.4, null, 3, 1, 3, 'pending'],
  ]),
  r110: rows('r110', [
    ['like', 'Plays chess and wants a rematch', 'resident', 0.91, 'Next time I will beat you', 20, 3, 4],
    ['like', 'Loves model trains', 'resident', 0.88, 'I collect trains', 16, 4, 3],
    ['like', 'Drinks black tea', 'resident', 0.86, null, 12, 2, 3],
  ]),
  r111: rows('r111', [
    ['like', 'Quilts, sorts patches into colours', 'resident', 0.92, 'I am sorting my patches', 27, 3, 5],
    ['like', 'Watches soap operas in the afternoon', 'resident', 0.86, 'My shows are on at two', 18, 4, 4],
    ['like', 'Keeps peppermints in her pocket', 'resident', 0.84, null, 11, 2, 3],
    ['style', 'Hard of hearing: face her and speak clearly', 'staff', 0.97, null, 55, 1, 8],
    ['health', 'Unsteady when getting out of the chair', 'resident', 0.55, 'My legs wobble when I stand up', 2, 2, 2, 'pending'],
  ]),
  r112: rows('r112', [
    ['like', 'Loves salsa music', 'resident', 0.93, 'Put on some salsa', 22, 2, 6],
    ['like', 'Follows boxing, talks about old fights', 'resident', 0.85, 'Did you see the fight last night?', 15, 4, 4],
    ['like', 'Drinks cafe con leche, no sugar', 'resident', 0.9, 'Cafe con leche, no sugar for me', 13, 3, 4],
    ['person', 'Brother Luis visits monthly', 'family', 0.88, null, 36, 9, 3],
  ]),
}

const hist = (
  conditions: MedicalHistory['conditions'],
  allergies: string[],
  medicines: string[],
  mobility: string,
  diet: string,
  reviewDays: number,
  reviewedBy: string,
): MedicalHistory => ({ conditions, allergies, medicines, mobility, diet, lastReview: NOW - reviewDays * DAY, reviewedBy })

const MEDICAL: Record<string, MedicalHistory> = {
  r101: hist([{ name: 'Hip replacement', since: '2022', note: 'Right hip, healed' }, { name: 'High blood pressure', since: '2015' }], ['Penicillin'], ['Amlodipine'], 'Walks with a frame, supervised on stairs', 'Regular, tea with two sugars', 12, 'Nurse Okoro'),
  r102: hist([{ name: 'Hearing loss', since: '2019', note: 'Hearing aids, left often off' }], [], ['Vitamin D'], 'Walks independently', 'Regular', 20, 'Nurse Patel'),
  r103: hist([{ name: 'Dementia', since: '2021', note: 'Moderate, worse in the evening' }, { name: 'Falls', since: '2023', note: 'Two falls last year' }], ['None known'], ['Donepezil'], 'Walks with a frame and an aide', 'Soft foods, needs reminding to drink', 6, 'Nurse Lindqvist'),
  r104: hist([{ name: 'COPD', since: '2018', note: 'On oxygen at night and as needed' }, { name: 'Falls risk', since: '2024' }], ['Latex'], ['Inhalers (two)'], 'Walks short distances, rests often', 'Low salt', 9, 'Nurse Okoro'),
  r105: hist([{ name: 'Mild arthritis', since: '2017', note: 'Hands and knees' }], [], ['Paracetamol as needed'], 'Walks independently', 'Regular', 31, 'Nurse Patel'),
  r106: hist([{ name: 'Type 2 diabetes', since: '2009', note: 'Checks sugar before meals' }], ['None known'], ['Metformin'], 'Walks with a stick', 'Diabetic diet, no added sugar', 7, 'Nurse Lindqvist'),
  r107: hist([{ name: 'Hearing loss', since: '2016' }, { name: 'Osteoporosis', since: '2020' }], ['Shellfish'], ['Calcium', 'Vitamin D'], 'Walks with a stick', 'Regular, no shellfish', 18, 'Nurse Okoro'),
  r108: hist([{ name: 'Knee replacement', since: '2023', note: 'Left knee, recovering' }, { name: 'Falls risk', since: '2023' }], [], ['Ibuprofen as needed'], 'Walks with a frame', 'Regular, vegetarian', 10, 'Nurse Patel'),
  r109: hist([{ name: 'Dementia', since: '2020', note: 'Advanced, mostly calm' }], ['Sulfa drugs'], ['Memantine'], 'Wheelchair, transfers with two staff', 'Soft diet, assisted feeding', 4, 'Nurse Lindqvist'),
  r110: hist([{ name: 'High cholesterol', since: '2018' }], [], ['Atorvastatin'], 'Walks independently', 'Regular', 40, 'Nurse Okoro'),
  r111: hist([{ name: 'Hearing loss', since: '2014' }, { name: 'Falls risk', since: '2022', note: 'Dizzy on standing' }], ['Aspirin'], ['Blood pressure tablet'], 'Walks with a frame, stand slowly', 'Regular', 8, 'Nurse Patel'),
  r112: hist([{ name: 'Type 2 diabetes', since: '2014' }], ['None known'], ['Metformin', 'Insulin at night'], 'Walks independently', 'Diabetic diet', 14, 'Nurse Lindqvist'),
}

export const profileFor = (id: string): { learned: LearnedFact[]; medical: MedicalHistory } => ({
  learned: LEARNED[id] ?? [],
  medical: MEDICAL[id] ?? hist([], [], [], 'Not recorded', 'Not recorded', 0, 'Not recorded'),
})
