import { useState } from 'react'
import type { BellhopData, Call, Resident } from '../../data/types'
import { clock, closestFreeRobot, initials, isOpen, openCallIn, robotAvailability, statusText } from '../../lib'
import { Chip } from '../shared'
import { recordDispatch, useDispatched } from '../board'

// Staff can send a robot to a room by hand. It rings the bell for that room (POST /calls), so the
// backend's own dispatcher picks the nearest free robot, exactly as for a resident's bell. The
// result shows on the Live tab like any other call.

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
      {shown.length === 0 && <p className="sm-empty">No room matches "{query}".</p>}
      <ul>
        {shown.map((r) => {
          const open = openCallIn(data.calls, r.room)
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
          <input value={other} onChange={(e) => setOther(e.target.value)} maxLength={32} placeholder="Room or place name" />
        </label>
        <button className="sb-btn" type="submit" disabled={!other.trim()}>
          Choose
        </button>
      </form>
    </nav>
  )
}

function RobotRows({ data, room }: { data: BellhopData; room?: string }) {
  const likely = room ? closestFreeRobot(data.robots, room) : undefined
  if (data.robots.length === 0) return <p className="sm-empty">No robots have reported in yet.</p>
  return (
    <ul className="sm-dispatch-robots" aria-label="Robots">
      {data.robots.map((r) => {
        const a = robotAvailability(r)
        return (
          <li key={r.id} className={a.free ? 'free' : 'busy'}>
            <b>{r.name}</b>
            <span className="sm-avail">{a.words}</span>
            {likely?.id === r.id && <span className="sm-likely">Closest free robot</span>}
            <em>
              {Math.round(r.battery)}%{r.room ? `, ${r.room}` : ''}
            </em>
          </li>
        )
      })}
    </ul>
  )
}

function Sent({ data }: { data: BellhopData }) {
  const sent = useDispatched()
  const find = (id: string): Call | undefined => [...data.calls, ...data.pastCalls].find((c) => c.id === id)
  return (
    <section>
      <h2>Sent from here</h2>
      {sent.length === 0 ? (
        <p className="sm-empty">Nothing sent from this screen yet.</p>
      ) : (
        <ul className="sm-sent">
          {sent.map((s) => {
            const call = find(s.callId)
            const robot = call?.robotId ? data.robots.find((r) => r.id === call.robotId)?.name : undefined
            return (
              <li key={s.callId} className={call && isOpen(call) ? 'open' : 'done'}>
                <time>{clock(s.at)}</time>
                <b>Room {s.room}</b>
                <span>{call ? (isOpen(call) ? `${robot ?? 'A nurse'}: ${statusText(call)}` : call.resolvedByRobot ? 'Finished, the robot handled it' : 'Finished') : 'Waiting for the backend'}</span>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function SendSection({ data, room, resident }: { data: BellhopData; room: string; resident?: Resident }) {
  const [busy, setBusy] = useState(false)
  const open = openCallIn(data.calls, room)
  const likely = closestFreeRobot(data.robots, room)
  const offline = data.connection.state !== 'live'
  let reason = ''
  if (offline) reason = 'Bellhop cannot be reached right now.'
  else if (open) reason = `Room ${room} already has an open call: ${statusText(open).toLowerCase()}. Sending another robot would only double up.`
  else if (!likely) reason = 'No robot is free, so none can be sent. Robots that are charging return when they are full.'
  const send = async () => {
    setBusy(true)
    const id = await data.actions.sendRobot(room)
    setBusy(false)
    if (id) recordDispatch({ callId: id, room, at: Date.now() })
  }
  return (
    <section>
      <h2>Send</h2>
      {reason ? (
        <p className="sm-why" role="status">
          {reason}
        </p>
      ) : (
        <p className="sm-empty">
          {likely?.name} is the closest free robot. It drives to room {room}{resident ? ` and talks with ${resident.name.split(' ')[0]}` : ''}. The call shows on the Live tab like any other.
        </p>
      )}
      <button className="sb-btn primary big sm-send" onClick={() => void send()} disabled={busy || Boolean(reason)}>
        {busy ? 'Sending...' : `Send a robot to room ${room}`}
      </button>
    </section>
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
            <h1>{room ? `Room ${room}` : 'Send a robot'}</h1>
            <p>{room ? (resident ? `${resident.name}${resident.flags.length ? `, ${resident.flags.join(', ')}` : ''}` : 'No resident on record for this place') : 'Choose a room on the left, then send the nearest free robot there.'}</p>
          </div>
        </header>
        <section>
          <h2>Robots</h2>
          <RobotRows data={data} room={room} />
        </section>
        {room && <SendSection key={room} data={data} room={room} resident={resident} />}
        <Sent data={data} />
      </article>
    </div>
  )
}
