// Drives the vendored usage-log client under Node with stubbed browser globals
// and prints what it sent as JSON; tests/test_usage_log_client.py asserts on it.

import { pathToFileURL } from 'node:url';

const sent = [];
const handlers = {};

function define(name, value) {
  Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
}

define('window', {
  matchMedia: () => ({ matches: false }),
  screen: { width: 1280, height: 800 },
  addEventListener() {},
});
define('navigator', { userAgent: 'probe', maxTouchPoints: 0 });
define('document', {
  visibilityState: 'visible',
  addEventListener() {},
});
define('fetch', (url, init) => {
  sent.push({ url, body: JSON.parse(init.body) });
  return Promise.resolve({ ok: true });
});
console.warn = () => {};

const root = {
  addEventListener(type, handler) { handlers[type] = handler; },
};

function click(id) {
  handlers.click({
    target: { closest: () => ({ getAttribute: () => id }) },
  });
}

function drain(usage) {
  usage.flush();
  return sent.splice(0).flatMap((s) => s.body.events).filter((e) => e.kind === 'tap');
}

const { initUsageLog } = await import(pathToFileURL(process.argv[2]).href);

const usage = initUsageLog({ root });
usage.trackView('board');

usage.track('some.id');
const tracked = drain(usage);

click('some.id');
const clicked = drain(usage);

for (const bad of ['has space', 'a/b', '', 'x'.repeat(65), '-lead', 42, null, undefined, {}]) {
  usage.track(bad);
}
const invalid = drain(usage);

const early = initUsageLog({ root });
early.track('before.view');
const beforeView = drain(early);

const disabled = initUsageLog({ endpoint: 'https://example.invalid/events' });
disabled.track('some.id');
disabled.trackView('board');
disabled.flush();

const disabledSends = sent.length;

// Public-site mode (`site: true`): page view and referrer on load, followed links as taps.
define('location', { href: 'https://example.com/about', host: 'example.com', pathname: '/about' });
document.referrer = 'https://www.linkedin.com/feed/';
function all(usage) {
  usage.flush();
  return sent.splice(0).flatMap((s) => s.body.events);
}
function follow(href) {
  handlers.click({
    target: { closest: (sel) => (sel === 'a[href]' ? { getAttribute: () => href } : null) },
  });
}
const site = initUsageLog({ root, site: true });
const siteLoad = all(site);
for (const href of ['/inspiring-conversations/sara?x=1', 'https://twitter.com/x', 'mailto:a@b.c', '#top', 'javascript:void(0)']) {
  follow(href);
}
const siteLinks = all(site);

document.referrer = 'https://example.com/';
const sameHost = all(initUsageLog({ root, site: true }));

document.referrer = 'https://www.linkedin.com/feed/';
const plain = initUsageLog({ root });
follow('https://twitter.com/x');
const plainEvents = all(plain);

const { pageId, hostId, linkId } = await import(pathToFileURL(process.argv[2]).href);
const here = { href: 'https://example.com/about', host: 'example.com', pathname: '/about' };
const ids = {
  pages: ['/', '/about/', '/a/B c.html', '/' + 'x'.repeat(80)].map(pageId),
  hosts: ['www.Google.com:443', 'bad host', ''].map(hostId),
  links: ['/about#jump', '/contact', 'HTTP://WWW.Example.org/a', 'ftp://x.y'].map((h) => linkId(h, here)),
};

console.log(JSON.stringify({
  tracked, clicked, invalid, beforeView,
  disabledHasTrack: typeof disabled.track === 'function',
  disabledSends,
  siteLoad, siteLinks, sameHost, plainEvents, ids,
}));
