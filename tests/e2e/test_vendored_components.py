"""Render harness for the vendored UI components (issue #120).

Drives `app/webapp/static/_vendored/demo.html` — the component gallery — in a
real browser and asserts each component's *key computed styles* in both the
light and dark themes, so a regression in any `_vendored/<name>/<name>.css`
fails loudly here rather than silently downstream in a consuming app.

The gallery is served over HTTP by the `static_server` session fixture (see
`conftest.py`) because the components' ESM imports (`switch.js`,
`empty-state.js`) don't run from `file://`.

Assertions are the contracts from `~/.claude/design.md` v2 ("Component
contracts" + the component token blocks); expected colors are the sRGB spec
values (the demo page omits the P3 twins on purpose).

The `nav/` component has its own harness — `test_vendored_nav.py` — because a
fixed, body-level nav can't share the gallery's scrolling page.
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect


@pytest.fixture()
def gallery(static_server: str, page: Page) -> Page:
    """The demo gallery, loaded and module-script-ready, in the light theme."""
    page.goto(f"{static_server}/_vendored/demo.html")
    page.wait_for_selector("body[data-demo-ready='1']")
    return page


def _style(page: Page, selector: str, prop: str) -> str:
    return page.eval_on_selector(
        selector, "(el, prop) => getComputedStyle(el)[prop]", prop
    )


def _set_theme(page: Page, theme: str) -> None:
    page.evaluate(
        "(t) => { document.documentElement.dataset.theme = t; }", theme
    )


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


def _wait_bg(page: Page, selector: str, expected: str) -> None:
    """Wait for a background-color to settle on `expected`.

    The switch track transitions its background over 0.15s, so an instant
    computed-style read lands mid-interpolation; wait for the end value.
    """
    page.wait_for_function(
        "([sel, want]) => getComputedStyle(document.querySelector(sel))"
        ".backgroundColor === want",
        arg=[selector, expected],
    )


# --------------------------------------------------------------------- light


def test_card_contract(gallery: Page) -> None:
    """card: rounded.lg corners, spacing.md padding, hairline border, title glyph 18px."""
    assert _style(gallery, "#demoCard", "borderRadius") == "16px"
    assert _style(gallery, "#demoCard", "paddingTop") == "16px"
    assert _style(gallery, "#demoCard", "borderTopWidth") == "1px"
    assert _style(gallery, "#demoCard .card-title .icon", "width") == "18px"


def test_disclosure_contract(gallery: Page) -> None:
    """disclosure: 52px closed summary, zeroed card padding, open-state divider."""
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "height") == "52px"
    assert _style(gallery, "#demoDisclosureClosed", "paddingTop") == "0px"
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "paddingLeft") == "14px"
    # Only the OPEN disclosure draws the divider under its summary.
    assert _style(gallery, "#demoDisclosureOpen .collapse-summary", "borderBottomWidth") == "1px"
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "borderBottomWidth") == "0px"


def test_switch_contract(gallery: Page) -> None:
    """switch: 44x26 track, green (success) on-track, off-track = border."""
    assert _style(gallery, "#demoSwitchOn", "width") == "44px"
    assert _style(gallery, "#demoSwitchOn", "height") == "26px"
    # THE green decision (design.md v2): on = colors.success, not accent.
    assert _style(gallery, "#demoSwitchOn", "backgroundColor") == "rgb(26, 127, 55)"
    assert _style(gallery, "#demoSwitchOff", "backgroundColor") == "rgb(209, 217, 224)"


def test_switch_builder(gallery: Page) -> None:
    """switch.js: builder emits the contract markup and flips on click."""
    built = gallery.locator("#demoSwitchBuilt")
    expect(built).to_have_attribute("role", "switch")
    expect(built).to_have_attribute("aria-checked", "false")
    built.click()
    expect(built).to_have_attribute("aria-checked", "true")
    _wait_bg(gallery, "#demoSwitchBuilt", "rgb(26, 127, 55)")


def test_empty_state_contract(gallery: Page) -> None:
    """empty-state: builder emits glyph (24px feature size) + message + action."""
    host = gallery.locator("#demoEmptyHost .empty-state")
    expect(host).to_be_visible()
    assert _style(gallery, "#demoEmptyHost .empty-state-icon", "width") == "24px"
    expect(gallery.locator("#demoEmptyHost .empty-state-message")).to_have_text(
        "Nothing reachable"
    )
    expect(gallery.locator("#demoEmptyHost .empty-state-action")).to_have_text("Retry")


def test_modal_contract(gallery: Page) -> None:
    """modal: opens via the native API, 34px close, AA disabled recipe on Save."""
    gallery.click("#openModalBtn")
    expect(gallery.locator("#demoDialog")).to_be_visible()
    assert _style(gallery, "#demoDialogClose", "width") == "34px"
    assert _style(gallery, "#demoDialogClose", "height") == "34px"
    # Disabled primary = the flat card-off/muted/line recipe, not opacity.
    assert _style(gallery, "#demoSaveBtn", "backgroundColor") == "rgb(246, 248, 250)"
    assert _style(gallery, "#demoSaveBtn", "color") == "rgb(101, 109, 118)"
    gallery.click("#demoDialogClose")
    expect(gallery.locator("#demoDialog")).to_be_hidden()


def test_icon_tile_contract(gallery: Page) -> None:
    """icon-tile: rounded.md squircle, tile-blue fill, feature-size glyph."""
    assert _style(gallery, "#demoTileBlue", "borderRadius") == "12px"
    assert _style(gallery, "#demoTileBlue", "backgroundColor") == "rgb(9, 105, 218)"
    assert _style(gallery, "#demoTileBlue .icon", "width") == "24px"


def test_button_contract(gallery: Page) -> None:
    """button: four tiers + shared disabled recipe + danger tint (fleet-config#296)."""
    # primary: solid accent fill, accent-fg text, spec's 48px min-height.
    assert _style(gallery, "#demoButtonPrimary", "backgroundColor") == "rgb(9, 105, 218)"
    assert _style(gallery, "#demoButtonPrimary", "color") == "rgb(255, 255, 255)"
    assert _style(gallery, "#demoButtonPrimary", "minHeight") == "48px"
    # tint: accent-soft fill — accent-tinted and non-opaque (color-mix with
    # transparent), never a second solid. Accent text.
    r, g, b, a = _rgba(_style(gallery, "#demoButtonTint", "backgroundColor"))
    assert (r, g, b) == (9, 105, 218)
    assert 0 < a < 1
    assert _style(gallery, "#demoButtonTint", "color") == "rgb(9, 105, 218)"
    # ghost: TRANSPARENT fill (not a tint), muted text, hairline line border.
    assert _style(gallery, "#demoButtonGhost", "backgroundColor") == "rgba(0, 0, 0, 0)"
    assert _style(gallery, "#demoButtonGhost", "color") == "rgb(101, 109, 118)"
    assert _style(gallery, "#demoButtonGhost", "borderColor") == "rgb(209, 217, 224)"
    # surface: card-off fill at the control height, muted text.
    assert _style(gallery, "#demoButtonSurface", "backgroundColor") == "rgb(246, 248, 250)"
    assert _style(gallery, "#demoButtonSurface", "height") == "36px"
    assert _style(gallery, "#demoButtonSurface", "color") == "rgb(101, 109, 118)"
    # disabled: the one shared card-off/line/muted recipe, not opacity.
    assert _style(gallery, "#demoButtonDisabled", "backgroundColor") == "rgb(246, 248, 250)"
    assert _style(gallery, "#demoButtonDisabled", "borderColor") == "rgb(209, 217, 224)"
    assert _style(gallery, "#demoButtonDisabled", "color") == "rgb(101, 109, 118)"
    assert _style(gallery, "#demoButtonDisabled", "opacity") == "1"
    # danger: the tint recipe restated on --deficit — still non-opaque.
    dr, dg, db, da = _rgba(_style(gallery, "#demoButtonDanger", "backgroundColor"))
    assert (dr, dg, db) == (207, 34, 46)
    assert 0 < da < 1
    assert _style(gallery, "#demoButtonDanger", "color") == "rgb(207, 34, 46)"


def test_range_tab_contract(gallery: Page) -> None:
    """range-tab: control-h height, card-off resting, accent-soft active pill."""
    assert _style(gallery, "#demoRangeDay", "height") == "36px"
    assert _style(gallery, "#demoRangeWeek", "backgroundColor") == "rgb(246, 248, 250)"
    assert _style(gallery, "#demoRangeWeek", "color") == "rgb(101, 109, 118)"
    r, g, b, a = _rgba(_style(gallery, "#demoRangeDay", "backgroundColor"))
    assert (r, g, b) == (9, 105, 218)
    assert 0 < a < 1
    assert _style(gallery, "#demoRangeDay", "color") == "rgb(9, 105, 218)"
    assert _style(gallery, "#demoRangeDisabled", "opacity") == "0.45"
    # clicking a resting pill flips .active onto it (caller-owned toggle).
    gallery.click("#demoRangeWeek")
    expect(gallery.locator("#demoRangeWeek")).to_have_class(re.compile(r"\bactive\b"))
    expect(gallery.locator("#demoRangeDay")).not_to_have_class(re.compile(r"\bactive\b"))


def test_page_foot_contract(gallery: Page) -> None:
    """page-foot: centered footer, muted/caption readout text, shared build-text format."""
    assert _style(gallery, "#demoPageFoot", "textAlign") == "center"
    assert _style(gallery, "#demoBuildReadout", "color") == "rgb(101, 109, 118)"
    assert _style(gallery, "#demoBuildReadout", "fontSize") == "12.48px"  # 0.78rem @ 16px root
    text = gallery.locator("#demoBuildReadout").inner_text()
    assert re.match(r"^Build: abc1234 · \d{4}-\d{2}-\d{2} \d{2}:\d{2}$", text), text


# ---------------------------------------------------------------------- dark


def test_dark_theme_values(gallery: Page) -> None:
    """Every component re-skins from the dark token block — same structure."""
    _set_theme(gallery, "dark")
    # card surface goes to the dark elevated value.
    assert _style(gallery, "#demoCard", "backgroundColor") == "rgb(22, 27, 34)"
    # switch on-track stays green, at the brighter dark success value
    # (waits out the 0.15s track transition).
    _wait_bg(gallery, "#demoSwitchOn", "rgb(63, 185, 80)")
    # icon-tile fill steps to the brighter dark tile-blue.
    assert _style(gallery, "#demoTileBlue", "backgroundColor") == "rgb(47, 129, 247)"
    # structure is theme-independent: closed height and radii hold.
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "height") == "52px"
    assert _style(gallery, "#demoCard", "borderRadius") == "16px"
    # modal disabled recipe holds AA on the dark surface (dark card-off/muted).
    gallery.click("#openModalBtn")
    assert _style(gallery, "#demoSaveBtn", "backgroundColor") == "rgb(1, 4, 9)"
    assert _style(gallery, "#demoSaveBtn", "color") == "rgb(125, 133, 144)"
    # button-primary re-skins to the dark accent; the shared disabled recipe
    # holds AA on the dark card-off/muted surface too.
    assert _style(gallery, "#demoButtonPrimary", "backgroundColor") == "rgb(47, 129, 247)"
    assert _style(gallery, "#demoButtonDisabled", "backgroundColor") == "rgb(1, 4, 9)"
    assert _style(gallery, "#demoButtonDisabled", "color") == "rgb(125, 133, 144)"
    # range-tab active pill re-skins to the dark accent.
    assert _style(gallery, "#demoRangeDay", "color") == "rgb(47, 129, 247)"
    # page-foot readout re-skins to the dark muted value.
    assert _style(gallery, "#demoBuildReadout", "color") == "rgb(125, 133, 144)"
