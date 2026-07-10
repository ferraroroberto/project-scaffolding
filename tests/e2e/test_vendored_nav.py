"""Render harness for the vendored `nav/` component (issue #142).

The nav can't join `demo.html`'s gallery — it's a sticky/fixed, body-level bar
that would sit on top of every other component — so this module mounts the real
`nav/nav-tabs.html` skeleton and the real `nav/nav-tabs.css` onto the gallery's
token blocks and asserts the icon contract on both surfaces.

The regression it exists to catch: `nav-tabs.css` used to hide `.tab-icon` on
desktop and reveal a `.tab-emoji` span instead, while every real adopter ships
SVG icons and no emoji span — so the desktop segmented control rendered
label-only tabs with no icon at all, silently, in five apps.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.conftest import STATIC_DIR

NAV_DIR = STATIC_DIR / "_vendored" / "nav"

# Desktop token values the assertions below key on (from demo.html's :root,
# which transcribes ~/.claude/design.md). --font-label 0.92rem @ 16px root
# = 14.72px; the icon is sized 1.05em of that.
_DESKTOP_ICON_PX = 14.72 * 1.05
_ACCENT = "rgb(9, 105, 218)"
_MUTED = "rgb(101, 109, 118)"


def _mount_nav(page: Page, base_url: str) -> Page:
    """Load the gallery (for its tokens), then graft on the real nav skeleton."""
    page.goto(f"{base_url}/_vendored/demo.html")
    page.wait_for_selector("body[data-demo-ready='1']")
    page.add_style_tag(url=f"{base_url}/_vendored/nav/nav-tabs.css")
    skeleton = (NAV_DIR / "nav-tabs.html").read_text(encoding="utf-8")
    page.evaluate(
        "(html) => document.body.insertAdjacentHTML('afterbegin', html)", skeleton
    )
    # `attached`, not the default `visible`: whether the icon is *visible* is
    # exactly what the tests below assert, and a hidden one must fail there with
    # a named locator rather than time out here in the fixture.
    page.wait_for_selector(".tabs .tab-icon", state="attached")
    return page


@pytest.fixture()
def nav(static_server: str, page: Page) -> Page:
    """The nav skeleton at a desktop viewport (fine pointer)."""
    page.set_viewport_size({"width": 1100, "height": 800})
    return _mount_nav(page, static_server)


@pytest.fixture()
def nav_mobile(static_server: str, browser: Browser) -> Iterator[Page]:
    """The nav skeleton at a phone viewport with a coarse pointer."""
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    try:
        _mount_nav(page, static_server)
        # Boot check, not a skip: if touch emulation stops flipping the pointer
        # media feature, every assertion below would silently test the desktop
        # rules instead of the pill.
        assert page.evaluate("matchMedia('(pointer: coarse)').matches"), (
            "coarse-pointer emulation is not active — the mobile pill rules "
            "never matched, so this harness would assert nothing"
        )
        yield page
    finally:
        context.close()


def _style(page: Page, selector: str, prop: str) -> str:
    return page.eval_on_selector(
        selector, "(el, prop) => getComputedStyle(el)[prop]", prop
    )


def test_skeleton_ships_no_emoji_span() -> None:
    """The markup skeleton demonstrates icon + label only (#142)."""
    assert "tab-emoji" not in (NAV_DIR / "nav-tabs.html").read_text(encoding="utf-8")


def test_desktop_icon_is_visible(nav: Page) -> None:
    """Desktop segmented control renders the SVG icon beside the label."""
    icon = nav.locator("#tabHome .tab-icon")
    expect(icon).to_be_visible()
    box = icon.bounding_box()
    assert box is not None
    assert box["width"] == pytest.approx(_DESKTOP_ICON_PX, abs=0.5)
    assert box["height"] == pytest.approx(_DESKTOP_ICON_PX, abs=0.5)
    # Painted by the stylesheet, not by per-path attributes, so the glyph takes
    # the tab's colour: accent when active, muted when not.
    assert _style(nav, "#tabHome .tab-icon", "fill") == "none"
    assert _style(nav, "#tabHome .tab-icon", "stroke") == _ACCENT
    assert _style(nav, "#tabStats .tab-icon", "stroke") == _MUTED
    # The icon leads; the label follows.
    label = nav.locator("#tabHome .tab-label").bounding_box()
    assert label is not None
    assert box["x"] + box["width"] <= label["x"]


def test_legacy_emoji_span_stays_hidden(nav: Page) -> None:
    """An app that still ships `.tab-emoji` gets the icon, not the emoji (#142).

    This is what lets an adopter re-vendor `nav-tabs.css` alone — without
    touching its markup — and land on the fixed desktop look.
    """
    nav.evaluate(
        "() => document.querySelector('#tabHome .tab-label')"
        ".insertAdjacentHTML('beforebegin', "
        "'<span class=\"tab-emoji\" aria-hidden=\"true\">\\ud83c\\udfe0</span>')"
    )
    expect(nav.locator("#tabHome .tab-emoji")).to_be_hidden()
    expect(nav.locator("#tabHome .tab-icon")).to_be_visible()


def test_narrow_desktop_collapses_to_a_centred_icon(nav: Page) -> None:
    """Below 520px on a fine pointer: label clipped, icon centred, no phantom gap."""
    nav.set_viewport_size({"width": 500, "height": 800})
    icon = nav.locator("#tabHome .tab-icon")
    expect(icon).to_be_visible()
    # The label leaves the accessibility tree intact but the flex flow entirely,
    # so `.tab`'s gap reserves no space beside the icon.
    expect(nav.locator("#tabHome")).to_have_accessible_name("Home")
    tab = nav.locator("#tabHome").bounding_box()
    box = icon.bounding_box()
    assert tab is not None and box is not None
    assert box["x"] + box["width"] / 2 == pytest.approx(tab["x"] + tab["width"] / 2, abs=1)


def test_mobile_pill_stacks_icon_over_label(nav_mobile: Page) -> None:
    """The floating pill keeps its 20px icon above the label."""
    icon = nav_mobile.locator("#tabHome .tab-icon")
    expect(icon).to_be_visible()
    assert _style(nav_mobile, "#tabHome .tab-icon", "width") == "20px"
    assert _style(nav_mobile, "#tabHome .tab-icon", "height") == "20px"
    assert _style(nav_mobile, "#tabHome .tab-icon", "stroke") == _ACCENT
    box = icon.bounding_box()
    label = nav_mobile.locator("#tabHome .tab-label").bounding_box()
    assert box is not None and label is not None
    assert box["y"] + box["height"] <= label["y"]
