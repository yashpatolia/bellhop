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
    resolved_by_robot: t.u32(), // 0 = not decided, 1 = no, 2 = yes
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

// What Bellhop knows about a resident. `times_seen` counts how often it was heard.
const memory_fact = table(
  { name: 'memory_fact', public: true },
  {
    id: t.string().primaryKey(),
    resident_id: t.string().index('btree'),
    text: t.string(),
    tags: t.string(), // comma-joined; the first tag is the kind (like, dislike, ...)
    created_at: t.string(),
    source: t.string(), // staff | conversation | family | inferred
    confidence: t.f64(),
    quote: t.string(), // "" = none
    call_id: t.string(), // "" = none
    last_confirmed: t.string(),
    times_seen: t.u32(),
  }
);

// Facts waiting for a nurse to approve or reject them.
const pending_fact = table(
  { name: 'pending_fact', public: true },
  {
    id: t.string().primaryKey(),
    resident_id: t.string().index('btree'),
    text: t.string(),
    tags: t.string(),
    source: t.string(),
    confidence: t.f64(),
    quote: t.string(),
    call_id: t.string(),
  }
);

// Mood, pain and drink readings. `value` 0 = none (a reading is 1 to 5).
const care_entry = table(
  { name: 'care_entry', public: true },
  {
    id: t.string().primaryKey(),
    resident_id: t.string().index('btree'),
    call_id: t.string(),
    kind: t.string(), // mood | pain | drink | repeat_question
    value: t.f64(),
    note: t.string(),
    at: t.string(),
  }
);

const flag = table(
  { name: 'flag', public: true },
  {
    id: t.string().primaryKey(),
    resident_id: t.string().index('btree'),
    call_id: t.string(),
    type: t.string(), // pain | asks_for_nurse | distress | no_answer
    reason: t.string(),
    created_at: t.string(),
    resolved_at: t.string(), // "" = open
  }
);

const preferences = table(
  { name: 'preferences', public: true },
  {
    resident_id: t.string().primaryKey(),
    hard_of_hearing: t.bool(),
    quiet_mode: t.bool(),
    night_mode: t.bool(),
    favourite_drink: t.string(), // "" = none
  }
);

const family_message = table(
  { name: 'family_message', public: true },
  {
    id: t.string().primaryKey(),
    resident_id: t.string().index('btree'),
    direction: t.string(), // to_resident | from_resident
    text: t.string(),
    created_at: t.string(),
  }
);

// When each resident last had their family voice notes read out.
const family_delivery = table(
  { name: 'family_delivery', public: true },
  { resident_id: t.string().primaryKey(), at: t.string() }
);

// Medical history entered by staff. The lists are JSON text.
const medical_record = table(
  { name: 'medical_record', public: true },
  {
    resident_id: t.string().primaryKey(),
    conditions: t.string(), // JSON [{name, since, note}]
    allergies: t.string(), // JSON [string]
    medicines: t.string(), // JSON [string]
    mobility: t.string(),
    diet: t.string(),
    last_review: t.string(), // "" = never
    reviewed_by: t.string(),
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
  pending_fact,
  care_entry,
  flag,
  preferences,
  family_message,
  family_delivery,
  medical_record,
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
    resolved_by_robot: t.u32(),
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
    source: t.string(),
    confidence: t.f64(),
    quote: t.string(),
    call_id: t.string(),
    last_confirmed: t.string(),
    times_seen: t.u32(),
  },
  (ctx, row) => {
    if (ctx.db.memory_fact.id.find(row.id)) ctx.db.memory_fact.id.update(row);
    else ctx.db.memory_fact.insert(row);
  }
);

export const delete_memory_fact = spacetimedb.reducer({ id: t.string() }, (ctx, { id }) => {
  ctx.db.memory_fact.id.delete(id);
});

// "Forget everything" for one resident.
export const delete_resident_memory = spacetimedb.reducer(
  { resident_id: t.string() },
  (ctx, { resident_id }) => {
    for (const row of [...ctx.db.memory_fact.resident_id.filter(resident_id)]) {
      ctx.db.memory_fact.id.delete(row.id);
    }
    for (const row of [...ctx.db.pending_fact.resident_id.filter(resident_id)]) {
      ctx.db.pending_fact.id.delete(row.id);
    }
  }
);

export const save_pending_fact = spacetimedb.reducer(
  {
    id: t.string(),
    resident_id: t.string(),
    text: t.string(),
    tags: t.string(),
    source: t.string(),
    confidence: t.f64(),
    quote: t.string(),
    call_id: t.string(),
  },
  (ctx, row) => {
    if (ctx.db.pending_fact.id.find(row.id)) ctx.db.pending_fact.id.update(row);
    else ctx.db.pending_fact.insert(row);
  }
);

export const delete_pending_fact = spacetimedb.reducer({ id: t.string() }, (ctx, { id }) => {
  ctx.db.pending_fact.id.delete(id);
});

export const save_care_entry = spacetimedb.reducer(
  {
    id: t.string(),
    resident_id: t.string(),
    call_id: t.string(),
    kind: t.string(),
    value: t.f64(),
    note: t.string(),
    at: t.string(),
  },
  (ctx, row) => {
    if (ctx.db.care_entry.id.find(row.id)) ctx.db.care_entry.id.update(row);
    else ctx.db.care_entry.insert(row);
  }
);

export const save_flag = spacetimedb.reducer(
  {
    id: t.string(),
    resident_id: t.string(),
    call_id: t.string(),
    type: t.string(),
    reason: t.string(),
    created_at: t.string(),
    resolved_at: t.string(),
  },
  (ctx, row) => {
    if (ctx.db.flag.id.find(row.id)) ctx.db.flag.id.update(row);
    else ctx.db.flag.insert(row);
  }
);

export const save_preferences = spacetimedb.reducer(
  {
    resident_id: t.string(),
    hard_of_hearing: t.bool(),
    quiet_mode: t.bool(),
    night_mode: t.bool(),
    favourite_drink: t.string(),
  },
  (ctx, row) => {
    if (ctx.db.preferences.resident_id.find(row.resident_id)) ctx.db.preferences.resident_id.update(row);
    else ctx.db.preferences.insert(row);
  }
);

export const save_family_message = spacetimedb.reducer(
  {
    id: t.string(),
    resident_id: t.string(),
    direction: t.string(),
    text: t.string(),
    created_at: t.string(),
  },
  (ctx, row) => {
    if (ctx.db.family_message.id.find(row.id)) ctx.db.family_message.id.update(row);
    else ctx.db.family_message.insert(row);
  }
);

export const save_family_delivery = spacetimedb.reducer(
  { resident_id: t.string(), at: t.string() },
  (ctx, row) => {
    if (ctx.db.family_delivery.resident_id.find(row.resident_id)) ctx.db.family_delivery.resident_id.update(row);
    else ctx.db.family_delivery.insert(row);
  }
);

export const save_medical_record = spacetimedb.reducer(
  {
    resident_id: t.string(),
    conditions: t.string(),
    allergies: t.string(),
    medicines: t.string(),
    mobility: t.string(),
    diet: t.string(),
    last_review: t.string(),
    reviewed_by: t.string(),
  },
  (ctx, row) => {
    if (ctx.db.medical_record.resident_id.find(row.resident_id)) ctx.db.medical_record.resident_id.update(row);
    else ctx.db.medical_record.insert(row);
  }
);
