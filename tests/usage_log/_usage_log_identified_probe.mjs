// Drives src/usage_log_worker.js's identified, consent-gated mode under Node against an
// in-memory SQLite standing in for D1 and prints what it stored as JSON;
// tests/usage_log/test_usage_log_identified.py asserts on it.

import { DatabaseSync } from 'node:sqlite';
import { pathToFileURL } from 'node:url';
import { fakeD1 } from './_fake_d1.mjs';

const worker = await import(pathToFileURL(process.argv[2]).href);

const VISITOR_A = 'a'.repeat(32);
const VISITOR_B = '0123456789abcdef0123456789abcdef';
const identify = { visitorCookie: 'uv', consentCookie: 'consent', ipRetentionDays: 30 };
const envelope = (events) => ({ session_id: 'probe-session-1', device_class: 'desktop', os_class: 'windows', events });
const view = (id) => envelope([{ kind: 'session_start' }, { kind: 'view', id }]);

function post(body, { cookie = null, ip = '203.0.113.9', country = 'ES' } = {}) {
  const headers = { 'cf-connecting-ip': ip, 'user-agent': 'Probe/1.0', 'content-type': 'application/json' };
  if (cookie !== null) headers.cookie = cookie;
  const req = new Request('https://site.example/api/usage/events', { method: 'POST', headers, body: JSON.stringify(body) });
  Object.defineProperty(req, 'cf', { value: { country } });
  return req;
}

const rowsOf = (db) => db.sql.prepare('SELECT ts, kind, view_id, country, visitor, ip FROM events ORDER BY id').all().map((r) => ({ ...r }));
const tablesOf = (db) => db.sql.prepare("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name").all().map((r) => r.name);
const logs = [];
console.log = (line) => logs.push(JSON.parse(line));
const out = {};

const day1 = new Date('2026-10-01T10:00:00Z');
const day31 = new Date('2026-10-31T10:00:00Z');
const day32 = new Date('2026-11-01T10:00:00Z');

// No consent: nothing stored, no table touched, one info line.
{
  const db = fakeD1();
  const missing = await worker.handleUsageEvents(post(view('home'), { cookie: `uv=${VISITOR_A}` }), db, { now: day1, identify });
  const denied = await worker.handleUsageEvents(post(view('home'), { cookie: `consent=denied; uv=${VISITOR_A}` }), db, { now: day1, identify });
  const noCookies = await worker.handleUsageEvents(post(view('home')), db, { now: day1, identify });
  out.noConsent = {
    statuses: [missing.status, denied.status, noCookies.status],
    bodies: [await missing.json(), await denied.json(), await noCookies.json()],
    tables: tablesOf(db),
    logs: logs.splice(0),
  };
}

// Consent: the cookie id and the address are stored; a malformed id or address is not.
{
  const db = fakeD1();
  const ok = await worker.handleUsageEvents(post(view('about'), { cookie: `uv=${VISITOR_A}; consent=granted` }), db, { now: day1, identify });
  await worker.handleUsageEvents(post(view('home'), { cookie: 'consent=granted; uv=not-hex', ip: '2001:db8::1' }), db, { now: day1, identify });
  await worker.handleUsageEvents(post(view('home'), { cookie: `consent=granted; uv=${VISITOR_B}`, ip: 'evil; DROP' }), db, { now: day1, identify });
  out.consent = { status: ok.status, body: await ok.json(), rows: rowsOf(db), salts: tablesOf(db).includes('usage_salts') ? db.sql.prepare('SELECT COUNT(*) AS n FROM usage_salts').get().n : null };
}

// Retention: a write on day 32 clears the address on rows older than 30 days, nothing else.
{
  const db = fakeD1();
  await worker.handleUsageEvents(post(view('home'), { cookie: `consent=granted; uv=${VISITOR_A}` }), db, { now: day1, identify });
  await worker.handleUsageEvents(post(view('home'), { cookie: `consent=granted; uv=${VISITOR_A}` }), db, { now: day31, identify });
  await worker.handleUsageEvents(post(view('about'), { cookie: `consent=granted; uv=${VISITOR_B}`, country: 'IT' }), db, { now: day32, identify });
  out.retention = { rows: rowsOf(db) };
  // The summary counts visitor A, seen on two days, as returning; B is new.
  out.summary = await worker.usageSummary(db, 30, { now: day32 });
}

// purgeIps on its own, as an admin read runs it.
{
  const db = fakeD1();
  await worker.handleUsageEvents(post(view('home'), { cookie: `consent=granted; uv=${VISITOR_A}` }), db, { now: day1, identify: { ...identify, ipRetentionDays: 365 } });
  await worker.handleUsageEvents(post(view('home'), { cookie: `consent=granted; uv=${VISITOR_B}` }), db, { now: day31, identify: { ...identify, ipRetentionDays: 365 } });
  const before = rowsOf(db).map((r) => r.ip);
  await worker.purgeIps(db, 7, { now: day31 });
  let badDays = null;
  try { await worker.purgeIps(db, 0); } catch (err) { badDays = err.name; }
  out.purge = { before, after: rowsOf(db).map((r) => r.ip), badDays };
}

// Misconfigured identify: refused, nothing stored, its own log line.
{
  const db = fakeD1();
  logs.splice(0);
  const res = await worker.handleUsageEvents(post(view('home'), { cookie: 'consent=granted' }), db, { now: day1, identify: { ...identify, ipRetentionDays: 'thirty' } });
  out.misconfigured = { status: res.status, tables: tablesOf(db), logs: logs.splice(0).map((l) => l.event) };
}

// Site mode (no identify) still stores no address, even though the column now exists.
{
  const db = fakeD1();
  await worker.handleUsageEvents(post(view('home'), { cookie: `consent=granted; uv=${VISITOR_A}` }), db, { now: day1 });
  out.siteMode = { rows: rowsOf(db) };
  out.siteSummaryReturning = (await worker.usageSummary(db, 30, { now: day1 })).returning;
}

// A D1 database created before the ip column gains it in place.
{
  const sql = new DatabaseSync(':memory:');
  sql.exec('CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT NOT NULL, kind TEXT NOT NULL,'
    + ' view_id TEXT, control_id TEXT, device_class TEXT NOT NULL, os_class TEXT NOT NULL, country TEXT, visitor TEXT)');
  const db = fakeD1(sql);
  const res = await worker.handleUsageEvents(post(view('home'), { cookie: `consent=granted; uv=${VISITOR_A}` }), db, { now: day1, identify });
  out.migrated = { status: res.status, columns: sql.prepare('PRAGMA table_info(events)').all().map((r) => r.name), rows: rowsOf(db) };
}

process.stdout.write(JSON.stringify(out));
