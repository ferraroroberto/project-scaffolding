// Drives the vendored usage-log client's identified mode (`visitorCookie`, `stop()`) under
// Node with stubbed browser globals, a cookie jar and listener bookkeeping, and prints what
// it did as JSON; tests/usage_log/test_usage_log_identified.py asserts on it.

import { pathToFileURL } from 'node:url';

const sent = [];
const cookieWrites = [];
const jar = new Map();
const listeners = { added: [], removed: [] };

function define(name, value) {
  Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
}

function target(label) {
  return {
    addEventListener(type) { listeners.added.push(`${label}:${type}`); },
    removeEventListener(type) { listeners.removed.push(`${label}:${type}`); },
  };
}

define('window', { ...target('window'), matchMedia: () => ({ matches: false }), screen: { width: 1280, height: 800 } });
define('navigator', {
  userAgent: 'probe', maxTouchPoints: 0,
  sendBeacon: (url, blob) => { sent.push({ url, beacon: true, blob }); return true; },
});
const doc = { ...target('document'), visibilityState: 'visible', referrer: '' };
Object.defineProperty(doc, 'cookie', {
  get: () => Array.from(jar, ([k, v]) => `${k}=${v}`).join('; '),
  set: (line) => {
    cookieWrites.push(line);
    const [pair, ...attrs] = line.split(';').map((s) => s.trim());
    const [name, value] = pair.split('=');
    const maxAge = attrs.find((a) => a.startsWith('Max-Age='));
    if (maxAge && Number(maxAge.slice(8)) <= 0) jar.delete(name); else jar.set(name, value);
  },
});
define('document', doc);
define('location', { href: 'https://example.com/about', host: 'example.com', pathname: '/about', protocol: 'https:' });
define('fetch', (url, init) => { sent.push({ url, body: init.body }); return Promise.resolve({ ok: true }); });
console.warn = () => {};

const root = target('root');
const out = {};

const mod = await import(pathToFileURL(process.argv[2]).href);
out.beforeInit = { sends: sent.length, cookie: doc.cookie, writes: cookieWrites.length, listeners: listeners.added.length };

// First visit: the cookie is created with its attributes; the id never rides in a body.
const usage = mod.initUsageLog({ root, site: true, visitorCookie: 'uv' });
out.afterInit = { writes: cookieWrites.splice(0), value: jar.get('uv') };
usage.flush();
out.bodyCarriesId = sent.splice(0).some((s) => String(s.body).includes(jar.get('uv')));

// A later page load reuses the cookie and does not extend it.
const again = mod.initUsageLog({ root, site: true, visitorCookie: 'uv' });
out.secondInit = { writes: cookieWrites.splice(0), value: jar.get('uv') };
again.stop();
cookieWrites.splice(0);

// A malformed id is replaced.
jar.set('uv', 'tampered');
const fixed = mod.initUsageLog({ root, visitorCookie: 'uv' });
out.replaced = /^[0-9a-f]{32}$/.test(jar.get('uv') || '');

// stop(): queue dropped unsent, listeners detached, cookie deleted, later calls no-ops.
sent.splice(0);
listeners.removed.splice(0);
fixed.trackView('queued-before-stop');
fixed.stop();
fixed.track('after.stop');
fixed.trackView('after-stop');
fixed.flush();
out.stop = {
  sends: sent.length,
  removed: listeners.removed.splice(0).sort(),
  deleteWrite: cookieWrites.splice(0),
  cookie: doc.cookie,
};

// Plain http: no Secure attribute.
location.protocol = 'http:';
mod.initUsageLog({ root, visitorCookie: 'uv', visitorCookieDays: 30 }).flush();
out.http = cookieWrites.splice(0);
location.protocol = 'https:';
jar.clear();

// A cookie name outside the id pattern disables the logger: no cookie, no send.
sent.splice(0);
const bad = mod.initUsageLog({ root, visitorCookie: 'a b;c' });
bad.flush();
out.badName = { cookie: doc.cookie, sends: sent.length, hasStop: typeof bad.stop === 'function' };

// Without visitorCookie no cookie is read or written, and stop() deletes nothing.
cookieWrites.splice(0);
const plain = mod.initUsageLog({ root, site: true });
plain.flush();
plain.stop();
out.plain = { writes: cookieWrites.length, cookie: doc.cookie };

process.stdout.write(JSON.stringify(out));
