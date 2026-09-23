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
fixed, body-level nav can't share the gallery's scrolling page. The
computed-style primitives both harnesses need (`style`, `set_theme`, `rgba`)
live once in `_color_assertions.py` (#208).
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e._color_assertions import contrast as _contrast
from tests.e2e._color_assertions import rgba as _rgba
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style
from tests.e2e._geometry import assert_min_target, assert_no_overlap
from tests.e2e.conftest import STATIC_DIR

_RANGE_ROWS = ("#demoRange2", "#demoRangeTabs", "#demoRange5")
_BOOT_SNIPPET = STATIC_DIR / "_vendored" / "text-size" / "text-size-boot.html"


@pytest.fixture()
def gallery(static_server: str, page: Page) -> Page:
    """The demo gallery, loaded and module-script-ready, in the light theme."""
    page.goto(f"{static_server}/_vendored/demo.html")
    page.wait_for_selector("body[data-demo-ready='1']")
    return page


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


_BASE_CONTROLS = ("#demoBaseButton", "#demoBaseInput", "#demoBaseSelect", "#demoBaseTextarea")


def _assert_base_inherits(page: Page) -> None:
    """base: every bare form control takes the body's font and text color.

    Without the base rule the UA stylesheet gives controls their own font
    (Arial at 13.33px on Windows Chrome) and a system text color (#266).
    """
    body = {prop: _style(page, "body", prop) for prop in ("fontFamily", "fontSize", "color")}
    for sel in _BASE_CONTROLS:
        for prop, want in body.items():
            assert _style(page, sel, prop) == want, (sel, prop)


_ACTION_LIST = "#demoActionList"


def _assert_action_row_colors(page: Page, *, muted: str, accent: tuple[int, int, int],
                              accent_text: str, control_border: str, attention: str) -> None:
    """action-row: the theme-dependent colors (meta, verb, filter, favorite)."""
    assert _style(page, "#demoActionTwoLine .action-row-meta", "color") == muted
    r, g, b, a = _rgba(_style(page, "#demoActionVerb", "backgroundColor"))
    assert (r, g, b) == accent
    assert 0 < a < 1
    assert _style(page, "#demoActionVerb", "color") == accent_text
    assert _style(page, "#demoActionFilter", "borderTopColor") == control_border
    assert _style(page, "#demoActionFavOn", "color") == attention


def _assert_action_row(page: Page) -> None:
    """action-row (#268, fleet-config#965): tap-the-row geometry and contract.

    Rows sit full-bleed in a zero-padded card on rows-scale heights; the
    title and context line truncate to one line; the favorite shows its
    pressed state by glyph fill, not only by color; every target is a real
    44px box, and no two touch.
    """
    assert _style(page, _ACTION_LIST, "paddingTop") == "0px"
    assert _style(page, "#demoActionOneLine", "minHeight") == "52px"
    assert _style(page, "#demoActionTwoLine", "minHeight") == "60px"
    # No vertical rules: rows divide on a top hairline, accessories on none.
    assert _style(page, "#demoActionTwoLine", "borderTopWidth") == "1px"
    assert _style(page, "#demoActionKebab", "borderLeftWidth") == "0px"
    # The main button is the row: it fills the row's full height.
    heights = page.evaluate(
        "() => { const row = document.getElementById('demoActionVerbRow');"
        " const main = row.querySelector('.action-row-main');"
        " return [row.clientHeight, main.getBoundingClientRect().height]; }"
    )
    assert heights[0] == heights[1], heights
    # Title: body at 600, one line, ellipsized; context: body-sm.
    title = "#demoActionLongTitle"
    assert _style(page, title, "fontWeight") == "600"
    assert _style(page, title, "fontSize") == "16px"
    assert _style(page, title, "whiteSpace") == "nowrap"
    assert _style(page, title, "textOverflow") == "ellipsis"
    assert page.eval_on_selector(title, "el => el.scrollWidth > el.clientWidth")
    assert _style(page, "#demoActionLong .action-row-meta", "fontSize") == "14px"
    assert _style(page, "#demoActionLong .action-row-meta", "textOverflow") == "ellipsis"
    # Favorite: outline at rest, filled glyph when pressed; the caller flips
    # aria-pressed only.
    assert _style(page, "#demoActionFavOn .action-row-fav-on", "display") != "none"
    assert _style(page, "#demoActionFavOn .action-row-fav-off", "display") == "none"
    assert _style(page, "#demoActionFavOff .action-row-fav-on", "display") == "none"
    page.click("#demoActionFavOff")
    expect(page.locator("#demoActionFavOff")).to_have_attribute("aria-pressed", "true")
    assert _style(page, "#demoActionFavOff .action-row-fav-off", "display") == "none"
    page.click("#demoActionFavOff")
    # Every accessory and main button is a >=44px target; none overlap.
    buttons = page.locator(f"{_ACTION_LIST} .action-row button")
    assert_min_target(buttons)
    assert_no_overlap(buttons)
    assert _style(page, "#demoActionKebab", "width") == "44px"
    assert _style(page, "#demoActionFilter", "height") == "44px"
    # The open kebab takes the accent; the filter hides rows (a flex row
    # must still honour [hidden]).
    page.click("#demoActionKebab")
    expect(page.locator("#demoActionKebab")).to_have_attribute("aria-expanded", "true")
    assert _style(page, "#demoActionKebab", "color") == "rgb(9, 105, 218)"
    page.fill("#demoActionFilterInput", "backup")
    expect(page.locator(f"{_ACTION_LIST} .action-row:visible")).to_have_count(1)
    page.fill("#demoActionFilterInput", "")
    expect(page.locator(f"{_ACTION_LIST} .action-row:visible")).to_have_count(4)


def test_card_contract(gallery: Page) -> None:
    """card: rounded.lg corners, spacing.md padding, hairline border, title glyph 18px.

    Also carries the base rule's and the action-row's (a card modifier)
    light-theme checks: a node of their own would breach the suite's
    ratcheted budget (.fleet.toml [e2e] test_budget).
    """
    assert _style(gallery, "#demoCard", "borderRadius") == "16px"
    assert _style(gallery, "#demoCard", "paddingTop") == "16px"
    assert _style(gallery, "#demoCard", "borderTopWidth") == "1px"
    assert _style(gallery, "#demoCard .card-title .icon", "width") == "18px"
    _assert_base_inherits(gallery)
    _assert_action_row(gallery)
    _assert_action_row_colors(
        gallery, muted="rgb(101, 109, 118)", accent=(9, 105, 218), accent_text="rgb(5, 80, 174)",
        control_border="rgb(129, 139, 152)", attention="rgb(154, 103, 0)",
    )


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
    # off-track = control-border (fleet-config#963), a 3:1+ control boundary.
    assert _style(gallery, "#demoSwitchOff", "backgroundColor") == "rgb(129, 139, 152)"


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
    """modal: opens via the native API, 34px close, 48px primary, AA disabled Save."""
    gallery.click("#openModalBtn")
    expect(gallery.locator("#demoDialog")).to_be_visible()
    assert _style(gallery, "#demoDialogClose", "width") == "34px"
    assert _style(gallery, "#demoDialogClose", "height") == "34px"
    # Save is the spec's 48px button-primary, not the page's 36px --control-h
    # (#280): the gallery sets --control-h: 36px, so a regression reads 36px.
    assert _style(gallery, "#demoSaveBtn", "height") == "48px"
    assert_min_target(gallery.locator("#demoSaveBtn"))
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
    # transparent), never a second solid. Text in accent-text, not the base
    # accent, which drops under AA on its own tint (fleet-config#963).
    r, g, b, a = _rgba(_style(gallery, "#demoButtonTint", "backgroundColor"))
    assert (r, g, b) == (9, 105, 218)
    assert 0 < a < 1
    assert _style(gallery, "#demoButtonTint", "color") == "rgb(5, 80, 174)"  # accent-text
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
    assert _style(gallery, "#demoButtonDanger", "color") == "rgb(164, 14, 38)"  # danger-text


def _assert_range_selection_reads_in_greyscale(page: Page) -> None:
    """The selected pill's border clears 3:1 (WCAG non-text) against a resting one.

    Contrast is luminance-only, so this is the greyscale test: before #267 the
    active and resting pills differed by ~1.06:1 on border, ~1.2:1 on fill and
    ~1:1 on text, so selection read through hue alone.
    """
    backdrop = _style(page, "body", "backgroundColor")
    for row in _RANGE_ROWS:
        active = _style(page, f"{row} .range-tab.active", "borderTopColor")
        resting = _style(page, f"{row} .range-tab:not(.active):not(:disabled)", "borderTopColor")
        ratio = _contrast(active, resting, backdrop)
        assert ratio >= 3, f"{row}: active vs resting border {ratio:.2f}:1"


def _assert_text_size(page: Page, static_server: str) -> None:
    """text-size (#276, fleet-config#967): Large scales rem type, not px geometry.

    Then the vendored boot snippet, byte-for-byte from its file, stamps the
    stored size and theme from `<head>` before the body parses, and falls
    back to `default` on an unknown value.
    """
    root = "html"
    assert page.get_attribute(root, "data-textsize") == "default"
    assert _style(page, root, "fontSize") == "16px"
    page.click("#demoTextSizeLarge")
    assert page.get_attribute(root, "data-textsize") == "large"
    assert _style(page, root, "fontSize") == "18px"  # 112.5% of 16px
    assert _style(page, "body", "fontSize") == "18px"  # rem type follows
    assert page.evaluate("localStorage.getItem('demo.textsize')") == "large"
    expect(page.locator("#demoTextSizeLarge")).to_have_attribute("aria-pressed", "true")
    expect(page.locator("#demoTextSizeLarge")).to_have_class(re.compile(r"\bactive\b"))
    # Geometry is px and holds at the Large step.
    assert _style(page, "#demoRangeDay", "height") == "36px"
    assert _style(page, "#demoActionOneLine", "minHeight") == "52px"
    assert _style(page, "#demoActionKebab", "width") == "44px"

    probe = f"{static_server}/_vendored/__boot_probe.html"
    html = (
        "<!DOCTYPE html><html><head>"
        + _BOOT_SNIPPET.read_text(encoding="utf-8")
        + '<link rel="stylesheet" href="text-size/text-size.css"></head>'
        "<body><script>window.seenAtBody = [document.documentElement.dataset.textsize,"
        " document.documentElement.dataset.theme];</script></body></html>"
    )
    page.route(probe, lambda route: route.fulfill(body=html, content_type="text/html"))
    for stored, want in (("small", "small"), ("huge", "default")):
        page.evaluate(
            "(v) => { localStorage.setItem('my-app.textsize', v);"
            " localStorage.setItem('my-app.theme', 'dark'); }", stored,
        )
        page.goto(probe)
        assert page.evaluate("window.seenAtBody") == [want, "dark"], stored
    assert _style(page, root, "fontSize") == "16px"  # 'huge' fell back to 100%
    page.evaluate("localStorage.setItem('my-app.textsize', 'small')")
    page.goto(probe)
    assert _style(page, root, "fontSize") == "15px"  # 93.75% of 16px


def test_range_tab_contract(gallery: Page, static_server: str, browser: Browser) -> None:
    """range-tab: control-h height, card-off resting, accent-soft active pill.

    Plus #267: a selected state that survives greyscale, one-line labels, and
    44px effective targets on a coarse pointer (checked here rather than in a
    new node, to hold the suite's ratcheted budget). Plus #276: the text-size
    control built on it, and its boot snippet.
    """
    assert _style(gallery, "#demoRangeDay", "height") == "36px"
    assert _style(gallery, "#demoRangeDay", "whiteSpace") == "nowrap"
    _assert_range_selection_reads_in_greyscale(gallery)
    assert _style(gallery, "#demoRangeWeek", "backgroundColor") == "rgb(246, 248, 250)"
    assert _style(gallery, "#demoRangeWeek", "color") == "rgb(101, 109, 118)"
    r, g, b, a = _rgba(_style(gallery, "#demoRangeDay", "backgroundColor"))
    assert (r, g, b) == (9, 105, 218)
    assert 0 < a < 1
    assert _style(gallery, "#demoRangeDay", "color") == "rgb(5, 80, 174)"  # accent-text
    assert _style(gallery, "#demoRangeDisabled", "opacity") == "0.45"
    # clicking a resting pill flips .active onto it (caller-owned toggle).
    gallery.click("#demoRangeWeek")
    expect(gallery.locator("#demoRangeWeek")).to_have_class(re.compile(r"\bactive\b"))
    expect(gallery.locator("#demoRangeDay")).not_to_have_class(re.compile(r"\bactive\b"))

    # Coarse pointer: the visual pill stays 36px, the ::before reaches the 44px
    # floor, and no two expanded rectangles overlap (an adjacent cluster).
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    try:
        phone = context.new_page()
        phone.goto(f"{static_server}/_vendored/demo.html")
        phone.wait_for_selector("body[data-demo-ready='1']")
        assert phone.evaluate("matchMedia('(pointer: coarse)').matches"), (
            "coarse-pointer emulation is not active"
        )
        for row in _RANGE_ROWS:
            assert_min_target(phone.locator(f"{row} .range-tab"))
        assert_no_overlap(phone.locator(".range-tabs .range-tab"))
        assert _style(phone, "#demoRangeDay", "height") == "36px"
    finally:
        context.close()

    # The text-size control is a range-tab row (#276), checked here for the
    # same budget reason. It navigates away from the gallery, so it runs last.
    _assert_text_size(gallery, static_server)


def test_page_foot_contract(gallery: Page) -> None:
    """page-foot: centered footer, muted/caption readout text, shared build-text format."""
    assert _style(gallery, "#demoPageFoot", "textAlign") == "center"
    assert _style(gallery, "#demoBuildReadout", "color") == "rgb(101, 109, 118)"
    assert _style(gallery, "#demoBuildReadout", "fontSize") == "12.48px"  # 0.78rem @ 16px root
    text = gallery.locator("#demoBuildReadout").inner_text()
    assert re.match(r"^Build: abc1234 · \d{4}-\d{2}-\d{2} \d{2}:\d{2}$", text), text


def test_home_head_contract(gallery: Page) -> None:
    """home-head: 52px row at 0-14px inset, title glyph 18px, status ellipsizes, right-pinned 34px toggle."""
    # One row at the disclosure closed-summary geometry (rows.md 52px, 0 14px).
    assert _style(gallery, "#demoHomeHead", "minHeight") == "52px"
    assert _style(gallery, "#demoHomeHead", "paddingLeft") == "14px"
    assert _style(gallery, "#demoHomeHead", "paddingTop") == "0px"  # overrides the card's own padding
    assert _style(gallery, "#demoHomeHead", "display") == "flex"
    # Title glyph is title-size and muted.
    assert _style(gallery, "#demoHomeHead .home-title .icon", "width") == "18px"
    # Status fills the middle and ellipsizes so it can't wrap the row.
    assert _style(gallery, "#demoHomeStatus", "textOverflow") == "ellipsis"
    assert _style(gallery, "#demoHomeStatus", "whiteSpace") == "nowrap"
    # Icon-only theme toggle: 34px square, subtle-contrast fill, no border, pinned right.
    assert _style(gallery, "#demoHomeToggle", "width") == "34px"
    assert _style(gallery, "#demoHomeToggle", "height") == "34px"
    assert _style(gallery, "#demoHomeToggle", "backgroundColor") == "rgb(246, 248, 250)"
    assert _style(gallery, "#demoHomeToggle", "borderTopWidth") == "0px"
    # The toggle is pinned to the right: its right edge sits within ~1px of the
    # row's content edge (row right minus the 14px inset), past the status.
    pinned = gallery.evaluate(
        "() => {"
        " const row = document.getElementById('demoHomeHead').getBoundingClientRect();"
        " const tog = document.getElementById('demoHomeToggle').getBoundingClientRect();"
        " const status = document.getElementById('demoHomeStatus').getBoundingClientRect();"
        " return { gap: (row.right - 14) - tog.right, afterStatus: tog.left >= status.right - 1 };"
        "}"
    )
    assert abs(pinned["gap"]) <= 1.5, pinned
    assert pinned["afterStatus"], pinned


def test_select_native_contract(gallery: Page) -> None:
    """select-native: control-height (36px via explicit height, not min-height), hairline border, input-bg fill."""
    # THE iOS decision: height is an explicit `height` (respected), never
    # `min-height` (ignored on a bare <select>, rendering it stubby).
    assert _style(gallery, "#demoSelectNative", "height") == "36px"
    assert _style(gallery, "#demoSelectNative", "borderRadius") == "12px"
    assert _style(gallery, "#demoSelectNative", "borderTopWidth") == "1px"
    assert _style(gallery, "#demoSelectNative", "borderTopColor") == "rgb(209, 217, 224)"
    # input-bg is card-off in light (var(--card-off) = #f6f8fa).
    assert _style(gallery, "#demoSelectNative", "backgroundColor") == "rgb(246, 248, 250)"
    assert _style(gallery, "#demoSelectNative", "color") == "rgb(31, 35, 40)"


# ---------------------------------------------------------------------- dark


def test_dark_theme_values(gallery: Page) -> None:
    """Every component re-skins from the dark token block — same structure."""
    _set_theme(gallery, "dark")
    # card surface goes to the dark elevated value.
    assert _style(gallery, "#demoCard", "backgroundColor") == "rgb(22, 27, 34)"
    # base: bare controls follow the body's text color into the dark theme.
    _assert_base_inherits(gallery)
    assert _style(gallery, "#demoBaseButton", "color") == "rgb(230, 237, 243)"
    # switch on-track stays green, at the brighter dark success value
    # (waits out the 0.15s track transition).
    _wait_bg(gallery, "#demoSwitchOn", "rgb(63, 185, 80)")
    # off-track is the dark control-border (fleet-config#963), not the hairline.
    _wait_bg(gallery, "#demoSwitchOff", "rgb(110, 118, 129)")
    # icon-tile fill steps to the brighter dark tile-blue.
    assert _style(gallery, "#demoTileBlue", "backgroundColor") == "rgb(47, 129, 247)"
    # structure is theme-independent: closed height and radii hold.
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "height") == "52px"
    assert _style(gallery, "#demoCard", "borderRadius") == "16px"
    # modal disabled recipe holds AA on the dark surface (dark card-off/muted).
    gallery.click("#openModalBtn")
    assert _style(gallery, "#demoSaveBtn", "backgroundColor") == "rgb(1, 4, 9)"
    assert _style(gallery, "#demoSaveBtn", "color") == "rgb(125, 133, 144)"
    # Enabled, the modal primary fills with the dark accent-fill (#1f6feb),
    # one step below accent so white text holds AA (fleet-config#963).
    gallery.eval_on_selector("#demoSaveBtn", "el => { el.disabled = false; }")
    assert _style(gallery, "#demoSaveBtn", "backgroundColor") == "rgb(31, 111, 235)"
    gallery.eval_on_selector("#demoSaveBtn", "el => { el.disabled = true; }")
    # button-primary takes the same dark accent-fill; the shared disabled
    # recipe holds AA on the dark card-off/muted surface too. The tints set
    # their text in the dark *-text tokens.
    assert _style(gallery, "#demoButtonPrimary", "backgroundColor") == "rgb(31, 111, 235)"
    assert _style(gallery, "#demoButtonTint", "color") == "rgb(88, 166, 255)"
    assert _style(gallery, "#demoButtonDanger", "color") == "rgb(255, 123, 114)"
    assert _style(gallery, "#demoButtonDisabled", "backgroundColor") == "rgb(1, 4, 9)"
    assert _style(gallery, "#demoButtonDisabled", "color") == "rgb(125, 133, 144)"
    # range-tab active pill re-skins to the dark accent-text, and its selection
    # still reads without hue on the dark surfaces.
    assert _style(gallery, "#demoRangeDay", "color") == "rgb(88, 166, 255)"
    _assert_range_selection_reads_in_greyscale(gallery)
    # page-foot readout re-skins to the dark muted value.
    assert _style(gallery, "#demoBuildReadout", "color") == "rgb(125, 133, 144)"
    # home-head toggle fill re-skins to the dark --close-bg (var(--line) = #30363d);
    # the 52px row geometry is theme-independent.
    assert _style(gallery, "#demoHomeHead", "minHeight") == "52px"
    assert _style(gallery, "#demoHomeToggle", "backgroundColor") == "rgb(48, 54, 61)"
    # select-native fill re-skins to the dark --input-bg (var(--bg) = #0d1117);
    # the 36px control height is theme-independent.
    assert _style(gallery, "#demoSelectNative", "height") == "36px"
    assert _style(gallery, "#demoSelectNative", "backgroundColor") == "rgb(13, 17, 23)"
    # action-row re-skins from the dark tokens; its rows-scale heights hold.
    assert _style(gallery, "#demoActionTwoLine", "minHeight") == "60px"
    _assert_action_row_colors(
        gallery, muted="rgb(125, 133, 144)", accent=(47, 129, 247),
        accent_text="rgb(88, 166, 255)",
        control_border="rgb(110, 118, 129)", attention="rgb(210, 153, 34)",
    )
