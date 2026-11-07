// Drives site-header.js under Node against stubbed browser globals; prints JSON for the pytest.
import { readFileSync } from 'node:fs';

const [modulePath] = process.argv.slice(2);
let run = 0;

// A page at `width` px whose :root carries `token` as --nav-breakpoint (null: the site sets nothing).
async function page({ width, token = null }) {
  const classes = new Set();
  const root = {
    classList: {
      toggle: (name, on) => (on ? classes.add(name) : classes.delete(name)),
      contains: (name) => classes.has(name),
    },
  };
  const header = { attrs: {}, classList: { toggle() {} }, setAttribute(k, v) { this.attrs[k] = v; } };
  const toggle = { attrs: {}, setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {}, focus() {} };
  const queries = [];
  const listeners = [];
  globalThis.document = {
    documentElement: root,
    addEventListener() {},
    querySelector: (sel) => (sel === '.site-header' ? header : sel === '.menu-toggle' ? toggle : null),
    querySelectorAll: () => [],
  };
  globalThis.getComputedStyle = () => ({ getPropertyValue: (name) => (name === '--nav-breakpoint' && token !== null ? token : '') });
  globalThis.window = {
    scrollY: 0,
    addEventListener() {},
    matchMedia: (query) => {
      const min = Number(/min-width: ([\d.]+)px/.exec(query)[1]);
      const media = { query, min, matches: width >= min, addEventListener: (_, fn) => listeners.push(fn) };
      queries.push(media);
      return media;
    },
  };
  // A data URL forces ES-module evaluation, fresh for every page, as <script type="module"> does.
  const source = readFileSync(modulePath, 'utf8') + `\n// run ${run += 1}`;
  await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
  return {
    header, toggle, queries,
    open: () => classes.has('menu-open'),
    openMenu: () => { classes.add('menu-open'); },
    resize: (to) => { for (const q of queries) q.matches = to >= q.min; listeners.forEach((fn) => fn()); },
  };
}

const out = {};
const state = (p) => ({ min: p.queries.map((q) => q.min), nav: p.header.attrs['data-nav'] ?? null });

out.defaultWide = state(await page({ width: 1300 }));
out.defaultPhone = state(await page({ width: 900 }));
out.raised = state(await page({ width: 1100, token: '1200px' }));
out.raisedWide = state(await page({ width: 1200, token: ' 1200px ' }));
out.belowFloor = state(await page({ width: 1100, token: '800px' }));
out.notPx = state(await page({ width: 1100, token: '75rem' }));
out.junk = state(await page({ width: 1100, token: 'wide' }));

// Growing past the breakpoint flips the mode and closes an open menu; shrinking back flips again and leaves it shut.
let p = await page({ width: 1100, token: '1200px' });
p.openMenu();
p.resize(1300);
out.grow = { nav: p.header.attrs['data-nav'], open: p.open(), expanded: p.toggle.attrs['aria-expanded'] };
p.resize(1100);
out.shrink = { nav: p.header.attrs['data-nav'], open: p.open() };

// Between 1024 and the raised breakpoint an open menu is not closed.
p = await page({ width: 900, token: '1200px' });
p.openMenu();
p.resize(1100);
out.betweenStaysOpen = { nav: p.header.attrs['data-nav'], open: p.open() };

console.log(JSON.stringify(out));
