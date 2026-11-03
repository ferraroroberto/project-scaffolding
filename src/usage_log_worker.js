// The Cloudflare half of the usage log: the same contract as src/usage_log.py, for a
// public site served by a Cloudflare Worker, writing the same `events` table in D1.
//
// VENDORED VERBATIM from project-scaffolding (manifest key `usage_log_worker`). Do NOT edit
// per app: an app imports it in its own Worker and mounts the two handlers on the paths the
// vendored client uses:
//
//   import { handleUsageEvents, usageSummary, USAGE_SCHEMA } from './usage_log_worker.js';
//   if (url.pathname === '/api/usage/events') return handleUsageEvents(request, env.DB);
//   // GET /api/usage/summary behind the app's own auth:
//   return Response.json(await usageSummary(env.DB, 30));
//
// What it stores is what usage_log.py stores (event kind, view id, control id, a random
// per-visit session id, device and OS class, a server timestamp), validated by the same
// rules, plus the two columns only a server that sees the request can fill:
//   country  two letters from the edge (request.cf.country), or NULL;
//   visitor  SHA-256 of a random salt, the address and the user agent, cut to 16 hex. The
//            salt is new each UTC day and deleted after it, so a visitor counts once per day
//            and the hash cannot be linked to the address, or to the same visitor another day.
// Never stored: the address, the user agent, URLs, query strings, form values, cookies.
//
// Identified mode, for a public site behind a consent banner, is opt-in per call:
//
//   handleUsageEvents(request, env.DB, { identify: {
//     visitorCookie: 'uv', consentCookie: 'consent', ipRetentionDays: 30 } });
//
// The server enforces consent itself: a request whose consent cookie is not `granted` stores
// nothing and touches no table. With it, `visitor` is the client's random cookie id (32 hex)
// instead of the daily hash, and `ip` holds cf-connecting-ip. Every identified write clears
// `ip` on rows older than ipRetentionDays (purgeIps, exported for an admin read to run too);
// country, device and pages stay. Fleet apps never use this mode.
//
// Instrumentation never breaks the site: a bad envelope is a 400, an oversized body a 413,
// and a database error a 503 with one log line; the client ignores all of them.

export const EVENT_KINDS = new Set(['session_start', 'view', 'tap', 'session_end', 'referrer']);
export const DEVICE_CLASSES = new Set(['phone', 'tablet', 'desktop']);
export const OS_CLASSES = new Set(['ios', 'android', 'windows', 'other']);
// Mirrors usage_log.py ID_PATTERN and SESSION_ID_PATTERN.
export const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$/;
const SESSION_ID_PATTERN = /^[A-Za-z0-9-]{8,64}$/;
export const MAX_EVENTS_PER_BATCH = 50;
export const MAX_BODY_BYTES = 16384;
export const MAX_AGE_DAYS = 365;
export const MAX_ROWS = 200000;
// Mirrors the client's VISITOR_ID_PATTERN: 128 random bits as lowercase hex.
export const VISITOR_ID_PATTERN = /^[0-9a-f]{32}$/;
export const CONSENT_GRANTED = 'granted';
// An IPv4 or IPv6 literal as the edge reports it; anything else is not stored.
const IP_PATTERN = /^[0-9A-Fa-f:.]{2,45}$/;

/** The D1 schema: the events table usage_log.py creates, plus the daily salts. */
export const USAGE_SCHEMA = `
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL,
    session_id   TEXT NOT NULL,
    kind         TEXT NOT NULL,
    view_id      TEXT,
    control_id   TEXT,
    device_class TEXT NOT NULL,
    os_class     TEXT NOT NULL,
    country      TEXT,
    visitor      TEXT,
    ip           TEXT
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
CREATE TABLE IF NOT EXISTS usage_salts (day TEXT PRIMARY KEY, salt TEXT NOT NULL);
`;

export class PayloadError extends Error {}

// Columns added after the first release, created in place on an older database.
const ADDED_COLUMNS = [['ip', 'TEXT']];

