// The gallery's runBusy card: the work settles only when Finish or Fail is
// tapped, so the harness can read the busy button and its toasts without racing
// a timer. Every call that actually runs is counted, to show a second tap in
// flight runs nothing. Loaded as a module beside the gallery's own script.
import { runBusy } from './button/busy.js';

let settle = null;
document.getElementById('demoBusyRun').addEventListener('click', (e) => {
  runBusy(e.currentTarget, () => {
    const calls = document.getElementById('demoBusyCalls');
    calls.textContent = String(Number(calls.textContent) + 1);
    return new Promise((resolve, reject) => { settle = { resolve, reject }; });
  }, { start: 'Refreshing', done: 'Refreshed', fail: 'Refresh failed' });
});
document.getElementById('demoBusyFinish').addEventListener('click', () => {
  if (settle) settle.resolve('ok');
});
document.getElementById('demoBusyFail').addEventListener('click', () => {
  if (settle) settle.reject(new Error('timed out'));
});
