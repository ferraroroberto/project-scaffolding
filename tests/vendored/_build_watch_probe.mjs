// Drives the vendored build-watch module under Node with stubbed browser
// globals and prints what it decided as JSON; tests/vendored/test_build_watch.py
// asserts on it.

import { pathToFileURL } from 'node:url';

const MODULE = process.argv[2];

function define(name, value) {
  Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
}

// A minimal element: enough for the prompt the module builds.
function element(tag) {
  const el = {
    tagName: tag.toUpperCase(),
    children: [],
    attributes: {},
    dataset: {},
    listeners: {},
    hidden: false,
    id: '',
    className: '',
    textContent: '',
    innerHTML: '',
    type: '',
    title: '',
    setAttribute(k, v) { this.attributes[k] = String(v); },
    append(...kids) { this.children.push(...kids); },
    addEventListener(type, fn) { this.listeners[type] = fn; },
  };
  return el;
}

let stampedAssets = [];
let entryScript = null;
const docListeners = {};
const body = element('body');
body.appendChild = (el) => { body.children.push(el); return el; };

define('document', {
  hidden: false,
  body,
  createElement: element,
  querySelector: () => entryScript,
  querySelectorAll: () => stampedAssets,
  addEventListener(type, fn) { docListeners[type] = fn; },
});
define('location', { reload() { reloads += 1; } });
let reloads = 0;
// The watch polls through the vendored helper, which schedules with
// window.setTimeout; a raw setInterval would be a regression, so it is counted.
let setIntervalCalls = 0;
define('setInterval', () => { setIntervalCalls += 1; return 0; });
let timers = [];
let timerIds = 0;
define('window', {
  setTimeout(fn, ms) { timerIds += 1; timers.push({ id: timerIds, fn, ms }); return timerIds; },
  clearTimeout(id) { timers = timers.filter((t) => t.id !== id); },
});
// A fake clock: the throttle reads Date.now(), and the poll's tick is fired by
// advancing it one poll interval, as the real timer would.
let clockMs = 1_000_000;
Date.now = () => clockMs;
async function fireTick() {
  clockMs += 5 * 60 * 1000;
  const armed = timers[timers.length - 1];
  if (!armed) throw new Error('no poll tick is armed');
  await armed.fn();
  await tick(); await tick();
}

let reads = [];
let nextResponse = { ok: true, status: 200, body: { asset_hash: 'bbb' } };
define('fetch', (url, init) => {
  reads.push({ url, init });
  const r = nextResponse;
  if (r instanceof Error) return Promise.reject(r);
  return Promise.resolve({ ok: r.ok, status: r.status, json: () => Promise.resolve(r.body) });
});

const mod = await import(pathToFileURL(MODULE).href);
const out = {};

out.constants = { throttle: mod.CHECK_THROTTLE_MS, interval: mod.CHECK_INTERVAL_MS };

out.verdict = {
  stale: mod.verdict('aaa', 'bbb'),
  current: mod.verdict('aaa', 'aaa'),
  unknown: [null, undefined, '', 0, 'missing'].flatMap((u) => [mod.verdict('aaa', u), mod.verdict(u, 'bbb')]),
};

out.shouldCheck = [
  mod.shouldCheck(1000, null, 60000),
  mod.shouldCheck(1000, undefined, 60000),
  mod.shouldCheck(30000, 1000, 60000),
  mod.shouldCheck(61000, 1000, 60000),
  mod.shouldCheck(60999, 1000, 60000),
];

out.stampOf = [
  mod.stampOf('https://h/static/app.js?v=abc123'),
  mod.stampOf('/static/styles/app.css?v=abc123'),
  mod.stampOf('https://h/static/app.js'),
  mod.stampOf('not a url at all ::'),
  mod.stampOf(''),
  mod.stampOf(null),
];

const tick = () => new Promise((r) => setTimeout(r, 0));
async function visible() {
  docListeners.visibilitychange();
  await tick(); await tick();
}

