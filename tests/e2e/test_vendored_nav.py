"""Render harness for the vendored `nav/` component (issue #142).

The nav can't join `demo.html`'s gallery — it's a sticky/fixed, body-level bar
that would sit on top of every other component — so this module mounts the real
`nav/nav-tabs.html` skeleton and the real `nav/nav-tabs.css` onto the gallery's
token blocks and asserts the icon contract on both surfaces.

The regression it exists to catch: `nav-tabs.css` used to hide `.tab-icon` on
desktop and reveal a `.tab-emoji` span instead, while every real adopter ships
SVG icons and no emoji span — so the desktop segmented control rendered
label-only tabs with no icon at all, silently, in five apps.

The computed-style primitives this harness shares with the gallery's
(`style`, `set_theme`, `rgba`) live once in `_color_assertions.py` (#208).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e._color_assertions import rgba as _rgba
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style
from tests.e2e.conftest import STATIC_DIR

NAV_DIR = STATIC_DIR / "_vendored" / "nav"

# Desktop token values the assertions below key on (from demo.html's :root,
# which transcribes ~/.claude/design.md). --font-label 0.92rem @ 16px root
# = 14.72px; the icon is sized 1.05em of that.
_DESKTOP_ICON_PX = 14.72 * 1.05
# Active-tab text and icon sit on the accent-soft tint, so they take
# accent-text, not the base accent (fleet-config#963).
_ACCENT_TEXT = "rgb(5, 80, 174)"
_ACCENT_TEXT_DARK = "rgb(88, 166, 255)"
_MUTED = "rgb(101, 109, 118)"
# design.md layout.wide / layout.rail (fleet-config#968).
_WIDE = 1100
_RAIL = 80


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
    """The nav skeleton at a desktop viewport (fine pointer), below the rail."""
    page.set_viewport_size({"width": _WIDE - 1, "height": 800})
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


def test_skeleton_ships_no_emoji_span() -> None:
    """The markup skeleton demonstrates icon + label only (#142)."""
    assert "tab-emoji" not in (NAV_DIR / "nav-tabs.html").read_text(encoding="utf-8")


def test_desktop_control_and_wide_rail(nav: Page) -> None:
    """Desktop: the icon beside the label in the column, a left rail when wide.

    Below layout.wide the segmented control holds the layout.measure column.
    At 1100px and up it is the 80px full-height rail (#281, fleet-config#968):
    tabs stacked icon over label, content offset past it even when an app's
    own `body`/`.app` padding shorthand loads after the vendored file.
    """
    nav_box = nav.locator(".tabs").bounding_box()
    assert nav_box is not None
    assert nav_box["width"] == 772 - 12 - 12  # layout.measure minus 2x --gap
    icon = nav.locator("#tabHome .tab-icon")
    expect(icon).to_be_visible()
    box = icon.bounding_box()
    assert box is not None
    assert box["width"] == pytest.approx(_DESKTOP_ICON_PX, abs=0.5)
    assert box["height"] == pytest.approx(_DESKTOP_ICON_PX, abs=0.5)
    # Painted by the stylesheet, not by per-path attributes, so the glyph takes
    # the tab's colour: accent-text when active, muted when not.
    assert _style(nav, "#tabHome .tab-icon", "fill") == "none"
    assert _style(nav, "#tabHome .tab-icon", "stroke") == _ACCENT_TEXT
    assert _style(nav, "#tabStats .tab-icon", "stroke") == _MUTED
    # The icon leads; the label follows.
    label = nav.locator("#tabHome .tab-label").bounding_box()
    assert label is not None
    assert box["x"] + box["width"] <= label["x"]

    nav.set_viewport_size({"width": 1440, "height": 900})
    rail = nav.locator(".tabs").bounding_box()
    assert rail == {"x": 0, "y": 0, "width": _RAIL, "height": 900}, rail
    assert _style(nav, ".tabs", "backgroundColor") == "rgb(255, 255, 255)"  # card
    assert _style(nav, ".tabs", "borderRightWidth") == "1px"
    assert _style(nav, ".tabs", "borderRightColor") == "rgb(209, 217, 224)"  # line
    assert _style(nav, ".tabs", "borderLeftWidth") == "0px"
    tabs = nav.evaluate(
        "() => [...document.querySelectorAll('.tabs .tab')].map((t) => {"
        " const l = t.querySelector('.tab-label'); const lb = l.getBoundingClientRect();"
        " const ib = t.querySelector('.tab-icon').getBoundingClientRect();"
        " const b = t.getBoundingClientRect();"
        " return { top: b.top, height: b.height, iconW: ib.width,"
        "  iconAbove: ib.bottom <= lb.top + 0.5, labelW: lb.width,"
        "  clipped: l.scrollWidth > l.clientWidth + 0.5 }; })"
    )
    assert [t["top"] for t in tabs] == sorted(t["top"] for t in tabs), tabs
    for t in tabs:
        assert t["iconAbove"] and t["iconW"] == 24, t  # icons.size.feature
        assert t["labelW"] > 1 and not t["clipped"], t
        assert t["height"] >= 44, t
    # Placement only: the active state is the column's, unchanged.
    assert _style(nav, "#tabHome", "color") == _ACCENT_TEXT
    expect(nav.locator("#tabHome")).to_have_attribute("aria-selected", "true")
    # Content clears the rail, even against an app's later padding shorthand.
    nav.add_style_tag(content="body { padding: 0; } .app { padding: 0 12px; }")
    app_x = nav.evaluate("() => document.querySelector('.app').getBoundingClientRect().x")
    assert app_x >= _RAIL, app_x


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


_LONG_LABELS = ("Capture", "History", "Settings", "Energy", "Family")


def test_narrow_desktop_stacks_icon_over_label(nav: Page) -> None:
    """Below 520px on a fine pointer: never icon-only; the icon stacks over its label.

    Five tabs of 6-8 letters, the case that clipped with the icon beside the
    label (#278): every label renders whole under its centred icon, and each
    tab keeps the 44px floor.
    """
    nav.evaluate(
        "(labels) => { const bar = document.querySelector('.tabs');"
        " while (bar.querySelectorAll('.tab').length < labels.length)"
        "   bar.appendChild(bar.querySelector('.tab:last-child').cloneNode(true));"
        " bar.querySelectorAll('.tab-label').forEach((l, i) => { l.textContent = labels[i]; }); }",
        list(_LONG_LABELS),
    )
    for width in (320, 500):
        nav.set_viewport_size({"width": width, "height": 800})
        metrics = nav.evaluate(
            "() => [...document.querySelectorAll('.tabs .tab')].map((t) => {"
            " const l = t.querySelector('.tab-label').getBoundingClientRect();"
            " const i = t.querySelector('.tab-icon').getBoundingClientRect();"
            " const b = t.getBoundingClientRect(); const s = t.querySelector('.tab-label');"
            " return { clipped: s.scrollWidth > s.clientWidth + 0.5, labelW: l.width,"
            "  iconAbove: i.bottom <= l.top + 0.5, height: b.height,"
            "  offCentre: Math.abs((i.left + i.right) / 2 - (b.left + b.right) / 2) }; })"
        )
        assert len(metrics) == len(_LONG_LABELS)
        for label, m in zip(_LONG_LABELS, metrics):
            assert not m["clipped"] and m["labelW"] > 1, (width, label, m)
            assert m["iconAbove"], (width, label, m)
            assert m["height"] >= 44, (width, label, m)
            assert m["offCentre"] <= 1, (width, label, m)
    expect(nav.locator("#tabHome")).to_have_accessible_name("Capture")


def test_mobile_pill_stacks_icon_over_label(nav_mobile: Page) -> None:
    """The floating pill keeps its 20px icon above the label; no rail when coarse."""
    icon = nav_mobile.locator("#tabHome .tab-icon")
    expect(icon).to_be_visible()
    assert _style(nav_mobile, "#tabHome .tab-icon", "width") == "20px"
    assert _style(nav_mobile, "#tabHome .tab-icon", "height") == "20px"
    assert _style(nav_mobile, "#tabHome .tab-icon", "stroke") == _ACCENT_TEXT
    box = icon.bounding_box()
    label = nav_mobile.locator("#tabHome .tab-label").bounding_box()
    assert box is not None and label is not None
    assert box["y"] + box["height"] <= label["y"]
    # A coarse pointer never gets the wide-layout rail, at any width (#281).
    nav_mobile.set_viewport_size({"width": 1440, "height": 900})
    assert nav_mobile.evaluate(f"matchMedia('(min-width: {_WIDE}px)').matches")
    bar = nav_mobile.locator(".tabs").bounding_box()
    assert bar is not None and bar["width"] > _RAIL and bar["height"] < 100, bar


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
    assert _style(nav_mobile, "#tabHome", "color") == _ACCENT_TEXT

    _set_theme(nav_mobile, "dark")
    _wait_style(nav_mobile, "#tabHome", "color", _ACCENT_TEXT_DARK)
    dark_bg = _style(nav_mobile, "#tabHome", "backgroundColor")
    # The pre-fix `--card-off` fill resolved to this exact opaque literal.
    assert dark_bg != "rgb(1, 9, 9)"
    assert 0 < _alpha(dark_bg) < 1
