// Bellhop SpacetimeDB module (v2 TypeScript API).
// Column order here is the reducer argument order and must match
// backend/src/bellhop/adapters/spacetimedb_store.py (COLUMNS). Business rules stay in
// Python; reducers only upsert full rows. Sentinels: "" = none, 0 = none/unscored.
import { schema, table, t } from 'spacetimedb/server';

const call = table(
  { name: 'call', public: true },
  {
    id: t.string().primaryKey(),
    room: t.string().index('btree'),
    resident_id: t.string(),
    urgency: t.u32(), // 0 = unscored, 1..4
    category: t.string(),
    status: t.string().index('btree'),
    summary: t.string(),
    assigned_to: t.string(), // comma-joined robot/nurse ids
    robot_id: t.string(),
    nurse_tasks: t.string(), // comma-joined nurse ids
    created_at: t.string(), // ISO-8601 from the Python Clock
    assigned_at: t.string(),
    first_response_at: t.string(),
    resolved_at: t.string(),
  }
);

const call_turn = table(
  { name: 'call_turn', public: true },
  {
    id: t.string().primaryKey(), // "{call_id}:{seq}"
    call_id: t.string().index('btree'),
    seq: t.u32(),
    speaker: t.string(),
    text: t.string(),
    at: t.string(),
  }
);

const resident = table(
  { name: 'resident', public: true },
  {
    id: t.string().primaryKey(),
    name: t.string(),
    room: t.string().index('btree'),
    risk_flags: t.string(), // comma-joined
    birth_year: t.u32(), // 0 = unknown
  }
);

const nurse = table(
  { name: 'nurse', public: true },
  {
    id: t.string().primaryKey(),
    name: t.string(),
    on_shift: t.bool(),
    open_tasks: t.u32(),
  }
);

const robot = table(
  { name: 'robot', public: true },
  {
    id: t.string().primaryKey(),
    status: t.string(),
    battery: t.f64(),
    room: t.string(), // "" = none
  }
);

const alert = table(
  { name: 'alert', public: true },
  {
    id: t.string().primaryKey(),
    call_id: t.string().index('btree'),
    nurse_id: t.string(), // "" = broadcast
    level: t.u32(),
    message: t.string(),
    created_at: t.string(),
    acked_at: t.string(), // "" = open
  }
);

const visit = table(
  { name: 'visit', public: true },
  {
    id: t.string().primaryKey(),
    call_id: t.string().index('btree'),
    resident_id: t.string(),
    robot_id: t.string(),
    resolved_by_robot: t.bool(),
    rating: t.u32(), // 0 = none
    mood: t.string(),
    nurse_urgency_override: t.u32(), // 0 = none
  }
);

const memory_fact = table(
  { name: 'memory_fact', public: true },
  {
    id: t.string().primaryKey(),
    resident_id: t.string().index('btree'),
    text: t.string(),
    tags: t.string(), // comma-joined
    created_at: t.string(),
  }
);

const spacetimedb = schema({
  call,
  call_turn,
  resident,
  nurse,
  robot,
  alert,
  visit,
  memory_fact,
});
export default spacetimedb;

export const save_call = spacetimedb.reducer(
  {
    id: t.string(),
    room: t.string(),
    resident_id: t.string(),
    urgency: t.u32(),
    category: t.string(),
    status: t.string(),
    summary: t.string(),
    assigned_to: t.string(),
    robot_id: t.string(),
    nurse_tasks: t.string(),
    created_at: t.string(),
    assigned_at: t.string(),
    first_response_at: t.string(),
    resolved_at: t.string(),
  },
  (ctx, row) => {
    if (ctx.db.call.id.find(row.id)) ctx.db.call.id.update(row);
    else ctx.db.call.insert(row);
  }
);

export const append_turn = spacetimedb.reducer(
  {
    call_id: t.string(),
    seq: t.u32(),
    speaker: t.string(),
    text: t.string(),
    at: t.string(),
  },
  (ctx, { call_id, seq, speaker, text, at }) => {
    const row = { id: `${call_id}:${seq}`, call_id, seq, speaker, text, at };
    if (ctx.db.call_turn.id.find(row.id)) ctx.db.call_turn.id.update(row);
    else ctx.db.call_turn.insert(row);
  }
);

export const save_resident = spacetimedb.reducer(
  {
    id: t.string(),
    name: t.string(),
    room: t.string(),
    risk_flags: t.string(),
    birth_year: t.u32(),
  },
  (ctx, row) => {
    if (ctx.db.resident.id.find(row.id)) ctx.db.resident.id.update(row);
    else ctx.db.resident.insert(row);
  }
);

export const save_nurse = spacetimedb.reducer(
  { id: t.string(), name: t.string(), on_shift: t.bool(), open_tasks: t.u32() },
  (ctx, row) => {
    if (ctx.db.nurse.id.find(row.id)) ctx.db.nurse.id.update(row);
    else ctx.db.nurse.insert(row);
  }
);

export const save_robot = spacetimedb.reducer(
  { id: t.string(), status: t.string(), battery: t.f64(), room: t.string() },
  (ctx, row) => {
    if (ctx.db.robot.id.find(row.id)) ctx.db.robot.id.update(row);
    else ctx.db.robot.insert(row);
  }
);

export const save_alert = spacetimedb.reducer(
  {
    id: t.string(),
    call_id: t.string(),
    nurse_id: t.string(),
    level: t.u32(),
    message: t.string(),
    created_at: t.string(),
    acked_at: t.string(),
  },
  (ctx, row) => {
    if (ctx.db.alert.id.find(row.id)) ctx.db.alert.id.update(row);
    else ctx.db.alert.insert(row);
  }
);

export const save_visit = spacetimedb.reducer(
  {
    id: t.string(),
    call_id: t.string(),
    resident_id: t.string(),
    robot_id: t.string(),
    resolved_by_robot: t.bool(),
    rating: t.u32(),
    mood: t.string(),
    nurse_urgency_override: t.u32(),
  },
  (ctx, row) => {
    if (ctx.db.visit.id.find(row.id)) ctx.db.visit.id.update(row);
    else ctx.db.visit.insert(row);
  }
);

export const save_memory_fact = spacetimedb.reducer(
  {
    id: t.string(),
    resident_id: t.string(),
    text: t.string(),
    tags: t.string(),
    created_at: t.string(),
  },
  (ctx, row) => {
    if (ctx.db.memory_fact.id.find(row.id)) ctx.db.memory_fact.id.update(row);
    else ctx.db.memory_fact.insert(row);
  }
);
