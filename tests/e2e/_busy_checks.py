"""Checks for the button busy state and the `runBusy` helper.

Run as cases of `test_vendored_components.py` on a freshly loaded `demo.html` gallery.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e._color_assertions import contrast as _contrast
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style

_AA = 4.5
_TIERS = ("Primary", "Tint", "Ghost", "Surface", "Danger", "Icon")
# The control fill: card-off in light, border-muted in dark, never a black well.
_FILL = {"light": "rgb(246, 248, 250)", "dark": "rgb(33, 38, 45)"}
_SPIN_JS = """sel => { const s = getComputedStyle(document.querySelector(sel), '::after');
  return { content: s.content, name: s.animationName, w: parseFloat(s.width), h: parseFloat(s.height) }; }"""


def _check_busy_look(page: Page, theme: str) -> None:
    _set_theme(page, theme)
    for tier in _TIERS:
        sel = f"#demoBusy{tier}"
        fill = _style(page, sel, "backgroundColor")
        assert fill == _FILL[theme], (theme, tier, fill)
        assert _style(page, sel, "pointerEvents") == "none", (theme, tier)
        assert _style(page, sel, "display") in ("flex", "inline-flex"), (theme, tier)  # a flex item blockifies inline-flex
        # A busy control still says what is happening: its label clears AA.
        assert _contrast(_style(page, sel, "color"), fill, fill) >= _AA, (theme, tier)
        spin = page.evaluate(_SPIN_JS, sel)
        assert spin["name"] == "button-busy-spin" and spin["content"] != "none", (theme, tier, spin)
        assert abs(spin["w"] - spin["h"]) < 0.5 and spin["w"] > 8, (theme, tier, spin)
    # The ring stands in for a leading glyph: the glyph is gone while busy.
    assert _style(page, "#demoBusyIcon > .icon", "display") == "none", theme


def check_busy_state_both_themes(gallery: Page) -> None:
    """busy: dimmed control fill, no taps, AA label, an inline spinner in place of the icon; both themes."""
    for theme in ("light", "dark"):
        _check_busy_look(gallery, theme)


def check_busy_state_on_a_phone(gallery: Page) -> None:
    """busy: the same look at phone width, with the ring and label on one row inside the button."""
    gallery.set_viewport_size({"width": 390, "height": 844})
    for theme in ("light", "dark"):
        _check_busy_look(gallery, theme)
    geo = gallery.evaluate(
        "() => { const b = document.getElementById('demoBusySurface').getBoundingClientRect();"
        " return { w: b.width, h: b.height, vw: innerWidth }; }"
    )
    assert geo["w"] <= geo["vw"] and geo["h"] == 36, geo  # the surface tier keeps its control height


def check_busy_spinner_stops_under_reduced_motion(gallery: Page) -> None:
    """busy: prefers-reduced-motion keeps the ring but stops it turning."""
    gallery.emulate_media(reduced_motion="reduce")
    spin = gallery.evaluate(_SPIN_JS, "#demoBusySurface")
    assert spin["name"] == "none" and spin["content"] != "none", spin


def check_run_busy_flow(gallery: Page) -> None:
    """runBusy: busy while in flight, a second tap runs nothing, toasts on success and on failure."""
    run, calls, toast = gallery.locator("#demoBusyRun"), gallery.locator("#demoBusyCalls"), gallery.locator("#toast")
    run.click()
    expect(run).to_have_attribute("aria-busy", "true")
    expect(toast).to_have_text("Refreshing")
    # A second tap in flight: pointer events are off, and a scripted click is ignored too.
    assert _style(gallery, "#demoBusyRun", "pointerEvents") == "none"
    gallery.evaluate("document.getElementById('demoBusyRun').click()")
    expect(calls).to_have_text("1")
    gallery.click("#demoBusyFinish")
    expect(run).not_to_have_attribute("aria-busy", "true")
    expect(toast).to_have_text("Refreshed")
    expect(toast).to_have_attribute("aria-live", "polite")
    # A failure clears busy too and says why, as an error.
    run.click()
    expect(run).to_have_attribute("aria-busy", "true")
    gallery.click("#demoBusyFail")
    expect(run).not_to_have_attribute("aria-busy", "true")
    expect(toast).to_have_text("Refresh failed: timed out")
    expect(toast).to_have_attribute("aria-live", "assertive")
    expect(calls).to_have_text("2")