async function applySchema(db) {
  const statements = USAGE_SCHEMA.split(';').map((s) => s.trim()).filter(Boolean);
  await db.batch(statements.map((s) => db.prepare(s)));
  const { results } = await db.prepare('PRAGMA table_info(events)').all();
  const have = new Set(results.map((r) => r.name));
  for (const [name, kind] of ADDED_COLUMNS) {
    if (!have.has(name)) await db.prepare(`ALTER TABLE events ADD COLUMN ${name} ${kind}`).run();
  }
}

// The schema is applied once per database per Worker isolate, the first time it is used.
const schemaReady = new WeakMap();
function ensureSchema(db) {
  if (!schemaReady.has(db)) {
    schemaReady.set(db, applySchema(db).catch((err) => {
      schemaReady.delete(db);
      throw err;
    }));
  }
  return schemaReady.get(db);
}

const validId = (v) => typeof v === 'string' && ID_PATTERN.test(v);

/** One client event as [kind, view_id, control_id], or null to drop it (usage_log.validate_event). */
export function validateEvent(raw) {
  if (raw === null || typeof raw !== 'object' || Array.isArray(raw)) return null;
  const { kind, id, view } = raw;
  if (typeof kind !== 'string' || !EVENT_KINDS.has(kind)) return null;
  if (view !== undefined && view !== null && !validId(view)) return null;
  const context = typeof view === 'string' ? view : null;
  if (kind === 'view') return validId(id) ? [kind, id, null] : null;
  if (kind === 'tap' || kind === 'referrer') return validId(id) ? [kind, context, id] : null;
  return [kind, context, null];
}

/** Decode and validate a POST body (usage_log.parse_batch); throws PayloadError. */
export function parseBatch(text) {
  if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) throw new PayloadError('batch too large');
  let data;
  try { data = JSON.parse(text); } catch (_) { throw new PayloadError('body is not JSON'); }
  if (data === null || typeof data !== 'object' || Array.isArray(data)) throw new PayloadError('body is not a JSON object');
  const { session_id: sessionId, device_class: device, os_class: os, events } = data;
  if (typeof sessionId !== 'string' || !SESSION_ID_PATTERN.test(sessionId)) throw new PayloadError('bad session_id');
  if (typeof device !== 'string' || !DEVICE_CLASSES.has(device)) throw new PayloadError('bad device_class');
  if (typeof os !== 'string' || !OS_CLASSES.has(os)) throw new PayloadError('bad os_class');
  if (!Array.isArray(events) || events.length > MAX_EVENTS_PER_BATCH) throw new PayloadError('bad events list');
  const batch = { sessionId, device, os, events: [], rejected: 0 };
  for (const raw of events) {
    const event = validateEvent(raw);
    if (event) batch.events.push(event); else batch.rejected += 1;
  }
  return batch;
}

