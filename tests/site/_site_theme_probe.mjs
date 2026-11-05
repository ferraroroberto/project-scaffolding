// Drives theme-boot.js and site-theme.js under Node against stubbed browser globals; prints JSON for the pytest.
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const [bootPath, modulePath] = process.argv.slice(2);
let run = 0;

function storage({ saved = null, blocked = false } = {}) {
  const writes = [];
  return {
    writes,
    getItem(key) {
      if (blocked) throw new Error('blocked');
      return key === 'theme' ? saved : null;
    },
    setItem(key, value) {
      if (blocked) throw new Error('blocked');
      writes.push([key, value]);
    },
  };
}

// The boot line runs as a plain script before anything else: all it may touch is <html> and storage.
function boot(store) {
  const root = { dataset: {} };
  let threw = false;
  try {
    runInNewContext(readFileSync(bootPath, 'utf8'), { localStorage: store, document: { documentElement: root } });
  } catch { threw = true; }
  return { theme: root.dataset.theme ?? null, threw };
}

// The module, loaded as the page loads it: `root` may already carry the boot script's choice.
async function page({ systemDark = false, theme, store = storage(), withButton = true } = {}) {
  const root = { dataset: theme ? { theme } : {} };
  const button = new EventTarget();
  button.attrs = {};
  button.setAttribute = (k, v) => { button.attrs[k] = v; };
  const media = new EventTarget();
  media.matches = systemDark;
  globalThis.document = {
    documentElement: root,
    querySelector: (sel) => (sel === '.theme-toggle' && withButton ? button : null),
  };
  globalThis.window = { matchMedia: (q) => (q === '(prefers-color-scheme: dark)' ? media : null) };
  globalThis.localStorage = store;
  // The file has no import or export, so Node would run it as CommonJS and cache it by path; a data URL
  // forces ES-module evaluation, as the browser's <script type="module"> does, fresh for every page.
  const source = readFileSync(modulePath, 'utf8') + `
// run ${run += 1}`;
  await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
  return {
    root, button, media, store,
    pressed: () => button.attrs['aria-pressed'] ?? null,
    click: () => button.dispatchEvent(new Event('click')),
    system: (dark) => { media.matches = dark; media.dispatchEvent(new Event('change')); },
  };
}

const out = {};

// The boot line.
out.boot = {
  dark: boot(storage({ saved: 'dark' })),
  light: boot(storage({ saved: 'light' })),
  none: boot(storage()),
  junk: boot(storage({ saved: 'sepia' })),
  blocked: boot(storage({ blocked: true })),
};

// System default: no saved choice, so the page leaves data-theme alone and the button mirrors the system.
let p = await page({ systemDark: true });
out.systemDark = { pressed: p.pressed(), theme: p.root.dataset.theme ?? null, writes: p.store.writes.length };
p = await page({ systemDark: false });
out.systemLight = { pressed: p.pressed(), theme: p.root.dataset.theme ?? null, writes: p.store.writes.length };

// The system setting changing under an unchosen page moves the button with it.
p.system(true);
out.systemChange = { pressed: p.pressed(), theme: p.root.dataset.theme ?? null };

// A press switches, saves and flips back.
p = await page({ systemDark: false });
p.click();
out.press = { theme: p.root.dataset.theme, pressed: p.pressed(), writes: [...p.store.writes] };
p.click();
out.pressAgain = { theme: p.root.dataset.theme, pressed: p.pressed(), writes: [...p.store.writes] };

// A press on a dark system switches to light, so the first press always goes the other way.
p = await page({ systemDark: true });
p.click();
out.pressOnDarkSystem = { theme: p.root.dataset.theme, pressed: p.pressed(), writes: [...p.store.writes] };

// A saved choice (already on <html> from the boot line) beats the system, and a system change does not move it.
p = await page({ systemDark: true, theme: 'light' });
out.savedLight = { pressed: p.pressed(), theme: p.root.dataset.theme, writes: p.store.writes.length };
p.system(true);
out.savedLightStays = { pressed: p.pressed(), theme: p.root.dataset.theme };

// Storage blocked: the press still switches this page.
p = await page({ systemDark: false, store: storage({ blocked: true }) });
p.click();
out.blockedPress = { theme: p.root.dataset.theme, pressed: p.pressed() };

// No switch in the markup: nothing happens and nothing throws.
p = await page({ systemDark: true, withButton: false });
out.noButton = { theme: p.root.dataset.theme ?? null, writes: p.store.writes.length };

console.log(JSON.stringify(out));
