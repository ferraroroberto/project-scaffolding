"""Render harness for the code-listing component.

Drives the `demo.html` gallery through the shared `gallery` fixture in `conftest.py`;
split from `test_vendored_components.py` to keep each harness module small.

The listing sits inside a list item on purpose: the design-review rule COMP-14 judges
a painted button against the nearest `li`, so a Copy control that draws itself there
reads as a painted row verb. The component's Copy must draw nothing at rest.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style

_LISTING = "#demoCodeListing .code-listing"
_COPY = "#demoCodeListing .code-listing-copy"
_STATUS = "#demoCodeListing .code-listing-status"
_HEAD = "#demoCodeListing .code-listing-head"
_SAMPLE = "setx ARCHIVE_ROOT D:\\archive"


def _assert_unpainted(gallery: Page) -> None:
    """The Copy control draws no fill, border or shadow at rest, in either theme."""
    for theme in ("light", "dark"):
        _set_theme(gallery, theme)
        bg = _style(gallery, _COPY, "backgroundColor")
        assert bg in ("rgba(0, 0, 0, 0)", "transparent"), f"{theme}: painted fill {bg}"
        assert _style(gallery, _COPY, "backgroundImage") == "none"
        for side in ("Top", "Right", "Bottom", "Left"):
            assert _style(gallery, _COPY, f"border{side}Width") == "0px", f"{theme}: {side} border"
        assert _style(gallery, _COPY, "boxShadow") == "none"
    _set_theme(gallery, "light")


def test_code_listing_copy_is_an_unpainted_icon_button_in_a_list_item(gallery: Page) -> None:
    """code-listing: inside a list item the Copy is a plain glyph named by aria-label and a tooltip."""
    copy = gallery.locator(_COPY)
    expect(copy).to_be_visible()
    # The host is a list item, the exact shape COMP-14 measures against.
    assert gallery.locator("#demoCodeListing li .code-listing").count() == 1
    # A glyph on nothing: the vendored icon-button, no visible text.
    expect(copy).to_have_class(re.compile(r"\bicon-button\b"))
    expect(copy).to_have_attribute("aria-label", "Copy")
    expect(copy).to_have_attribute("title", "Copy")
    assert gallery.locator(_COPY).inner_text().strip() == ""
    _assert_unpainted(gallery)
    # The target floor is 44px and the header grows to hold it.
    box = copy.bounding_box()
    assert box is not None and box["width"] >= 44 and box["height"] >= 44, box
    head = gallery.locator(_HEAD).bounding_box()
    assert head is not None and head["height"] >= 44, head
    # The frame is the card surface on a hairline.
    assert _style(gallery, _LISTING, "backgroundColor") == "rgb(255, 255, 255)"  # --card
    assert _style(gallery, _LISTING, "borderTopLeftRadius") == "12px"  # --radius-md
    assert _style(gallery, "#demoCodeListing pre", "fontSize") == "13px"


def test_code_listing_copy_puts_the_listing_on_the_clipboard_and_confirms(gallery: Page) -> None:
    """code-listing: a tap copies the listing's text, swaps the glyph and announces it politely."""
    gallery.context.grant_permissions(["clipboard-read", "clipboard-write"])
    status = gallery.locator(_STATUS)
    expect(status).to_have_attribute("role", "status")
    expect(status).to_have_attribute("aria-live", "polite")
    expect(status).to_have_text("")
    gallery.locator(_COPY).click()
    expect(status).to_have_text("Copied")
    expect(gallery.locator(_COPY)).to_have_attribute("data-copied", "true")
    assert gallery.evaluate("() => navigator.clipboard.readText()") == _SAMPLE
    # The confirmation clears itself and the control returns to its resting glyph.
    expect(status).to_have_text("", timeout=5000)
    expect(gallery.locator(_COPY)).not_to_have_attribute("data-copied", "true")
    _assert_unpainted(gallery)


def test_code_listing_copy_failure_is_said_not_swallowed(gallery: Page) -> None:
    """code-listing: when the clipboard refuses, the header says so instead of confirming."""
    gallery.evaluate(
        "() => { Object.defineProperty(navigator, 'clipboard', {"
        " value: { writeText: () => Promise.reject(new Error('denied')) }, configurable: true }); }"
    )
    gallery.locator(_COPY).click()
    status = gallery.locator(_STATUS)
    expect(status).to_have_text("Copy failed")
    expect(status).to_have_attribute("data-state", "error")
    expect(gallery.locator(_COPY)).not_to_have_attribute("data-copied", "true")