function prompt() {
  return body.children.find((c) => c.id === 'buildPrompt') || null;
}

// The module itself is loaded from a file URL with no ?v=, so the boot stamp
// falls back to the stamped assets the page linked.
stampedAssets = [];
out.noStamp = { started: mod.initBuildWatch(), reads: reads.length };

stampedAssets = [{ src: '/static/main.js?v=aaa' }, { href: '/static/app.css?v=aaa' }];
const started = mod.initBuildWatch({ endpoint: '/api/version' });
out.started = started;
out.intervalMs = timers.map((t) => t.ms);

// Stale: both known and differ -> the prompt shows.
nextResponse = { ok: true, status: 200, body: { asset_hash: 'bbb' } };
await visible();
const p = prompt();
out.stale = {
  shown: !!p && p.hidden === false,
  className: p && p.className,
  role: p && p.attributes.role,
  live: p && p.attributes['aria-live'],
  texts: p && p.children.map((c) => c.textContent),
  tracks: p && p.children.map((c) => c.dataset.track || null),
  surface: p && p.dataset.surface,
  read: reads[reads.length - 1],
};

// A visibility flick inside the throttle window does not re-read.
const before = reads.length;
await visible();
out.throttled = reads.length === before;

// Dismiss: the prompt stays down for the same live build...
p.children[2].listeners.click();
out.dismissedHidden = p.hidden;
await fireTick();
out.dismissStaysDown = p.hidden;

// ...and comes back when the server moves to yet another build.
nextResponse = { ok: true, status: 200, body: { asset_hash: 'ccc' } };
await fireTick();
out.newBuildReshows = p.hidden === false;

// Reload is only ever the user's tap.
out.reloadsBeforeTap = reloads;
p.children[1].listeners.click();
out.reloadsAfterTap = reloads;

// Back on the boot build -> the prompt hides.
nextResponse = { ok: true, status: 200, body: { asset_hash: 'aaa' } };
await fireTick();
out.currentHides = p.hidden;

// Unknown is never stale: on a fresh page, a 401, an empty hash, a missing
// field or a failed read builds no prompt at all.
for (const [name, resp] of [
  ['unauthorized', { ok: false, status: 401, body: { detail: 'no' } }],
  ['emptyHash', { ok: true, status: 200, body: { asset_hash: '' } }],
  ['noField', { ok: true, status: 200, body: { git_sha: 'x' } }],
  ['network', new Error('offline')],
]) {
  body.children = [];
  timers = [];
  nextResponse = resp;
  mod.initBuildWatch();
  await fireTick();
  out[name] = prompt() === null;
}

// A caller's own reader (an app that adds auth headers) replaces fetch.
const own = [];
reads = [];
timers = [];
const second = mod.initBuildWatch({
  endpoint: '/x/version',
  fetchJson: (url) => { own.push(url); return Promise.resolve({ asset_hash: 'zzz' }); },
});
await fireTick();
out.ownReader = { started: second, urls: own, fetchCalls: reads.length };

// A per-file-hash app reports its entry module's stamp as asset_hash, so the
// entry module script's ?v= is the boot build, not a stylesheet's.
entryScript = { src: '/static/app.js?v=eee' };
stampedAssets = [{ href: '/static/app.css?v=sss' }, { src: '/static/app.js?v=eee' }];
out.entry = {};
for (const live of ['eee', 'sss']) {
  body.children = [];
  timers = [];
  nextResponse = { ok: true, status: 200, body: { asset_hash: live } };
  mod.initBuildWatch();
  await fireTick();
  const shown = prompt();
  out.entry[live] = !!shown && shown.hidden === false;
}

// A hidden page arms no tick; the raw setInterval was never used.
timers = [];
mod.initBuildWatch();
const armedWhileVisible = timers.length;
document.hidden = true;
docListeners.visibilitychange();
out.hidden = { armedWhileVisible, armedAfterHide: timers.length };
document.hidden = false;
out.setIntervalCalls = setIntervalCalls;

process.stdout.write(JSON.stringify(out));
