import { useState } from 'react'
import type { BellhopData, Resident } from '../../data/types'
import { clock, closestFreeRobot, initials, isOpen, nextRobotId, robotAvailability } from '../../lib'
import { Chip } from '../shared'
import { recordDispatch, useDispatched } from '../board'

// Staff drive a chosen robot to a room by hand (POST /robots/{id}/navigate) and can stop it
// (POST /robots/{id}/stop). It only drives: no call is made and the robot does not start a visit.
// The Pi decides what the target means (a configured room name or a marker id) and reports where
// the robot really is. The closest free robot is preselected.

const byRoom = (a: Resident, b: Resident) => a.room.localeCompare(b.room, undefined, { numeric: true })

function RoomList({ data, selected }: { data: BellhopData; selected?: string }) {
  const [query, setQuery] = useState('')
  const [other, setOther] = useState('')
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean)
  const shown = data.residents.slice().sort(byRoom).filter((r) => terms.every((t) => `room ${r.room} ${r.name}`.toLowerCase().includes(t)))
  return (
    <nav className="sm-reslist" aria-label="Rooms">
      <h2>Rooms</h2>
      <input className="sm-search" type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search room or name" aria-label="Search rooms" />
      <p className="sm-count" aria-live="polite">
        {query ? `${shown.length} of ${data.residents.length} rooms` : `${data.residents.length} rooms`}
      </p>
      {data.residents.length === 0 ? (
        <p className="sm-empty">No rooms yet. A room appears here once a resident is in it, from the Residents tab. You can still send a robot to another place below.</p>
      ) : (
        shown.length === 0 && <p className="sm-empty">No room matches "{query}".</p>
      )}
      <ul>
        {shown.map((r) => {
          const open = data.calls.find((c) => c.room === r.room && isOpen(c))
          return (
            <li key={r.id}>
              <a href={`#/dispatch/${encodeURIComponent(r.room)}`} aria-current={r.room === selected ? 'page' : undefined}>
                <span className="sm-resname">
                  Room {r.room} <small>{r.name}</small>
                </span>
                <span className="sm-resmeta">{open ? <Chip u={open.urgency} /> : <span>No open call</span>}</span>
              </a>
            </li>
          )
        })}
      </ul>
      <form
        className="sm-other"
        onSubmit={(e) => {
          e.preventDefault()
          const room = other.trim()
          if (room) window.location.hash = `#/dispatch/${encodeURIComponent(room)}`
        }}
      >
        <label>
          Another place, such as the lobby
          <input value={other} onChange={(e) => setOther(e.target.value)} maxLength={32} placeholder="Room, place or marker id" />
        </label>
        <button className="sb-btn" type="submit" disabled={!other.trim()}>
          Choose
        </button>
      </form>
    </nav>
  )
}

