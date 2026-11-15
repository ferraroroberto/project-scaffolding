"""Checks for the design-review rules the vendored components own: a switch, a glance row.

Called from `test_vendored_components.py`; kept apart so that module stays under the
structure ratchet's near-limit band.
"""

from __future__ import annotations

from playwright.sync_api import Page

from tests.e2e._color_assertions import style as _style

_LIGHT_ACCENT = "rgb(9, 105, 218)"
_DARK_ACCENT = "rgb(31, 111, 235)"


def check_switch_follows_aria_checked(gallery: Page, *, dark: bool = False) -> None:
    """COLOR-04: aria-checked alone (no `on` class) draws the accent track and moves the thumb."""
    want = _DARK_ACCENT if dark else _LIGHT_ACCENT
    # The track fades over 0.15s, so wait for the end value instead of reading mid-fade.
    gallery.wait_for_function(
        "([sel, want]) => getComputedStyle(document.querySelector(sel)).backgroundColor === want",
        arg=["#demoSwitchAria", want],
    )
    assert _style(gallery, "#demoSwitchAria .knob", "transform") == _style(gallery, "#demoSwitchOn .knob", "transform")


def check_glance_rows_exist_before_their_reads_land(gallery: Page) -> None:
    """LAYOUT-10: an empty glance value draws a dash and the row keeps its 44px height, so filling it moves nothing."""
    assert gallery.eval_on_selector(
        "#demoGlanceEmpty", "el => getComputedStyle(el, '::before').content").startswith('"—"')
    assert _style(gallery, "#demoGlanceEmpty", "whiteSpace") == "nowrap"
    assert _style(gallery, "#demoGlanceFilled", "whiteSpace") == "nowrap"
    heights = gallery.eval_on_selector_all(
        "#demoGlanceCard .glance-row", "els => els.map(e => e.getBoundingClientRect().height)")
    assert heights == [44, 44], heights
