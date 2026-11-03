// Drives site-consent.js under Node against stubbed browser globals; prints JSON for the pytest.
import { pathToFileURL } from 'node:url';

const modulePath = process.argv[2];
let run = 0;
let network = 0;

function element() {
  const target = new EventTarget();
  const el = {
    hidden: true, dataset: {}, focused: 0, offsetHeight: 64, children: {},
    addEventListener: (...a) => target.addEventListener(...a),
    dispatch: (type, init = {}) => {
      const e = new Event(type, { cancelable: true });
      Object.assign(e, init);
      target.dispatchEvent(e);
      return e;
    },
    focus() { el.focused += 1; },
    querySelector: (sel) => el.children[sel] ?? null,
  };
  return el;
}

// One page: a bar (accept/reject buttons), an opener link, a cookie jar, a document event bus.
async function page({ cookie = '', bar = {}, withBar = true, protocol = 'https:' } = {}) {
  const jar = new Map();
  for (const part of cookie.split(';').filter(Boolean)) jar.set(part.split('=')[0].trim(), part.trim());
  const writes = [];
  const events = [];
  const root = { style: { props: {}, setProperty(k, v) { this.props[k] = v; }, removeProperty(k) { delete this.props[k]; } } };
  const barEl = element();
  const accept = element();
  const reject = element();
  barEl.dataset = { ...bar };
  barEl.children = { '[data-consent-accept]': accept, '[data-consent-reject]': reject };
  const opener = element();
  const bus = new EventTarget();
  globalThis.document = {
    documentElement: root,
    get cookie() { return [...jar.values()].join('; '); },
    set cookie(v) {
      writes.push(v);
      const [pair, ...attrs] = v.split(';');
      const [k] = pair.split('=');
      if (attrs.some((a) => a.trim() === 'Max-Age=0')) jar.delete(k); else jar.set(k, pair);
    },
    querySelector: (sel) => (sel === '[data-consent]' && withBar ? barEl : null),
    querySelectorAll: (sel) => (sel === '[data-consent-open]' ? [opener] : []),
    addEventListener: (...a) => bus.addEventListener(...a),
    dispatchEvent: (e) => bus.dispatchEvent(e),
  };
  globalThis.location = { protocol };
  document.addEventListener('consent:change', (e) => events.push(e.detail));
  const mod = await import(`${pathToFileURL(modulePath).href}?run=${run += 1}`);
  return {
    mod, bar: barEl, accept, reject, opener, writes, events, root, jar,
    shown: () => !barEl.hidden,
    click: (el) => el.dispatch('click'),
    cookie: () => document.cookie,
  };
}

globalThis.fetch = () => { network += 1; throw new Error('network'); };
globalThis.XMLHttpRequest = function () { network += 1; throw new Error('network'); };
Object.defineProperty(globalThis, 'navigator', { value: { sendBeacon() { network += 1; return false; } }, configurable: true });

const out = {};

// First visit: shown, nothing written, no event, focus not taken.
let p = await page();
out.first = { shown: p.shown(), writes: p.writes.length, events: p.events.length, focused: p.bar.focused, reserve: p.root.style.props['--consent-h'], consent: p.mod.getConsent() };

// Accept.
p.click(p.accept);
out.accept = { shown: p.shown(), writes: p.writes, events: p.events, consent: p.mod.getConsent(), reserve: p.root.style.props['--consent-h'] ?? null };

// Next load with the stored choice: bar suppressed, no event, no write.
let next = await page({ cookie: p.cookie() });
out.afterAccept = { shown: next.shown(), writes: next.writes.length, events: next.events.length, consent: next.mod.getConsent() };

// Reopen from the link, then withdraw with Reject: one click, event {granted:false}.
let reopen = next.opener.dispatch('click');
out.reopen = { shown: next.shown(), prevented: reopen.defaultPrevented, barFocused: next.bar.focused };
next.click(next.reject);
out.withdraw = { shown: next.shown(), events: next.events, writes: next.writes, openerFocused: next.opener.focused, consent: next.mod.getConsent() };

// Reject on a first visit.
p = await page();
p.click(p.reject);
out.reject = { shown: p.shown(), writes: p.writes, events: p.events, consent: p.mod.getConsent() };

// The same choice again from a reopened bar is stored again but announced once only.
const again = await page({ cookie: p.cookie() });
again.opener.dispatch('click');
again.click(again.reject);
out.sameChoice = { writes: again.writes.length, events: again.events.length, shown: again.shown() };

// Escape closes a reopened bar and leaves the stored choice alone.
const esc = await page({ cookie: p.cookie() });
esc.opener.dispatch('click');
esc.bar.dispatch('keydown', { key: 'Escape' });
out.escape = { shown: esc.shown(), writes: esc.writes.length, events: esc.events.length };

// Escape on the first-visit bar does nothing: a choice is still owed.
const firstEsc = await page();
firstEsc.bar.dispatch('keydown', { key: 'Escape' });
out.firstEscape = { shown: firstEsc.shown() };

// Custom cookie name and lifetime; plain http omits Secure.
const custom = await page({ bar: { consentCookie: 'cc', consentDays: '30' }, protocol: 'http:' });
custom.click(custom.accept);
out.custom = { writes: custom.writes };

// A malformed stored value counts as no choice.
const junk = await page({ cookie: 'consent=maybe' });
out.junk = { shown: junk.shown(), consent: junk.mod.getConsent() };

// Another cookie with the name as a suffix is not the choice.
const other = await page({ cookie: 'xconsent=granted' });
out.otherCookie = { shown: other.shown(), consent: other.mod.getConsent() };

// A bad cookie name or lifetime keeps the bar hidden and never stores.
const warns = [];
console.warn = (m) => warns.push(String(m));
const bad = await page({ bar: { consentCookie: 'a b;c' } });
const badDays = await page({ bar: { consentDays: '0' } });
out.invalid = { shown: bad.shown(), daysShown: badDays.shown(), consent: bad.mod.getConsent(), warns: warns.length };

// No bar in the markup: the module does nothing.
const none = await page({ withBar: false });
out.noBar = { consent: none.mod.getConsent(), writes: none.writes.length };

out.network = network;
process.stdout.write(JSON.stringify(out));
