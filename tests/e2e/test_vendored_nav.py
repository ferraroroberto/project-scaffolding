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

import re
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
_ACCENT_DARK = "rgb(47, 129, 247)"
_MUTED = "rgb(101, 109, 118)"

_RGBA_RE = re.compile(r"rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)")
# Chromium serializes a computed color-mix() as `color(srgb R G B / A)` with
# 0-1 float channels (legacy rgba() only when no color-mix is involved).
_COLOR_SRGB_RE = re.compile(r"color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: / ([\d.]+))?\)")


def _rgba(color: str) -> tuple[int, int, int, float]:
    """Parse a getComputedStyle color string into (r, g, b, alpha 0-1)."""
    m = _RGBA_RE.match(color)
    if m:
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), a
    m = _COLOR_SRGB_RE.match(color)
    assert m, f"unexpected color format: {color}"
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    return (round(float(m.group(1)) * 255), round(float(m.group(2)) * 255),
            round(float(m.group(3)) * 255), a)


def _set_theme(page: Page, theme: str) -> None:
    page.evaluate(
        "(t) => { document.documentElement.dataset.theme = t; }", theme
    )


def _alpha(color: str) -> float:
    """Extract the alpha channel from a computed color string.

    A `color-mix(in srgb, ...)` result serializes as `rgba(r, g, b, a)` for
    the light-theme accent, but Chromium serializes the *dark*-theme accent's
    mix as `oklab(l a b / a)` instead (same `in srgb` mix, different output
    notation depending on the input channel values) — so this parses the
    alpha generically off the tail rather than assuming one color function.
    A solid, non-mixed `rgb(r, g, b)` (3 channels, no alpha) is opaque.
    """
    if "/" in color:
        return float(color.rsplit("/", 1)[1].rstrip(") ").strip())
    if color.startswith("rgba("):
        return float(color[len("rgba(") : -1].split(",")[3])
    return 1.0


def _wait_style(page: Page, selector: str, prop: str, expected: str) -> None:
    """Wait for a computed style property to settle on *expected*.

    `.tab` transitions `background`/`border-color`/`color` over 0.16s
    (nav-tabs.css), so an instant post-toggle read lands mid-interpolation —
    same reasoning as `test_vendored_components.py`'s `_wait_bg`.
    """
    page.wait_for_function(
        "([sel, prop, want]) => getComputedStyle(document.querySelector(sel))"
        "[prop] === want",
        arg=[selector, prop, expected],
    )


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


def test_mobile_pill_active_tab_is_accent_tint_not_inset_surface(
    nav_mobile: Page,
) -> None:
    """Active pill: accent-soft tint + accent-border-soft hairline, both themes (#159).

    Regression for the dark-mode "black hole": the active tab used to fill
    with `--card-off` (dark canvas-subtle, true black), which read as a hole
    punched through the translucent tabbar. It must render as a translucent
    accent tint instead — matching `button-tint` / `.icon-header-btn.active`
    emphasis elsewhere in the fleet.
    """
    r, g, b, a = _rgba(_style(nav_mobile, "#tabHome", "backgroundColor"))
    assert (r, g, b) == (9, 105, 218)
    assert 0 < a < 1
    assert _style(nav_mobile, "#tabHome", "color") == _ACCENT

    _set_theme(nav_mobile, "dark")
    _wait_style(nav_mobile, "#tabHome", "color", _ACCENT_DARK)
    dark_bg = _style(nav_mobile, "#tabHome", "backgroundColor")
    # The pre-fix `--card-off` fill resolved to this exact opaque literal.
    assert dark_bg != "rgb(1, 9, 9)"
    assert 0 < _alpha(dark_bg) < 1
