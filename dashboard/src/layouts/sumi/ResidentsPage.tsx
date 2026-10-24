import { useState } from 'react'
import { Sparkline } from '../../components/Charts'
import type { BellhopData, Call, EntryCategory, FactKind, FactSource, LearnedFact, RefinedEntry, Resident, ReviewDecision } from '../../data/types'
import { ENTRY_LABEL } from '../../data/staffEntries'
import { CATEGORY_LABEL, clock, initials, isOpen, statusText } from '../../lib'
import { findTendencies } from '../../tendencies'
import { Chip, Detail } from '../shared'

const KIND_ORDER: FactKind[] = ['like', 'dislike', 'person', 'routine', 'style', 'health', 'event']
const KIND_LABEL: Record<FactKind, string> = {
  like: 'Likes',
  dislike: 'Dislikes',
  person: 'People',
  routine: 'Routines',
  style: 'How to talk with them',
  health: 'Health things they mentioned',
  event: 'Life events',
}
const SOURCE_LABEL: Record<FactSource, string> = {
  resident: 'Heard from the resident',
  staff: 'Confirmed by staff',
  family: 'From family',
  inferred: 'Inferred by Bellhop',
}
const LEARNED_CATEGORIES: EntryCategory[] = ['like', 'dislike', 'person', 'routine', 'style']
const MEDICAL_CATEGORIES: EntryCategory[] = ['condition', 'allergy', 'medicine', 'mobility', 'diet']

const confidenceWord = (c: number) => (c >= 0.85 ? 'High' : c >= 0.65 ? 'Medium' : 'Low')

function ago(ms: number, now: number): string {
  const days = Math.floor((now - ms) / 86_400_000)
  return days <= 0 ? 'today' : days === 1 ? 'yesterday' : `${days} days ago`
}

function dayLabel(ms: number, now: number): string {
  const d = new Date(ms)
  const same = (a: Date, b: Date) => a.toDateString() === b.toDateString()
  if (same(d, new Date(now))) return 'Today'
  if (same(d, new Date(now - 86_400_000))) return 'Yesterday'
  return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' })
}

function watchNotes(r: Resident): string[] {
  const notes: string[] = []
  if (r.mood.length >= 2 && r.mood[r.mood.length - 1] < r.mood[0] - 1) notes.push('Quieter than usual')
  if (r.pain.length >= 2 && r.pain[r.pain.length - 1] > r.pain[0] + 1) notes.push('Pain rising')
  return notes
}

/** What a search can match: name, room, risk flags, learned facts and recorded conditions. */
function searchText(r: Resident): string {
  return [r.name, `room ${r.room}`, ...r.flags, ...r.learned.map((f) => f.text), ...r.medical.conditions.map((c) => c.name)].join(' ').toLowerCase()
}

function ResidentList({ data, selectedId }: { data: BellhopData; selectedId: string }) {
  const [query, setQuery] = useState('')
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
  const shown = data.residents.filter((r) => terms.every((t) => searchText(r).includes(t)))
  return (
    <nav className="sm-reslist" aria-label="Residents">
      <h2>Residents</h2>
      <input
        className="sm-search"
        type="search"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="Search name, room, condition"
        aria-label="Search residents"
      />
      <p className="sm-count" aria-live="polite">
        {query ? `${shown.length} of ${data.residents.length} residents` : `${data.residents.length} residents`}
      </p>
      {shown.length === 0 && <p className="sm-empty">No resident matches "{query}".</p>}
      <ul>
        {shown.map((r) => {
          const open = data.calls.find((c) => c.residentId === r.id && isOpen(c))
          const review = r.learned.filter((f) => f.status === 'pending').length
          const watch = watchNotes(r)
          return (
            <li key={r.id}>
              <a href={`#/residents/${r.id}`} aria-current={r.id === selectedId ? 'page' : undefined}>
                <span className="sm-resname">
                  {r.name} <small>Room {r.room}</small>
                </span>
                <span className="sm-resmeta">
                  {open ? <Chip u={open.urgency} /> : <span>No open call</span>}
                  {watch.map((w) => (
                    <span key={w} className="sm-watch">
                      {w}
                    </span>
                  ))}
                  {review > 0 && <span className="sm-review">{review} to review</span>}
                </span>
              </a>
            </li>
          )
        })}
      </ul>
    </nav>
  )
}

