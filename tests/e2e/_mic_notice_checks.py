"""Checks for the vendored `mic-notice` component, run as cases of `test_vendored_rec_wave.py`.

Two halves, both in a real browser over the `demo.html` gallery:

* the gallery's fixed legs (live input, no label) are asserted on their rendered
  state and computed styles, in both themes;
* the silent-mic lifecycle runs the real module against a fake level source and
  a fake clock (`page.clock`), never a microphone: the 3000 ms window and both
  warning texts are checked to the millisecond, with no real waiting.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e._color_assertions import set_theme, style

_DEFAULT_TEXT = "No sound from the microphone — check Bluetooth/AirPods"
_REMOTE_TEXT = (
    "No sound from the microphone — check the Remote Desktop audio recording setting "
    "('Record from this computer')"
)

# Light / dark `--muted`, `--attention` and `--attention-text` from the gallery's token blocks.
_MUTED = {"light": "rgb(101, 109, 118)", "dark": "rgb(125, 133, 144)"}
_ATTENTION = {"light": "rgb(154, 103, 0)", "dark": "rgb(210, 153, 34)"}
_ATTENTION_TEXT = {"light": "rgb(125, 78, 0)", "dark": "rgb(227, 179, 65)"}

# A fixed level source and a stream that only names its input; the test sets the
# level and reads what the component reported.
_SETUP = """
window.__lvl = { level: 0, closed: 0 };
window.__source = {
  running: true, connect() {}, close() { __lvl.closed += 1; },
  read: (n) => ({ rms: __lvl.level, levels: Array.from({ length: n }, () => __lvl.level) }),
};
window.__stream = (label) => ({ getAudioTracks: () => [{ label }] });
window.__box = document.createElement('div');
window.__box.id = 'probeBox';
window.__box.hidden = true;
document.body.appendChild(window.__box);
"""

_ATTACH = """
async (label) => {
  const { attachMicNotice } = await import('./mic-notice/mic-notice.js');
  window.__events = [];
  window.__stop = attachMicNotice(window.__box, window.__stream(label), {
    source: window.__source,
    onSilent: (text, name) => window.__events.push(['silent', text, name]),
    onSignal: () => window.__events.push(['signal']),
  });
}
"""


def _clocked(page: Page) -> Page:
    page.clock.install()
    page.evaluate(_SETUP)
    return page


def _warning_hidden(page: Page) -> bool:
    return page.evaluate("() => window.__box.querySelector('.mic-notice-silent').hidden")


# ------------------------------------------------------------------ gallery


def check_gallery_live_leg_names_the_input_and_shows_the_strip(gallery: Page) -> None:
    box = gallery.locator("#demoMicLive")
    expect(box).to_be_visible()
    expect(box.locator(".mic-notice-input")).to_have_text("Mic: AirPods")
    expect(box.locator(".mic-notice-wave .rec-wave")).to_have_count(1)
    expect(box.locator(".mic-notice-silent")).to_be_hidden()


def check_gallery_no_label_leg_keeps_the_strip_without_an_input_line(gallery: Page) -> None:
    box = gallery.locator("#demoMicNoLabel")
    expect(box).to_be_visible()
    expect(box.locator(".mic-notice-input")).to_be_hidden()
    expect(box.locator(".mic-notice-wave .rec-wave")).to_have_count(1)
    # The leg opts out of the timer.
    expect(box.locator(".rec-wave-time")).to_have_count(0)


def check_notice_colors_in_both_themes(gallery: Page) -> None:
    """The input line is muted, the strip accent, the warning the attention treatment."""
    gallery.evaluate(_SETUP)
    gallery.evaluate(_ATTACH, "AirPods")
    # Show the warning directly: the verdict itself is the lifecycle tests' job.
    gallery.evaluate("() => { window.__box.querySelector('.mic-notice-silent').hidden = false; }")
    for theme in ("light", "dark"):
        set_theme(gallery, theme)
        assert style(gallery, "#probeBox .mic-notice-input", "color") == _MUTED[theme]
        assert style(gallery, "#probeBox .mic-notice-silent", "color") == _ATTENTION_TEXT[theme]
        assert style(gallery, "#probeBox .mic-notice-silent", "borderTopColor") == _ATTENTION[theme]
    gallery.evaluate("() => window.__stop()")


# ---------------------------------------------------------------- lifecycle


def check_silent_after_exactly_three_seconds_then_signal_clears_it(gallery: Page) -> None:
    _clocked(gallery).evaluate(_ATTACH, "AirPods")
    assert gallery.evaluate("() => window.__box.hidden") is False
    assert _warning_hidden(gallery)

    gallery.clock.run_for(2900)
    assert _warning_hidden(gallery)  # still inside the window
    gallery.clock.run_for(200)
    assert not _warning_hidden(gallery)
    assert gallery.evaluate("() => window.__box.querySelector('.mic-notice-silent').textContent") == _DEFAULT_TEXT
    assert gallery.evaluate("() => window.__box.classList.contains('is-silent')") is True
    assert gallery.evaluate("() => window.__events") == [["silent", _DEFAULT_TEXT, "AirPods"]]

    gallery.evaluate("() => { window.__lvl.level = 0.2; }")
    gallery.clock.run_for(200)
    assert _warning_hidden(gallery)
    assert gallery.evaluate("() => window.__box.classList.contains('is-silent')") is False
    assert gallery.evaluate("() => window.__events.map((e) => e[0])") == ["silent", "signal"]
    gallery.evaluate("() => window.__stop()")


def check_sound_inside_the_window_never_warns(gallery: Page) -> None:
    _clocked(gallery).evaluate(_ATTACH, "AirPods")
    gallery.clock.run_for(2500)
    gallery.evaluate("() => { window.__lvl.level = 0.2; }")
    gallery.clock.run_for(5000)
    assert _warning_hidden(gallery)
    assert gallery.evaluate("() => window.__events.map((e) => e[0])") == ["signal"]
    gallery.evaluate("() => window.__stop()")


def check_remote_audio_points_at_the_remote_desktop_setting(gallery: Page) -> None:
    _clocked(gallery).evaluate(_ATTACH, "Remote Audio")
    gallery.clock.run_for(3200)
    assert gallery.evaluate("() => window.__box.querySelector('.mic-notice-silent').textContent") == _REMOTE_TEXT
    assert gallery.evaluate("() => window.__box.querySelector('.mic-notice-input').textContent") == "Mic: Remote Audio"
    gallery.evaluate("() => window.__stop()")


def check_every_other_input_keeps_the_bluetooth_text(gallery: Page, label: str) -> None:
    _clocked(gallery).evaluate(_ATTACH, label)
    gallery.clock.run_for(3200)
    text = gallery.evaluate("() => window.__box.querySelector('.mic-notice-silent').textContent")
    assert text == _DEFAULT_TEXT
    gallery.evaluate("() => window.__stop()")


def check_stop_empties_and_hides_the_notice_and_leaves_the_source_open(gallery: Page) -> None:
    _clocked(gallery).evaluate(_ATTACH, "AirPods")
    gallery.clock.run_for(3200)
    gallery.evaluate("() => { window.__stop(); window.__stop(); }")  # twice is fine
    assert gallery.evaluate("() => window.__box.hidden") is True
    assert gallery.evaluate("() => window.__box.children.length") == 0
    assert gallery.evaluate("() => window.__box.classList.contains('is-silent')") is False
    assert gallery.evaluate("() => window.__lvl.closed") == 0  # the caller owns the source
    # A stopped notice stays quiet however long the clock runs.
    gallery.clock.run_for(10000)
    assert gallery.evaluate("() => window.__events.length") == 1


def check_a_withheld_label_still_shows_the_notice(gallery: Page) -> None:
    _clocked(gallery).evaluate(_ATTACH, "")
    assert gallery.evaluate("() => window.__box.hidden") is False
    assert gallery.evaluate("() => window.__box.querySelector('.mic-notice-input').hidden") is True
    gallery.evaluate("() => window.__stop()")


def check_a_stream_with_no_track_api_does_not_throw(gallery: Page) -> None:
    _clocked(gallery)
    gallery.evaluate(
        """async () => {
          const { attachMicNotice } = await import('./mic-notice/mic-notice.js');
          window.__stop = attachMicNotice(window.__box, {}, { source: window.__source });
        }"""
    )
    assert gallery.evaluate("() => window.__box.querySelector('.mic-notice-input').hidden") is True
    gallery.evaluate("() => window.__stop()")
