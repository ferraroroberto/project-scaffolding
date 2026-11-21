// Drives the vendored toast's action button under Node with a minimal DOM and
// prints what stayed on screen as JSON; tests/vendored/test_toast_action.py
// asserts on it.

import { pathToFileURL } from 'node:url';

const MODULE = process.argv[2];

// A node is "connected" while it is a descendant of the document body.
function element(tag) {
  const el = {
    tagName: tag.toUpperCase(),
    id: '',
    className: '',
    hidden: false,
    disabled: false,
    type: '',
    textContent: '',
    dataset: {},
    attributes: {},
    listeners: {},
    children: [],
    parent: null,
    get isConnected() {
      let n = el;
      while (n.parent) n = n.parent;
      return n === body;
    },
    setAttribute(k, v) { this.attributes[k] = String(v); },
    appendChild(child) { return this.append(child); },
    append(...kids) {
      for (const k of kids) {
        if (typeof k === 'string') continue;
        k.parent = el;
        el.children.push(k);
      }
    },
    replaceChildren(...kids) {
      for (const c of el.children) c.parent = null;
      el.children = [];
      el.append(...kids);
    },
    addEventListener(type, fn) { el.listeners[type] = fn; },
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
const realAppend = body.append.bind(body);
body.append = (...kids) => { for (const k of kids) if (k.id) byId[k.id] = k; realAppend(...kids); };
body.appendChild = (k) => { body.append(k); return k; };

const { showToast } = await import(pathToFileURL(MODULE).href);

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

async function tap(toast) {
  const button = toast.children.find((c) => c.tagName === 'BUTTON');
  button.listeners.click();
  await tick();
  await tick();
}

const shown = (toast) => ({ hidden: toast.hidden, buttons: toast.children.filter((c) => c.tagName === 'BUTTON').length });

// 1. A plain tap runs the action, then hides the toast.
let ran = 0;
let toast = showToast('Deleted', undefined, { action: { label: 'Undo', onClick: () => { ran += 1; } } });
await tap(toast);
const plain = { ran, ...shown(toast) };

// 2. The action shows its own confirmation: that toast stays up.
toast = showToast('Deleted', undefined, {
  ms: 0,
  action: { label: 'Undo', onClick: () => { showToast('Restored', undefined, { ms: 0 }); } },
});
await tap(toast);
const confirmed = shown(toast);

// 3. An async action that shows its toast while it runs.
toast = showToast('Deleted', undefined, {
  ms: 0,
  action: {
    label: 'Undo',
    onClick: async () => { await tick(); showToast('Restored', undefined, { ms: 0 }); },
  },
});
await tap(toast);
const asyncConfirmed = shown(toast);

// 4. A rejected action still hides its own toast.
toast = showToast('Deleted', undefined, { ms: 0, action: { label: 'Undo', onClick: () => Promise.reject(new Error('x')) } });
process.on('unhandledRejection', () => {});
await tap(toast);
const rejected = shown(toast);

console.log(JSON.stringify({ plain, confirmed, asyncConfirmed, rejected }));
process.exit(0);