function FactRow({ fact, now, onReview }: { fact: LearnedFact; now: number; onReview?: (decision: ReviewDecision) => void }) {
  return (
    <li className={fact.status === 'pending' ? 'pending' : ''}>
      <span className="sm-fact">{fact.text}</span>
      <span className="sm-factmeta">
        {SOURCE_LABEL[fact.source]}, {confidenceWord(fact.confidence)} confidence ({Math.round(fact.confidence * 100)}%), seen {fact.timesSeen}{' '}
        {fact.timesSeen === 1 ? 'time' : 'times'}, last confirmed {ago(fact.lastConfirmed, now)}
      </span>
      {fact.quote && <q className="sm-quote">{fact.quote}</q>}
      {onReview && (
        <span className="sm-actions">
          <button className="sb-btn primary" onClick={() => onReview('approve')}>
            Approve
          </button>
          <button className="sb-btn" onClick={() => onReview('reject')}>
            Reject
          </button>
        </span>
      )}
    </li>
  )
}

function Learned({ data, resident, now }: { data: BellhopData; resident: Resident; now: number }) {
  const active = resident.learned.filter((f) => f.status === 'active')
  const pending = resident.learned.filter((f) => f.status === 'pending')
  return (
    <section>
      <h2>What Bellhop has learned</h2>
      {active.length === 0 && <p className="sm-empty">Nothing learned yet.</p>}
      {KIND_ORDER.map((kind) => {
        const facts = active.filter((f) => f.kind === kind)
        if (!facts.length) return null
        return (
          <div key={kind} className="sm-kind">
            <h3>{KIND_LABEL[kind]}</h3>
            <ul>
              {facts.map((f) => (
                <FactRow key={f.id} fact={f} now={now} />
              ))}
            </ul>
          </div>
        )
      })}
      {pending.length > 0 && (
        <div className="sm-kind sm-pending">
          <h3>Waiting for a nurse to review ({pending.length})</h3>
          <p className="sm-empty">Bellhop is not using these yet. Approve a fact to start using it, or reject it to forget it.</p>
          <ul>
            {pending.map((f) => (
              <FactRow key={f.id} fact={f} now={now} onReview={(d) => data.actions.reviewFact(resident.id, f.id, d)} />
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}

function AddNote({ data, resident }: { data: BellhopData; resident: Resident }) {
  const [open, setOpen] = useState(false)
  const [category, setCategory] = useState<EntryCategory>('like')
  const [text, setText] = useState('')
  const [refined, setRefined] = useState<RefinedEntry | null>(null)
  const [edited, setEdited] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [added, setAdded] = useState('')

  const reset = () => {
    setText('')
    setRefined(null)
    setEdited('')
    setError('')
  }
  const tidy = async () => {
    setBusy(true)
    setError('')
    setAdded('')
    try {
      const out = await data.actions.refineEntry(resident.id, { category, text })
      setRefined(out)
      setEdited(out.text)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not tidy that note.')
    } finally {
      setBusy(false)
    }
  }
  const save = () => {
    if (!refined || !edited.trim()) return
    data.actions.addEntry(resident.id, { ...refined, text: edited.trim() })
    setAdded(`Added to ${resident.name.split(' ')[0]}'s profile: ${ENTRY_LABEL[refined.category].toLowerCase()}, "${edited.trim()}".`)
    reset()
    setOpen(false)
  }

  if (!open) {
    return (
      <section>
        <h2>Add a note</h2>
        {added && (
          <p className="sm-added" role="status">
            {added}
          </p>
        )}
        <button className="sm-btn" onClick={() => setOpen(true)}>
          Add a like, dislike, routine or medical note
        </button>
      </section>
    )
  }
  return (
    <section>
      <h2>Add a note</h2>
      <p className="sm-empty">Write it in your own words. Bellhop tidies it up and you check it before it is saved.</p>
      {!refined ? (
        <form
          className="sm-form"
          onSubmit={(e) => {
            e.preventDefault()
            void tidy()
          }}
        >
          <label>
            What kind of note is it?
            <select value={category} onChange={(e) => setCategory(e.target.value as EntryCategory)}>
              <optgroup label="About them">
                {LEARNED_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {ENTRY_LABEL[c]}
                  </option>
                ))}
              </optgroup>
              <optgroup label="Medical history">
                {MEDICAL_CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {ENTRY_LABEL[c]}
                  </option>
                ))}
              </optgroup>
            </select>
          </label>
          <label>
            Your note
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} placeholder="For example: he likes his tea strong, htn since 2015, pt c/o knee pain" />
          </label>
          {error && (
            <p className="sm-error" role="alert">
              {error}
            </p>
          )}
          <div className="sm-actions">
            <button className="sb-btn primary" type="submit" disabled={busy || !text.trim()}>
              {busy ? 'Working...' : 'Submit'}
            </button>
            <button className="sb-btn" type="button" onClick={() => { setOpen(false); reset() }}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="sm-form">
          <p className="sm-original">
            <strong>{ENTRY_LABEL[refined.category]}.</strong> You wrote: {text}
          </p>
          <label>
            How it will be saved (you can change it)
            <input value={edited} onChange={(e) => setEdited(e.target.value)} />
          </label>
          {refined.since && <p className="sm-empty">Recorded as since {refined.since}.</p>}
          {refined.notes.length > 0 && (
            <ul className="sm-changes" aria-label="What was changed">
              {refined.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
          <div className="sm-actions">
            <button className="sb-btn primary" onClick={save} disabled={!edited.trim()}>
              Add to profile
            </button>
            <button className="sb-btn" onClick={() => setRefined(null)}>
              Edit my note
            </button>
            <button className="sb-btn" onClick={() => { setOpen(false); reset() }}>
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  )
}

function Habits({ resident, calls, now }: { resident: Resident; calls: Call[]; now: number }) {
  const tendencies = findTendencies(calls, now)
  const watch = watchNotes(resident)
  return (
    <section>
      <h2>Habits and tendencies</h2>
      {tendencies.length === 0 ? (
        <p className="sm-empty">No repeated pattern yet. Patterns show up after a few calls across different days.</p>
      ) : (
        <ul className="sm-tendencies">
          {tendencies.map((t) => (
            <li key={t.id}>
              <strong>{t.text}</strong>
              <span>{t.evidence}</span>
            </li>
          ))}
        </ul>
      )}
      <dl className="sm-facts">
        <dt>Mood, 7 days</dt>
        <dd className="sm-trend">
          <Sparkline values={resident.mood} min={1} max={5} color="var(--ink-2)" w={120} h={28} />
          {resident.mood.length >= 2 && (watch.includes('Quieter than usual') ? 'Quieter than usual' : 'Steady')}
        </dd>
        <dt>Pain, 7 days</dt>
        <dd className="sm-trend">
          <Sparkline values={resident.pain} min={1} max={5} color="var(--u3)" w={120} h={28} />
          {resident.pain.length >= 2 && (watch.includes('Pain rising') ? 'Rising' : 'Steady')}
        </dd>
      </dl>
    </section>
  )
}

function Medical({ resident, now }: { resident: Resident; now: number }) {
  const m = resident.medical
  return (
    <section>
      <h2>Medical history</h2>
      <p className="sm-empty">Entered by staff. Bellhop does not learn or change these. Use "Add a note" to add to them.</p>
      <dl className="sm-facts">
        <dt>Conditions</dt>
        <dd>
          {m.conditions.length === 0 && 'None recorded'}
          <ul className="sm-plainlist">
            {m.conditions.map((c) => (
              <li key={c.name}>
                <strong>{c.name}</strong>, since {c.since}
                {c.note ? `. ${c.note}` : ''}
              </li>
            ))}
          </ul>
        </dd>
        <dt>Allergies</dt>
        <dd>{m.allergies.length ? m.allergies.join(', ') : 'None recorded'}</dd>
        <dt>Medicines</dt>
        <dd>{m.medicines.length ? m.medicines.join(', ') : 'None recorded'}</dd>
        <dt>Mobility</dt>
        <dd>{m.mobility}</dd>
        <dt>Diet</dt>
        <dd>{m.diet}</dd>
        <dt>Last reviewed</dt>
        <dd>
          {ago(m.lastReview, now)} by {m.reviewedBy}
        </dd>
      </dl>
    </section>
  )
}

const FIRST_SHOWN = 8

function CallHistory({ resident, calls, now }: { resident: Resident; calls: Call[]; now: number }) {
  const [all, setAll] = useState(false)
  const shown = all ? calls : calls.slice(0, FIRST_SHOWN)
  const days = shown.map((c) => dayLabel(c.createdAt, now))
  return (
    <section>
      <h2>Call history ({calls.length})</h2>
      {calls.length === 0 && <p className="sm-empty">No calls yet.</p>}
      <ul className="sm-recentcalls">
        {shown.map((c, i) => {
          const day = days[i]
          const heading = i === 0 || day !== days[i - 1]
          return (
            <li key={c.id} className={heading ? 'newday' : ''}>
              {heading && <span className="sm-day">{day}</span>}
              <a href={`#/residents/${resident.id}/${c.id}`} aria-label={`Read the conversation from ${day} at ${clock(c.createdAt)}`}>
                <time>{clock(c.createdAt)}</time>
                <Chip u={c.urgency} />
                <span>
                  {CATEGORY_LABEL[c.category]}. {statusText(c)}
                </span>
                <span className="sm-open">Read</span>
              </a>
            </li>
          )
        })}
      </ul>
      {calls.length > FIRST_SHOWN && (
        <button className="sb-btn" onClick={() => setAll(!all)}>
          {all ? 'Show fewer' : `Show all ${calls.length} calls`}
        </button>
      )}
    </section>
  )
}

export function ResidentsPage({ data, residentId, callId }: { data: BellhopData; residentId?: string; callId?: string }) {
  const first = data.residents.find((r) => data.calls.some((c) => c.residentId === r.id && isOpen(c))) ?? data.residents[0]
  const resident = data.residents.find((r) => r.id === residentId) ?? first
  if (!resident) return <p className="sm-empty">No residents yet.</p>
  const calls = [...data.pastCalls, ...data.calls].filter((c) => c.residentId === resident.id).sort((a, b) => b.createdAt - a.createdAt)
  const viewing = callId ? calls.find((c) => c.id === callId) : undefined
  return (
    <div className="sm-people">
      <ResidentList data={data} selectedId={resident.id} />
      <article className="sm-profile" aria-label={`${resident.name} profile`}>
        <header>
          <span className="sm-avatar" aria-hidden="true">
            {initials(resident.name)}
          </span>
          <div>
            <h1>{resident.name}</h1>
            <p>
              Room {resident.room}{resident.age ? `, age ${resident.age}` : ''}
            </p>
            {resident.flags.length > 0 && (
              <p className="sm-flags">
                {resident.flags.map((f) => (
                  <span key={f}>{f}</span>
                ))}
              </p>
            )}
          </div>
        </header>
        {viewing ? (
          <section className="sm-callview">
            <a className="sm-back" href={`#/residents/${resident.id}`}>
              Back to {resident.name.split(' ')[0]}'s profile
            </a>
            <Detail call={viewing} data={data} />
          </section>
        ) : (
          <>
            <Habits resident={resident} calls={calls} now={data.now} />
            <Learned data={data} resident={resident} now={data.now} />
            <AddNote data={data} resident={resident} />
            <Medical resident={resident} now={data.now} />
            <CallHistory resident={resident} calls={calls} now={data.now} />
          </>
        )}
      </article>
    </div>
  )
}
