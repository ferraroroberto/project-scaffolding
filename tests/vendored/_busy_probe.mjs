// Drives the vendored runBusy under Node with a minimal DOM and prints what
// happened as JSON; tests/vendored/test_busy.py asserts on it.

import { pathToFileURL } from 'node:url';

const MODULE = process.argv[2];

function element(tag) {
  const el = {
    tagName: tag.toUpperCase(),
    id: '',
    className: '',
    hidden: false,
    textContent: '',
    dataset: {},
    attributes: {},
    children: [],
    text: '',
    setAttribute(k, v) { this.attributes[k] = String(v); },
    getAttribute(k) { return k in this.attributes ? this.attributes[k] : null; },
    removeAttribute(k) { delete this.attributes[k]; },
    append(...kids) {
      for (const k of kids) {
        if (typeof k === 'string') this.text += k;
        else if (k.tagName === 'SPAN') this.text += k.text;
        this.children.push(k);
      }
    },
    appendChild(child) { this.append(child); return child; },
    replaceChildren(...kids) { this.children = []; this.text = ''; this.append(...kids); },
    addEventListener() {},
  };
  return el;
}

const body = element('body');
const byId = {};
Object.defineProperty(globalThis, 'document', {
  value: {
    body,
    createElement: (tag) => element(tag),
    createElementNS: (_ns, tag) => element(tag),
    getElementById: (id) => byId[id] || null,
  },
  configurable: true,
});
body.appendChild = (k) => { if (k.id) byId[k.id] = k; return k; };

const { runBusy } = await import(pathToFileURL(MODULE).href);

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const toast = () => {
  const el = byId.toast;
  return el ? { text: el.children[0] ? el.children[0].text : '', hidden: el.hidden, error: el.className.includes('error') } : null;
};

// 1. A second tap while the work is in flight is ignored; busy clears on success.
{
  const button = element('button');
  let calls = 0;
  let release;
  const work = () => { calls += 1; return new Promise((resolve) => { release = resolve; }); };
  const first = runBusy(button, work, { start: 'Refreshing', done: (v) => 'Got ' + v });
  const busyWhileRunning = button.getAttribute('aria-busy');
  const startToast = toast();
  const second = await runBusy(button, work, { start: 'Refreshing' });
  release(7);
  const result = await first;
  globalThis.__one = {
    calls,
    busyWhileRunning,
    startToast,
    second,
    result,
    busyAfter: button.getAttribute('aria-busy'),
    doneToast: toast(),
  };
}

// 2. An async rejection clears busy and toasts the error text.
{
  const button = element('button');
  const result = await runBusy(button, async () => { await tick(); throw new Error('timeout'); }, { start: 'Syncing', fail: 'Sync failed' });
  globalThis.__two = { ok: result.ok, busyAfter: button.getAttribute('aria-busy'), toast: toast() };
}

// 3. A synchronous throw is handled the same, and a later tap runs again.
{
  const button = element('button');
  const first = await runBusy(button, () => { throw new Error('boom'); });
  let ran = 0;
  const again = await runBusy(button, () => { ran += 1; return 'fine'; }, { done: 'Saved' });
  globalThis.__three = { firstOk: first.ok, firstToast: null, busyAfter: button.getAttribute('aria-busy'), again: again.ok, ran, toast: toast() };
  globalThis.__threeFirstText = first.error.message;
}

// 4. With a start toast and no done message, the start toast is dismissed.
{
  const button = element('button');
  await runBusy(button, async () => { await tick(); }, { start: 'Working' });
  globalThis.__four = { toast: toast() };
}

console.log(JSON.stringify({
  inflight: globalThis.__one,
  rejected: globalThis.__two,
  sync: globalThis.__three,
  dismissed: globalThis.__four,
}));
process.exit(0);