/** UTC timestamp in the one stored format (usage_log.format_ts). */
export function formatTs(date) {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function hex(bytes) {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** The visitor hash for one request, from today's salt (created on first use). */
async function visitorHash(db, request, now) {
  const day = formatTs(now).slice(0, 10);
  const fresh = hex(crypto.getRandomValues(new Uint8Array(16)));
  await db.batch([
    db.prepare('DELETE FROM usage_salts WHERE day < ?1').bind(day),
    db.prepare('INSERT OR IGNORE INTO usage_salts (day, salt) VALUES (?1, ?2)').bind(day, fresh),
  ]);
  const salt = await db.prepare('SELECT salt FROM usage_salts WHERE day = ?1').bind(day).first('salt');
  const ip = request.headers.get('cf-connecting-ip') || '';
  const ua = request.headers.get('user-agent') || '';
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${salt}|${ip}|${ua}`));
  return hex(new Uint8Array(digest)).slice(0, 16);
}

function country(request) {
  const c = request.cf && request.cf.country;
  return typeof c === 'string' && /^[A-Z]{2}$/.test(c) ? c : null;
}

/** One cookie's value from the request, or null. */
function cookie(request, name) {
  for (const part of (request.headers.get('cookie') || '').split(';')) {
    const at = part.indexOf('=');
    if (at > 0 && part.slice(0, at).trim() === name) return part.slice(at + 1).trim();
  }
  return null;
}

function clientIp(request) {
  const ip = request.headers.get('cf-connecting-ip') || '';
  return IP_PATTERN.test(ip) ? ip : null;
}

const PURGE_IPS = 'UPDATE events SET ip = NULL WHERE ip IS NOT NULL AND ts < ?1';

function purgeStatement(db, days, now) {
  return db.prepare(PURGE_IPS).bind(formatTs(new Date(now.getTime() - days * 86400000)));
}

/** Clear the stored address on every row older than `days` days; the rest of the row stays. */
export async function purgeIps(db, days, { now = new Date() } = {}) {
  if (!Number.isInteger(days) || days < 1) throw new TypeError('purgeIps: days must be a positive integer');
  await ensureSchema(db);
  await purgeStatement(db, days, now).run();
}

function json(body, status) {
  return new Response(JSON.stringify(body), {
    status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' },
  });
}

/** POST /api/usage/events: validate a client batch and store it, then apply retention.
 *  `identify` switches on identified mode (see the header); without it nothing changes. */
export async function handleUsageEvents(request, db, { now = new Date(), identify = null } = {}) {
  if (request.method !== 'POST') return new Response('Method Not Allowed', { status: 405, headers: { allow: 'POST' } });
  if (Number(request.headers.get('content-length') || 0) > MAX_BODY_BYTES) return json({ error: 'batch too large' }, 413);
  let batch;
  try {
    batch = parseBatch(await request.text());
  } catch (err) {
    if (err instanceof PayloadError) return json({ error: err.message }, err.message === 'batch too large' ? 413 : 400);
    throw err;
  }
  if (identify) return storeIdentified(request, db, batch, now, identify);
  try {
    await ensureSchema(db);
    const ts = formatTs(now);
    const visitor = await visitorHash(db, request, now);
    const where = country(request);
    const insert = 'INSERT INTO events (ts, session_id, kind, view_id, control_id, device_class, os_class, country, visitor)'
      + ' VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9)';
    await db.batch([
      ...batch.events.map(([kind, view, control]) => db.prepare(insert)
        .bind(ts, batch.sessionId, kind, view, control, batch.device, batch.os, where, visitor)),
      ...retention(db, now),
    ]);
  } catch (err) {
    console.log(JSON.stringify({ event: 'usage.dropped', error: String(err && err.message) }));
    return json({ error: 'not stored' }, 503);
  }
  return json({ accepted: batch.events.length, rejected: batch.rejected }, 200);
}

/** The age and row caps every write applies. */
function retention(db, now) {
  const cutoff = formatTs(new Date(now.getTime() - MAX_AGE_DAYS * 86400000));
  return [
    db.prepare('DELETE FROM events WHERE ts < ?1').bind(cutoff),
    db.prepare('DELETE FROM events WHERE id <= (SELECT id FROM events ORDER BY id DESC LIMIT 1 OFFSET ?1)').bind(MAX_ROWS),
  ];
}

/** Identified mode: store only with consent, with the cookie visitor id and the address. */
async function storeIdentified(request, db, batch, now, { visitorCookie, consentCookie, ipRetentionDays }) {
  const days = Number(ipRetentionDays);
  if (typeof visitorCookie !== 'string' || !visitorCookie || typeof consentCookie !== 'string' || !consentCookie
      || !Number.isInteger(days) || days < 1) {
    console.log(JSON.stringify({ event: 'usage.misconfigured', error: 'identify needs visitorCookie, consentCookie and a positive integer ipRetentionDays' }));
    return json({ error: 'not stored' }, 503);
  }
  if (cookie(request, consentCookie) !== CONSENT_GRANTED) {
    console.log(JSON.stringify({ event: 'usage.no_consent', events: batch.events.length }));
    return json({ accepted: 0, rejected: batch.events.length + batch.rejected }, 200);
  }
  const id = cookie(request, visitorCookie);
  const visitor = VISITOR_ID_PATTERN.test(id || '') ? id : null;
  try {
    await ensureSchema(db);
    const ts = formatTs(now);
    const where = country(request);
    const ip = clientIp(request);
    const insert = 'INSERT INTO events (ts, session_id, kind, view_id, control_id, device_class, os_class, country, visitor, ip)'
      + ' VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)';
    await db.batch([
      ...batch.events.map(([kind, view, control]) => db.prepare(insert)
        .bind(ts, batch.sessionId, kind, view, control, batch.device, batch.os, where, visitor, ip)),
      ...retention(db, now),
      purgeStatement(db, days, now),
    ]);
  } catch (err) {
    console.log(JSON.stringify({ event: 'usage.dropped', error: String(err && err.message) }));
    return json({ error: 'not stored' }, 503);
  }
  return json({ accepted: batch.events.length, rejected: batch.rejected }, 200);
}

async function counts(db, sql, since) {
  const { results } = await db.prepare(sql).bind(since).all();
  const out = {};
  for (const row of results) out[row.k] = row.n;
  return out;
}

// Visitors in the window also seen on another UTC day, earlier stored history included
// (usage_log.py _RETURNING_SQL). A daily-hash visitor changes every day, so it is 0 there.
const RETURNING_SQL = 'SELECT COUNT(*) AS n FROM (SELECT visitor FROM events WHERE visitor IN'
  + ' (SELECT visitor FROM events WHERE ts >= ?1 AND visitor IS NOT NULL)'
  + ' GROUP BY visitor HAVING COUNT(DISTINCT substr(ts, 1, 10)) > 1)';

/** The summary usage_log.summarize returns, over the last `days` days. */
export async function usageSummary(db, days, { now = new Date() } = {}) {
  await ensureSchema(db);
  const since = formatTs(new Date(now.getTime() - days * 86400000));
  const where = 'FROM events WHERE ts >= ?1';
  const totals = await db.prepare(
    `SELECT COUNT(*) AS events, COUNT(DISTINCT session_id) AS sessions, MIN(ts) AS first, MAX(ts) AS last ${where}`,
  ).bind(since).first();
  const visitors = await db.prepare(`SELECT COUNT(DISTINCT visitor) AS n ${where} AND visitor IS NOT NULL`).bind(since).first('n');
  const returning = await db.prepare(RETURNING_SQL).bind(since).first('n');
  return {
    days,
    since,
    events: totals.events,
    sessions: totals.sessions,
    first_ts: totals.first,
    last_ts: totals.last,
    views: await counts(db, `SELECT view_id AS k, COUNT(*) AS n ${where} AND kind = 'view' GROUP BY view_id ORDER BY n DESC, k`, since),
    controls: await counts(db, `SELECT control_id AS k, COUNT(*) AS n ${where} AND kind = 'tap' GROUP BY control_id ORDER BY n DESC, k`, since),
    devices: await counts(db, `SELECT device_class AS k, COUNT(DISTINCT session_id) AS n ${where} GROUP BY device_class ORDER BY k`, since),
    os: await counts(db, `SELECT os_class AS k, COUNT(DISTINCT session_id) AS n ${where} GROUP BY os_class ORDER BY k`, since),
    referrers: await counts(db, `SELECT control_id AS k, COUNT(*) AS n ${where} AND kind = 'referrer' GROUP BY control_id ORDER BY n DESC, k`, since),
    countries: await counts(db, `SELECT country AS k, COUNT(DISTINCT session_id) AS n ${where} AND country IS NOT NULL GROUP BY country ORDER BY n DESC, k`, since),
    visitors,
    returning,
  };
}
