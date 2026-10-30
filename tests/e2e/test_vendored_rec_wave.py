"""Render and lifecycle harness for the vendored `rec-wave` component (#507).

Two halves, both in a real browser over the `demo.html` gallery:

* the gallery's five fixed-level legs (idle, live, silent mic, reduced motion,
  no Web Audio) are asserted on their rendered state and computed styles, in
  both themes;
* the lifecycle (starts on a stream, stops and releases, silent verdict and its
  recovery, a shared source left open, no-AudioContext fallback) runs the real
  module against a fake `AudioContext` whose level the test sets, because
  headless Chromium has no microphone.

The silent verdict is driven with a short `silenceMs` rather than a faked
clock, so each test waits tens of milliseconds, not the real 1.5 s.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style

# A stand-in for the page's AudioContext: counts what the component creates and
# closes, and feeds the analyser a sine whose amplitude the test sets.
_FAKE_AUDIO = """
window.__fake = { level: 0.1, created: 0, closed: 0, resumed: 0, connected: 0, state: 'running' };
window.AudioContext = class {
  constructor() { __fake.created += 1; this.state = __fake.state; }
  resume() { __fake.resumed += 1; return Promise.resolve(); }
  close() { __fake.closed += 1; return Promise.resolve(); }
  createAnalyser() {
    return {
      fftSize: 0,
      getFloatTimeDomainData(buf) {
        for (let i = 0; i < buf.length; i += 1) buf[i] = __fake.level * Math.sin(i / 3);
      },
    };
  }
  createMediaStreamSource() { return { connect() { __fake.connected += 1; } }; }
};
window.__host = document.createElement('button');
window.__host.innerHTML = '<span id="glyph">mic</span>';
document.body.appendChild(window.__host);
window.__glyph = window.__host.firstChild;
"""

_ATTACH = """
async (opts) => {
  const { attachRecWave } = await import('./rec-wave/rec-wave.js');
  window.__events = [];
  window.__stop = attachRecWave(window.__host, {}, {
    ...opts,
    onSilent: () => window.__events.push('silent'),
    onSignal: () => window.__events.push('signal'),
  });
}
"""


def _fake(page: Page) -> Page:
    page.evaluate(_FAKE_AUDIO)
    return page


def _state(page: Page) -> str | None:
    return page.evaluate("() => window.__host.dataset.recWaveState ?? null")


def _glyph_display(page: Page) -> str:
    return page.evaluate("() => getComputedStyle(window.__glyph).display")


# ------------------------------------------------------------------ gallery


def test_gallery_legs_render_their_states(gallery: Page) -> None:
    """Idle shows the glyph only; live, silent, reduced and unmeasured set their state."""
    expect(gallery.locator("#demoRecIdle .rec-wave")).to_have_count(0)
    states = {
        "#demoRecLiveHost": "live",
        "#demoRecSilentHost": "silent",
        "#demoRecReducedHost": "live",
        "#demoRecNoneHost": "unmeasured",
    }
    for host, want in states.items():
        gallery.wait_for_function(
            "([h, s]) => document.querySelector(h).dataset.recWaveState === s", arg=[host, want]
        )
    # The wave replaces the glyph while it is on.
    assert _style(gallery, "#demoRecLiveHost svg", "display") == "none"
    assert gallery.locator("#demoRecLiveHost .rec-wave-bars > i").count() == 24
    assert gallery.locator("#demoRecReducedHost .rec-wave-meter > i").count() == 1
    assert gallery.locator("#demoRecReducedHost .rec-wave-bars").count() == 0
    # Unmeasured is the timer alone: never a flat strip that reads as a silent mic.
    assert _style(gallery, "#demoRecNoneHost .rec-wave-bars", "display") == "none"
    assert gallery.locator("#demoRecNoneHost .rec-wave-time").is_visible()
    assert gallery.locator("#demoRecNoneHost .rec-wave-time").inner_text() == "0:00"


def test_gallery_live_bars_move_and_silent_bars_are_flat_and_dimmed(gallery: Page) -> None:
    gallery.wait_for_function(
        "() => document.querySelector('#demoRecSilentHost').dataset.recWaveState === 'silent'"
    )
    live = gallery.eval_on_selector_all(
        "#demoRecLiveHost .rec-wave-bars > i", "els => els.map(e => e.style.transform)"
    )
    flat = gallery.eval_on_selector_all(
        "#demoRecSilentHost .rec-wave-bars > i", "els => els.map(e => e.style.transform)"
    )
    assert len(set(live)) > 4, live
    assert set(flat) == {"scaleY(0.08)"}, flat
    # The dimming eases in over 0.15 s, so wait for its end value.
    gallery.wait_for_function(
        "() => getComputedStyle(document.querySelector('#demoRecSilentHost .rec-wave-bars')).opacity === '0.4'"
    )
    assert _style(gallery, "#demoRecLiveHost .rec-wave-bars", "opacity") == "1"


def test_gallery_strip_takes_the_host_text_color_in_both_themes(gallery: Page) -> None:
    for theme in ("light", "dark"):
        _set_theme(gallery, theme)
        button_color = _style(gallery, "#demoRecLive", "color")
        assert _style(gallery, "#demoRecLiveHost .rec-wave-bars > i", "backgroundColor") == button_color
        assert _style(gallery, "#demoRecLiveHost .rec-wave-time", "color") == button_color


def test_reduced_motion_meter_has_no_transition(gallery: Page) -> None:
    assert _style(gallery, "#demoRecReducedHost .rec-wave-meter", "overflow") == "hidden"
    gallery.emulate_media(reduced_motion="reduce")
    assert _style(gallery, "#demoRecReducedHost .rec-wave-meter", "transitionDuration") == "0s"
    assert _style(gallery, "#demoRecLiveHost .rec-wave-bars", "transitionDuration") == "0s"


# ---------------------------------------------------------------- lifecycle


def test_starts_on_a_stream_and_stop_releases_the_context(gallery: Page) -> None:
    _fake(gallery).evaluate(_ATTACH, {"reducedMotion": False})
    fake = gallery.evaluate("() => ({ ...window.__fake })")
    assert (fake["created"], fake["connected"], fake["resumed"]) == (1, 1, 1)
    assert _state(gallery) == "live"
    assert _glyph_display(gallery) == "none"
    bars = gallery.eval_on_selector_all("#glyph + .rec-wave .rec-wave-bars > i", "els => els.length")
    assert bars == 24

    gallery.evaluate("() => { window.__stop(); window.__stop(); }")
    assert gallery.evaluate("() => window.__fake.closed") == 1  # closed once, not twice
    assert _state(gallery) is None
    assert _glyph_display(gallery) != "none"
    assert gallery.locator(".rec-wave").count() == 4  # only the gallery's own legs remain


def test_quiet_input_goes_silent_then_signal_clears_it(gallery: Page) -> None:
    _fake(gallery)
    gallery.evaluate("() => { window.__fake.level = 0; }")
    gallery.evaluate(_ATTACH, {"reducedMotion": False, "silenceMs": 150})
    gallery.wait_for_function("() => window.__host.dataset.recWaveState === 'silent'")
    assert gallery.evaluate("() => window.__events") == ["silent"]

    gallery.evaluate("() => { window.__fake.level = 0.2; }")
    gallery.wait_for_function("() => window.__host.dataset.recWaveState === 'live'")
    assert gallery.evaluate("() => window.__events") == ["silent", "signal"]
    gallery.evaluate("() => window.__stop()")


def test_a_signal_is_announced_once_not_every_tick(gallery: Page) -> None:
    _fake(gallery).evaluate(_ATTACH, {"reducedMotion": False})
    gallery.wait_for_timeout(300)
    assert gallery.evaluate("() => window.__events") == ["signal"]
    gallery.evaluate("() => window.__stop()")


def test_a_shared_source_stays_open_after_stop(gallery: Page) -> None:
    _fake(gallery).evaluate(
        """async () => {
          const { attachRecWave, createLevelSource } = await import('./rec-wave/rec-wave.js');
          window.__source = createLevelSource();
          window.__source.connect({});
          window.__stop = attachRecWave(window.__host, {}, { source: window.__source });
        }"""
    )
    assert gallery.evaluate("() => window.__fake.created") == 1  # one context for the take
    gallery.evaluate("() => window.__stop()")
    assert gallery.evaluate("() => window.__fake.closed") == 0
    gallery.evaluate("() => window.__source.close()")
    assert gallery.evaluate("() => window.__fake.closed") == 1


def test_no_audio_context_falls_back_to_the_timer(gallery: Page) -> None:
    gallery.evaluate(
        "() => { window.AudioContext = undefined; window.webkitAudioContext = undefined;"
        " window.__host = document.createElement('button'); document.body.appendChild(window.__host); }"
    )
    gallery.evaluate(_ATTACH, {"reducedMotion": False})
    assert _state(gallery) == "unmeasured"
    time_el = gallery.locator("button > .rec-wave .rec-wave-time")
    expect(time_el).to_have_text("0:00")
    expect(time_el).to_have_text("0:01", timeout=3000)
    gallery.evaluate("() => window.__stop()")


def test_a_suspended_context_is_unmeasured_not_silent(gallery: Page) -> None:
    _fake(gallery).evaluate("() => { window.__fake.state = 'suspended'; }")
    gallery.evaluate(_ATTACH, {"reducedMotion": False, "silenceMs": 50})
    gallery.wait_for_timeout(300)
    assert _state(gallery) == "unmeasured"
    assert gallery.evaluate("() => window.__events") == []
    gallery.evaluate("() => window.__stop()")


def test_the_media_query_picks_the_meter_when_no_option_is_given(gallery: Page) -> None:
    gallery.emulate_media(reduced_motion="reduce")
    _fake(gallery).evaluate(_ATTACH, {})
    assert gallery.locator("#glyph + .rec-wave[data-motion='reduced'] .rec-wave-meter").count() == 1
    gallery.evaluate("() => window.__stop()")


def test_reduced_motion_option_draws_one_meter(gallery: Page) -> None:
    _fake(gallery).evaluate(_ATTACH, {"reducedMotion": True})
    assert gallery.eval_on_selector_all("#glyph + .rec-wave .rec-wave-bars", "els => els.length") == 0
    meter = gallery.locator("#glyph + .rec-wave .rec-wave-meter > i")
    expect(meter).to_have_count(1)
    gallery.wait_for_function(
        "() => { const t = document.querySelector('#glyph + .rec-wave .rec-wave-meter > i').style.transform;"
        " return t.startsWith('scaleX(') && t !== 'scaleX(0)'; }"
    )
    gallery.evaluate("() => window.__stop()")
