import type { components } from './schema'

// Wire types, generated from contracts/openapi.json (npm run gen:api). Only data/adapt.ts reads them.
type S = components['schemas']

export type ApiCall = S['Call']
export type ApiAlert = S['Alert']
export type ApiRobot = S['Robot']
export type ApiResident = S['Resident']
export type ApiNurse = S['Nurse']
export type ApiFact = S['MemoryFact']
export type ApiPending = S['PendingFact']
export type ApiMedical = S['MedicalRecord']
export type ApiCare = S['CareEntry']
export type ApiPrefs = S['Preferences']
export type ApiRefined = S['RefinedNote']
export type ApiMetrics = Record<string, unknown>
