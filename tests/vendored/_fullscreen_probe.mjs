// Loads the real vendored fullscreen.js under Node and prints, as JSON, what
// isEdge() says for a spread of user agents and what readFullscreen() reads from
// a stubbed store; tests/vendored/test_fullscreen_detection.py asserts on it.

import { pathToFileURL } from 'node:url';

const MODULE = process.argv[2];

const store = new Map();
globalThis.localStorage = {
  getItem(k) { return store.has(k) ? store.get(k) : null; },
  setItem(k, v) { store.set(k, String(v)); },
  removeItem(k) { store.delete(k); },
};

const { isEdge, readFullscreen } = await import(pathToFileURL(MODULE).href);

const AGENTS = JSON.parse(process.argv[3]);
const agents = {};
for (const [name, ua] of Object.entries(AGENTS)) agents[name] = isEdge(ua);

const stored = {};
stored.unset = readFullscreen('demo');
store.set('demo.fullscreen', '1');
stored.on = readFullscreen('demo');
stored.otherApp = readFullscreen('other');
store.set('demo.fullscreen', '0');
stored.zero = readFullscreen('demo');
globalThis.localStorage = { getItem() { throw new Error('blocked'); } };
stored.blocked = readFullscreen('demo');

console.log(JSON.stringify({ agents, stored }));
