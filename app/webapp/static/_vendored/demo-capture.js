/* Gallery legs for the capture components (rec-wave, mic-notice). A fixed level
 * source stands in for the mic, so the page never asks for one. */
import { attachRecWave } from './rec-wave/rec-wave.js';
import { attachMicNotice } from './mic-notice/mic-notice.js';

// rec-wave: a fixed level source stands in for the mic; `silenceMs: 1` reaches the silent verdict at once.
const demoSource = (loud, running = true) => ({
  running, connect() {}, close() {}, read: (n) => !running ? null : { rms: loud ? 0.1 : 0,
    levels: Array.from({ length: n }, (_, i) => loud ? Math.min(1, 0.25 + 0.7 * Math.abs(Math.sin(i * 0.9)) * (1 - Math.abs(i - n / 2) / n)) : 0) },
});
const wave = (id, source, extra) => attachRecWave(document.getElementById(id), null, { source, reducedMotion: false, ...extra });
wave('demoRecLiveHost', demoSource(true));
wave('demoRecSilentHost', demoSource(false), { silenceMs: 1 });
wave('demoRecReducedHost', demoSource(true), { reducedMotion: true });
wave('demoRecNoneHost', demoSource(false, false));

// mic-notice: a fixed level source and a stream that only names its input stand in for the mic.
const demoStream = (label) => ({ getAudioTracks: () => [{ label }] });
attachMicNotice(document.getElementById('demoMicLive'), demoStream('AirPods'), { source: demoSource(true) });
attachMicNotice(document.getElementById('demoMicSilent'), demoStream('AirPods'), { source: demoSource(false) });
attachMicNotice(document.getElementById('demoMicRemote'), demoStream('Remote Audio'), { source: demoSource(false) });
attachMicNotice(document.getElementById('demoMicNoLabel'), demoStream(''), { source: demoSource(true), timer: false });
