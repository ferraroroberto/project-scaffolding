// Drives src/usage_log_worker.js under Node against an in-memory SQLite standing in for
// D1 (node:sqlite) and prints what it did as JSON; tests/test_usage_log_worker.py asserts
// on it, and compares its event validation with usage_log.py's on the same cases.

import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const worker = await import(pathToFileURL(process.argv[2]).href);
const cases = JSON.parse(readFileSync(process.argv[3], 'utf8'));

/** The slice of the D1 API the worker half uses, over node:sqlite. */
function fakeD1() {
  const sql = new DatabaseSync(':memory:');
  const statement = (text, args = []) => ({
    bind: (...bound) => statement(text, bound),
    run: async () => { sql.prepare(text).run(...args); return { success: true }; },
    first: async (column) => {
      const row = sql.prepare(text).get(...args);
      if (row === undefined) return null;
      return column ? row[column] : { ...row };
    },
    all: async () => ({ results: sql.prepare(text).all(...args).map((r) => ({ ...r })) }),
    apply: () => sql.prepare(text).run(...args),
  });
  return {
    sql,
    prepare: (text) => statement(text),
    batch: async (statements) => {
      sql.exec('BEGIN');
      try {
        const out = statements.map((s) => s.apply());
        sql.exec('COMMIT');
        return out;
      } catch (err) {
        sql.exec('ROLLBACK');
        throw err;
      }
    },
  };
}

function post(body, { ip = '203.0.113.9', ua = 'Probe/1.0', country = 'ES', method = 'POST' } = {}) {
  const req = new Request('https://site.example/api/usage/events', {
    method,
    headers: { 'cf-connecting-ip': ip, 'user-agent': ua, 'content-type': 'application/json' },
    body: method === 'POST' ? JSON.stringify(body) : undefined,
  });
  Object.defineProperty(req, 'cf', { value: { country } });
  return req;
}

const envelope = (events) => ({ session_id: 'probe-session-1', device_class: 'phone', os_class: 'ios', events });
const day1 = new Date('2026-11-01T10:00:00Z');
const day2 = new Date('2026-11-02T10:00:00Z');
const db = fakeD1();

const validated = cases.map((c) => worker.validateEvent(c));

const first = await worker.handleUsageEvents(post(envelope([
  { kind: 'session_start' },
  { kind: 'referrer', id: 'linkedin.com' },
  { kind: 'view', id: 'about' },
  { kind: 'tap', id: 'out:twitter.com', view: 'about', text: 'secret' },
  { kind: 'bogus' },
])), db, { now: day1 });
const sameDay = await worker.handleUsageEvents(post(envelope([{ kind: 'view', id: 'home' }])), db, { now: day1 });
const otherVisitor = await worker.handleUsageEvents(post(envelope([{ kind: 'view', id: 'home' }]), { ip: '198.51.100.7', country: 'IT' }), db, { now: day1 });
const nextDay = await worker.handleUsageEvents(post(envelope([{ kind: 'view', id: 'home' }])), db, { now: day2 });
const badEnvelope = await worker.handleUsageEvents(post({ session_id: 'x', events: [] }), db, { now: day2 });
const wrongMethod = await worker.handleUsageEvents(post(null, { method: 'GET' }), db, { now: day2 });

const rows = db.sql.prepare('SELECT ts, session_id, kind, view_id, control_id, device_class, os_class, country, visitor FROM events ORDER BY id').all().map((r) => ({ ...r }));
const salts = db.sql.prepare('SELECT day FROM usage_salts ORDER BY day').all().map((r) => r.day);
const summary = await worker.usageSummary(db, 30, { now: day2 });

console.log(JSON.stringify({
  validated,
  statuses: [first.status, sameDay.status, otherVisitor.status, nextDay.status, badEnvelope.status, wrongMethod.status],
  firstBody: await first.json(),
  rows,
  salts,
  summary,
}));