function RobotRows({ data, room, chosen, onChoose }: { data: BellhopData; room: string | undefined; chosen: string | undefined; onChoose: (id: string) => void }) {
  const closest = room ? closestFreeRobot(data.robots, room) : undefined
  if (data.robots.length === 0) return <p className="sm-empty">No robots have reported in yet.</p>
  return (
    <ul className="sm-dispatch-robots" aria-label="Robots">
      {data.robots.map((r) => {
        const a = robotAvailability(r)
        return (
          <li key={r.id} className={`${a.free ? 'free' : 'busy'} ${chosen === r.id ? 'chosen' : ''}`}>
            <label>
              <input type="radio" name="robot" value={r.id} checked={chosen === r.id} disabled={!room || !a.free} onChange={() => onChoose(r.id)} />
              <b>{r.name}</b>
              <span className="sm-avail">{a.words}</span>
              {closest?.id === r.id && <span className="sm-likely">Closest free robot</span>}
              <em>
                {Math.round(r.battery)}%{r.room ? `, ${r.room}` : ''}
              </em>
            </label>
            {r.state === 'en_route' && (
              <button className="sb-btn sm-stop" onClick={() => void data.actions.stopRobot(r.id)} aria-label={`Stop ${r.name}`}>
                Stop {r.name}
              </button>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function Sent({ data }: { data: BellhopData }) {
  const sent = useDispatched()
  return (
    <section>
      <h2>Driven from here</h2>
      {sent.length === 0 ? (
        <p className="sm-empty">Nothing sent from this screen yet.</p>
      ) : (
        <ul className="sm-sent">
          {sent.map((s) => {
            const robot = data.robots.find((r) => r.id === s.robotId)
            const driving = robot?.state === 'en_route'
            return (
              <li key={`${s.robotId}-${s.at}`} className={driving ? 'open' : 'done'}>
                <time>{clock(s.at)}</time>
                <b>{robot?.name ?? s.robotId}</b>
                <span>
                  to {s.room}: {!robot ? 'no longer reporting' : driving ? 'driving' : robot.state === 'with_resident' ? 'now with a resident' : 'standing by (arrived or stopped)'}
                </span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

const ROBOT_ID = /^[a-z0-9][a-z0-9_-]{0,31}$/

function AddRobot({ data }: { data: BellhopData }) {
  const suggested = nextRobotId(data.robots.map((r) => r.id))
  const [id, setId] = useState('')
  const [room, setRoom] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [added, setAdded] = useState('')
  const wanted = (id.trim() || suggested).toLowerCase()
  let problem = ''
  if (!ROBOT_ID.test(wanted)) problem = 'Use lowercase letters, numbers, - or _, up to 32 characters.'
  else if (data.robots.some((r) => r.id === wanted)) problem = `${wanted} is already in the fleet.`
  const add = async () => {
    setBusy(true)
    setError('')
    try {
      await data.actions.addRobot(wanted, room.trim() || null)
      setAdded(wanted)
      setId('')
      setRoom('')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Bellhop did not add the robot.')
    }
    setBusy(false)
  }
  return (
    <section className="sm-addrobot">
      <h2>Add a robot to the fleet</h2>
      <p className="sm-empty">
        Use the id the robot is set up with (ROBOT_ID on the robot), so its reports land on this robot. Battery and position update as soon as it reports in.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          if (!problem) void add()
        }}
      >
        <label>
          Robot id
          <input value={id} onChange={(e) => setId(e.target.value)} placeholder={suggested} maxLength={32} spellCheck={false} />
        </label>
        <label>
          <span>
            Where it stands by <small>(optional)</small>
          </span>
          <input value={room} onChange={(e) => setRoom(e.target.value)} placeholder="Charging dock, lobby or a room" maxLength={32} />
        </label>
        <button className="sb-btn primary" type="submit" disabled={busy || Boolean(problem) || data.connection.state !== 'live'}>
          {busy ? 'Adding...' : `Add ${wanted}`}
        </button>
      </form>
      {(problem && id.trim()) || error ? (
        <p className="sm-why" role="alert">
          {error || problem}
        </p>
      ) : added ? (
        <p className="sm-empty" role="status">
          {added} is in the fleet and standing by.
        </p>
      ) : null}
    </section>
  )
}

function Body({ data, room, resident }: { data: BellhopData; room?: string; resident?: Resident }) {
  const [picked, setPicked] = useState<string | undefined>()
  const [busy, setBusy] = useState(false)
  const closest = room ? closestFreeRobot(data.robots, room) : undefined
  // The nurse's pick, as long as that robot is still free; otherwise the closest free robot.
  const pickedRobot = data.robots.find((r) => r.id === picked && robotAvailability(r).free)
  const robot = pickedRobot ?? closest
  let reason = ''
  if (data.connection.state !== 'live') reason = 'Bellhop cannot be reached right now.'
  else if (!robot) reason = 'No robot is free, so none can be driven. A robot that is driving, with a resident or charging cannot take a new target.'
  const send = async () => {
    if (!room || !robot) return
    setBusy(true)
    const ok = await data.actions.driveRobot(robot.id, room)
    setBusy(false)
    if (ok) recordDispatch({ robotId: robot.id, room, at: Date.now() })
  }
  return (
    <>
      <section>
        <h2>Robots</h2>
        <RobotRows data={data} room={room} chosen={robot?.id} onChoose={setPicked} />
      </section>
      {room && (
        <section>
          <h2>Drive</h2>
          {reason ? (
            <p className="sm-why" role="status">
              {reason}
            </p>
          ) : (
            <p className="sm-empty">
              {robot?.name} drives to {resident ? `room ${room}, where ${resident.name.split(' ')[0]} is` : room}. It only drives: no call is made and it does not start a visit. Use Stop beside a driving robot to halt it. Choose a different free robot above if you prefer.
            </p>
          )}
          <button className="sb-btn primary big sm-send" onClick={() => void send()} disabled={busy || Boolean(reason)}>
            {busy ? 'Sending...' : robot ? `Drive ${robot.name} to ${room}` : `Drive a robot to ${room}`}
          </button>
        </section>
      )}
    </>
  )
}

export function DispatchPage({ data, room }: { data: BellhopData; room?: string }) {
  const resident = room ? data.residents.find((r) => r.room === room) : undefined
  return (
    <div className="sm-people">
      <RoomList data={data} selected={room} />
      <article className="sm-profile" aria-label="Dispatch">
        <header>
          <span className="sm-avatar" aria-hidden="true">
            {resident ? initials(resident.name) : '?'}
          </span>
          <div>
            <h1>{room ? `Room ${room}` : 'Drive a robot'}</h1>
            <p>{room ? (resident ? `${resident.name}${resident.flags.length ? `, ${resident.flags.join(', ')}` : ''}` : 'No resident on record for this place') : 'Choose a room on the left, then choose which free robot to drive there.'}</p>
          </div>
        </header>
        <Body key={room ?? ''} data={data} room={room} resident={resident} />
        <Sent data={data} />
        <AddRobot data={data} />
      </article>
    </div>
  )
}
