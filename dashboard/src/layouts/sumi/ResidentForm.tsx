import { useState } from 'react'
import type { BellhopData, Resident } from '../../data/types'
import { RISK_CHOICES } from '../../data/adapt'
import { cleaned, parseYear, residentProblem } from '../../data/residentForm'

// Add a resident and give them a room, or change a resident's room and details. The backend has
// the last word: it refuses a room that is already taken, and its reason is shown here.

export function ResidentForm({ data, resident }: { data: BellhopData; resident?: Resident }) {
  const [name, setName] = useState(resident?.name ?? '')
  const [room, setRoom] = useState(resident?.room ?? '')
  const [year, setYear] = useState(resident?.birthYear ? String(resident.birthYear) : '')
  const [flags, setFlags] = useState<string[]>(resident?.riskFlags ?? [])
  const [hearing, setHearing] = useState(resident?.hardOfHearing ?? false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const input = { name, room, birthYear: parseYear(year), riskFlags: flags, hardOfHearing: hearing }
  const problem = residentProblem(input, data.residents, resident?.id)
  const taken = [...new Set(data.residents.filter((r) => r.id !== resident?.id).map((r) => r.room))].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }))
  const back = resident ? `#/residents/${resident.id}` : '#/residents'
  const known = new Set(RISK_CHOICES.map((c) => c.code))

  const toggle = (code: string) => setFlags((f) => (f.includes(code) ? f.filter((x) => x !== code) : [...f, code]))

  const submit = async () => {
    if (problem) return
    setBusy(true)
    setError('')
    try {
      if (resident) {
        await data.actions.updateResident(resident.id, cleaned(input))
        window.location.hash = back
      } else {
        const id = await data.actions.addResident(cleaned(input))
        window.location.hash = `#/residents/${id}`
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That did not work.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section>
      <h2>{resident ? 'Change room or details' : 'Add a resident'}</h2>
      <p className="sm-empty">{resident ? 'A resident can only have one room, and a room only one resident.' : 'Give them a room that is free. Bellhop sends the robot to that room when they ring.'}</p>
      <form
        className="sm-form"
        onSubmit={(e) => {
          e.preventDefault()
          void submit()
        }}
      >
        <label>
          Full name
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={80} autoComplete="off" />
        </label>
        <label>
          Room
          <input value={room} onChange={(e) => setRoom(e.target.value)} maxLength={32} autoComplete="off" aria-describedby="rooms-in-use" />
        </label>
        <p id="rooms-in-use" className="sm-empty">
          {taken.length ? `Rooms already in use: ${taken.join(', ')}.` : 'No room is in use yet.'}
        </p>
        <label>
          Year of birth (optional)
          <input value={year} onChange={(e) => setYear(e.target.value)} inputMode="numeric" maxLength={4} placeholder="For example 1941" autoComplete="off" />
        </label>
        <fieldset className="sm-checks">
          <legend>Things staff should know</legend>
          {RISK_CHOICES.map((c) => (
            <label key={c.code}>
              <input type="checkbox" checked={flags.includes(c.code)} onChange={() => toggle(c.code)} />
              {c.label}
            </label>
          ))}
          <label>
            <input type="checkbox" checked={hearing} onChange={(e) => setHearing(e.target.checked)} />
            Hard of hearing
          </label>
          {flags.filter((f) => !known.has(f)).length > 0 && <p className="sm-empty">Also kept: {flags.filter((f) => !known.has(f)).join(', ')}.</p>}
        </fieldset>
        {(error || (problem && (name || room || year))) && (
          <p className="sm-error" role="alert">
            {error || problem}
          </p>
        )}
        <div className="sm-actions">
          <button className="sb-btn primary" type="submit" disabled={busy || Boolean(problem)}>
            {busy ? 'Saving...' : resident ? 'Save changes' : 'Add resident'}
          </button>
          <a className="sb-btn" href={back}>
            Cancel
          </a>
        </div>
      </form>
    </section>
  )
}
