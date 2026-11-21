// Drives the vendored page-foot restart sheet under Node with stubbed browser
// globals and prints what it decided as JSON; tests/vendored/test_restart_sheet.py
// asserts on it.

import { pathToFileURL } from 'node:url';

const MODULE = process.argv[2];

function element(tag) {
  const el = {
    tagName: tag.toUpperCase(),
    children: [],
    attributes: {},
    dataset: {},
    listeners: {},
    classes: [],
    hidden: false,
    disabled: false,
    open: false,
    value: '',
    className: '',
    textContent: '',
    innerHTML: '',
    type: '',
    classList: { add(c) { el.classes.push(c); } },
    setAttribute(k, v) { this.attributes[k] = String(v); },
    append(...kids) {
      this.children.push(...kids);
      if (this.tagName === 'SELECT' && !this.value && kids.length) this.value = kids[0].value;
    },
    addEventListener(type, fn) { this.listeners[type] = fn; },
    showModal() { this.open = true; },
    close() { this.open = false; },
  };
  return el;
}

const body = element('body');
body.appendChild = (el) => { body.children.push(el); return el; };
let readout = null;
Object.defineProperty(globalThis, 'document', {
  value: {
    body,
    createElement: element,
    getElementById: () => readout,
  },
  configurable: true,
});

const mod = await import(pathToFileURL(MODULE).href);
const { outcome, initRestartSheet, RESTART_TIMEOUT_MS, POLL_INTERVAL_MS } = mod;

const before = { git_sha: 'aaa1111', built_at: '2026-11-21T10:00:00' };
const fresh = { git_sha: 'aaa1111', built_at: '2026-11-21T10:01:00' };
const T = 90000;
const outcomes = {
  waiting: outcome(before, null, null, 'r1', 1000, T),
  restarted: outcome(before, fresh, { id: 'r1', state: 'ok' }, 'r1', 5000, T),
  back_record_running: outcome(before, fresh, { id: 'r1', state: 'running' }, 'r1', 5000, T),
  failed: outcome(before, before, { id: 'r1', state: 'failed', exit_code: 1 }, 'r1', 5000, T),
  runner_gone: outcome(before, null, { id: 'r1', state: 'unknown' }, 'r1', 5000, T),
  other_run_failed: outcome(before, null, { id: 'r0', state: 'failed' }, 'r1', 5000, T),
  never_back: outcome(before, null, null, 'r1', T, T),
  same_process_at_timeout: outcome(before, before, { id: 'r1', state: 'running' }, 'r1', T, T),
  back_unrecorded_at_timeout: outcome(before, fresh, null, 'r1', T, T),
  ok_but_same_process_at_timeout: outcome(before, before, { id: 'r1', state: 'ok' }, 'r1', T, T),
  no_before_ok: outcome(null, fresh, { id: 'r1', state: 'ok' }, 'r1', 5000, T),
};

// One scripted run: `versions` and `records` are served in order (the last
// repeats); `post` is the POST answer; returns what the page showed.
async function scenario({ targets, post, versions, records, taps = 1, getFails = false }) {
  readout = element('p');
  body.children = [];
  let clock = 0;
  let reloads = 0;
  let posted = null;
  let v = 0;
  let r = 0;
  const fetchJson = async (url) => {
    if (url === '/api/restart') {
      if (getFails) { const e = new Error('HTTP 404'); e.status = 404; throw e; }
      const last = records ? records[Math.min(r++, records.length - 1)] : null;
      return { targets, last };
    }
    const next = versions[Math.min(v++, versions.length - 1)];
    if (next === null) throw new Error('down');
    return next;
  };
  const offered = await initRestartSheet({
    readout,
    fetchJson,
    postJson: async (url, payload) => { posted = payload; return post; },
    sleep: async (ms) => { clock += ms; },
    now: () => clock,
    reload: () => { reloads += 1; },
  });
  if (!offered) return { offered, readoutAttrs: readout.attributes, sheets: body.children.length };
  const dialog = body.children[0];
  const card = dialog.children[0];
  const confirm = card.children[card.children.length - 1].children[0];
  const note = card.children.find((c) => c.className === 'restart-sheet-note');
  const log = card.children.find((c) => c.className === 'restart-sheet-log');
  readout.listeners.click();
  const labels = [confirm.textContent];
  const notes = [];
  for (let i = 0; i < taps; i += 1) {
    confirm.listeners.click();
    labels.push(confirm.textContent);
    notes.push(note.textContent);
  }
  for (let i = 0; i < 200 && confirm.disabled; i += 1) await new Promise((res) => setImmediate(res));
  return {
    offered,
    open: dialog.open,
    trackView: dialog.dataset.trackView,
    surface: dialog.dataset.surface,
    readoutAttrs: readout.attributes,
    readoutClasses: readout.classes,
    tracks: card.children.flatMap((c) => [c, ...c.children]).map((c) => c.dataset.track).filter(Boolean),
    labels,
    notes,
    note: note.textContent,
    tone: note.dataset.tone || null,
    log: log.hidden ? null : log.textContent,
    posted,
    reloads,
    elapsed: clock,
  };
}

const app = [{ id: 'app', label: 'Restart app', warning: '' }];
const risky = [...app, { id: 'worker', label: 'Restart worker', warning: 'Stops the running jobs.' }];
const accepted = { status: 202, body: { restart_id: 'r1', target: 'app' } };

const result = {
  constants: { timeout: RESTART_TIMEOUT_MS, poll: POLL_INTERVAL_MS },
  outcomes,
  no_targets: await scenario({ targets: [], post: accepted, versions: [before] }),
  no_route: await scenario({ targets: app, post: accepted, versions: [before], getFails: true }),
  restarted: await scenario({
    targets: app, post: accepted, versions: [before, null, fresh],
    records: [null, { id: 'r1', state: 'running' }, { id: 'r1', state: 'ok', exit_code: 0 }],
  }),
  failed: await scenario({
    targets: app, post: accepted, versions: [before],
    records: [null, { id: 'r1', state: 'failed', exit_code: 1, log_tail: ['ERROR: reclaim failed'] }],
  }),
  timed_out: await scenario({ targets: app, post: accepted, versions: [before, null], records: [null] }),
  refused: await scenario({ targets: app, post: { status: 401, body: null }, versions: [before] }),
  busy: await scenario({ targets: app, post: { status: 409, body: { restart_id: 'r0' } }, versions: [before] }),
  warned_once: await scenario({ targets: [risky[1]], post: accepted, versions: [before], records: [null], taps: 1 }),
  picker: await scenario({ targets: risky, post: accepted, versions: [before, fresh],
    records: [null, { id: 'r1', state: 'ok', exit_code: 0 }] }),
};

process.stdout.write(JSON.stringify(result));
