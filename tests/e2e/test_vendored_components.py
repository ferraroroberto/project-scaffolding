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

The action-row avatar, code-listing and day-row/day-marks checks live in
`_action_row_avatar_checks.py`, `_code_listing_checks.py` and `_day_checks.py`
and run as cases of the one test below.

The `nav/` component has its own harness — `test_vendored_nav.py` — because a
fixed, body-level nav can't share the gallery's scrolling page. The
computed-style primitives both harnesses need (`style`, `set_theme`, `rgba`)
live once in `_color_assertions.py` (#208).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from contextlib import AbstractContextManager

from playwright.sync_api import Browser, Page, expect

from tests.e2e import _action_row_avatar_checks, _code_listing_checks, _day_checks
from tests.e2e._action_row_assertions import (
    assert_action_row,
    assert_action_row_colors,
    assert_action_row_ext,
    assert_action_row_ext_colors,
    assert_action_row_meta_figures,
)
from tests.e2e._cases import cases
from tests.e2e._color_assertions import contrast as _contrast
from tests.e2e._color_assertions import rgba as _rgba
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style
from tests.e2e._geometry import (
    assert_min_target,
    assert_no_overlap,
    assert_unpainted,
    effective_rect,
)
from tests.e2e.conftest import STATIC_DIR

_RANGE_ROWS = ("#demoRange2", "#demoRangeTabs", "#demoRange5")
_TRANSPARENT = "rgba(0, 0, 0, 0)"
_BOOT_SNIPPET = STATIC_DIR / "_vendored" / "text-size" / "text-size-boot.html"


# The dark control fill: border-muted, the closed-palette value the spec fills
# controls and disabled buttons with (fleet-config#1368). Never #010409 / #0d1117.
_DARK_CONTROL_FILL = "rgb(33, 38, 45)"
_DARK_BLACK_WELLS = ("rgb(1, 4, 9)", "rgb(13, 17, 23)")


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


def _check_card_contract(gallery: Page) -> None:
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
    assert_action_row(gallery)
    assert_action_row_colors(
        gallery, muted="rgb(101, 109, 118)", ink="rgb(31, 35, 40)",
        control_border="rgb(129, 139, 152)", attention="rgb(154, 103, 0)",
    )
    assert_action_row_ext(gallery)
    assert_action_row_ext_colors(
        gallery, muted=(101, 109, 118), ink="rgb(31, 35, 40)", card="rgb(255, 255, 255)",
        success="rgb(26, 127, 55)", danger="rgb(207, 34, 46)",
    )
    assert_action_row_meta_figures(gallery)


def _check_disclosure_contract(gallery: Page) -> None:
    """disclosure: 52px closed summary, zeroed card padding, open-state divider."""
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "height") == "52px"
    assert _style(gallery, "#demoDisclosureClosed", "paddingTop") == "0px"
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "paddingLeft") == "14px"
    # Only the OPEN disclosure draws the divider under its summary.
    assert _style(gallery, "#demoDisclosureOpen .collapse-summary", "borderBottomWidth") == "1px"
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "borderBottomWidth") == "0px"


def _check_switch_contract(gallery: Page) -> None:
    """switch: 44x26 track, accent-fill on-track (never green), off-track = border."""
    assert _style(gallery, "#demoSwitchOn", "width") == "44px"
    assert _style(gallery, "#demoSwitchOn", "height") == "26px"
    # on = accent-fill (design.md `switch.trackOn`, fleet-config#1200), never green.
    assert _style(gallery, "#demoSwitchOn", "backgroundColor") == "rgb(9, 105, 218)"
    # off-track = control-border (fleet-config#963), a 3:1+ control boundary.
    assert _style(gallery, "#demoSwitchOff", "backgroundColor") == "rgb(129, 139, 152)"


def _check_switch_builder(gallery: Page) -> None:
    """switch.js: builder emits the contract markup and flips on click."""
    built = gallery.locator("#demoSwitchBuilt")
    expect(built).to_have_attribute("role", "switch")
    expect(built).to_have_attribute("aria-checked", "false")
    built.click()
    expect(built).to_have_attribute("aria-checked", "true")
    _wait_bg(gallery, "#demoSwitchBuilt", "rgb(9, 105, 218)")


def _check_empty_state_contract(gallery: Page) -> None:
    """empty-state: builder emits glyph (24px feature size) + message + action."""
    host = gallery.locator("#demoEmptyHost .empty-state")
    expect(host).to_be_visible()
    assert _style(gallery, "#demoEmptyHost .empty-state-icon", "width") == "24px"
    expect(gallery.locator("#demoEmptyHost .empty-state-message")).to_have_text(
        "Nothing reachable"
    )
    expect(gallery.locator("#demoEmptyHost .empty-state-action")).to_have_text("Retry")
    # The action is the block's one standalone button: a real 44px, not a hit-area
    # expansion (#286; it rendered 38.6px tall from padding + one label line).
    assert_min_target(gallery.locator("#demoEmptyHost .empty-state-action"))


def _check_modal_contract(gallery: Page) -> None:
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


def _check_modal_row_label_only(gallery: Page) -> None:
    """modal: the row label is ink 600; an app's muted span in the row keeps its own style (#363)."""
    gallery.click("#openModalBtn")
    for theme, ink, muted in (("light", "rgb(31, 35, 40)", "rgb(101, 109, 118)"),
                              ("dark", "rgb(230, 237, 243)", "rgb(125, 133, 144)")):
        _set_theme(gallery, theme)
        assert _style(gallery, "#demoRowLabel", "color") == ink, theme
        assert _style(gallery, "#demoRowLabel", "fontWeight") == "600", theme
        assert _style(gallery, "#demoRowNote", "color") == muted, theme
        assert _style(gallery, "#demoRowNote", "fontWeight") == "400", theme


def _check_modal_autofocus_title_has_no_ring(gallery: Page) -> None:
    """modal: an autofocused `h2[tabindex=-1]` title draws no ring; a tabbed control keeps it (#359)."""
    # The gallery paints no app-wide ring, so give it the one the fleet apps
    # ship (`:focus-visible { outline: 2px solid var(--accent) }`).
    gallery.add_style_tag(content=":focus-visible { outline: 2px solid rgb(9, 105, 218); outline-offset: 2px; }")
    # Open by keyboard so the focus the dialog moves to the title matches
    # :focus-visible, as it does on the iOS device that showed the ring.
    gallery.focus("#openModalBtn")
    gallery.keyboard.press("Enter")
    expect(gallery.locator("#demoDialog")).to_be_visible()
    title = gallery.locator("#demoDialog h2")
    expect(title).to_be_focused()
    assert title.evaluate("e => e.matches(':focus-visible')"), "title must be :focus-visible for this test to bite"
    assert _style(gallery, "#demoDialog h2", "outlineStyle") == "none"
    gallery.keyboard.press("Tab")
    expect(gallery.locator("#demoDialogClose")).to_be_focused()
    assert _style(gallery, "#demoDialogClose", "outlineStyle") == "solid"
    assert _style(gallery, "#demoDialogClose", "outlineWidth") == "2px"


def _check_icon_tile_contract(gallery: Page) -> None:
    """icon-tile: rounded.md squircle, tile-blue fill, feature-size glyph."""
    assert _style(gallery, "#demoTileBlue", "borderRadius") == "12px"
    assert _style(gallery, "#demoTileBlue", "backgroundColor") == "rgb(9, 105, 218)"
    assert _style(gallery, "#demoTileBlue .icon", "width") == "24px"


def _check_button_contract(gallery: Page) -> None:
    """button: four tiers + shared disabled recipe + outlined danger (fleet-config#296, #1403)."""
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
    # danger: the OUTLINED destructive recipe (fleet-config#1403, project-scaffolding#379)
    # — fully transparent fill (no fill, no tint), danger-text label, a 1px --deficit
    # border. Red on the former --deficit-soft tint.
    assert _style(gallery, "#demoButtonDanger", "backgroundColor") == "rgba(0, 0, 0, 0)"
    assert _style(gallery, "#demoButtonDanger", "color") == "rgb(164, 14, 38)"  # danger-text
    assert _style(gallery, "#demoButtonDanger", "borderColor") == "rgb(207, 34, 46)"  # deficit
    assert _style(gallery, "#demoButtonDanger", "borderWidth") == "1px"
    assert _contrast(_style(gallery, "#demoButtonDanger", "color"), "rgb(255, 255, 255)",
                     "rgb(255, 255, 255)") >= 4.5


_ICON_BUTTONS = "#demoIconButtons .icon-button"
# Every glyph-only control the gallery ships: the icon buttons, the home-head
# toggle + gear, the modal's close, and the action-row favorite + kebabs (all
# `.icon-button`s, #324/#329, fleet-config#1259), and every row verb: a verb on
# a list row is a plain icon-button too, the Stop alias included, with no fill
# and no border at rest (#386, fleet-config#1420).
_ICON_ONLY = (
    _ICON_BUTTONS,
    "#demoHomeHead .home-toggle",
    "#demoDialogClose",
    "#demoActionList .action-row-fav",
    "#demoActionList .action-row-kebab",
    "#demoActionList .action-row-verb",
    "#demoActionList .action-row-verb--stop",
    "#demoActionVerbCluster .icon-button",
)


def _assert_unpainted_at_rest(page: Page) -> None:
    """Icon-only controls: no fill, border or shadow at rest; >=44px targets.

    The pointer is moved off first so no control is read in its hover state.
    The modal close only has a box while its dialog is open, so its target
    check opens it.
    """
    page.mouse.move(0, 0)
    for selector in _ICON_ONLY:
        assert_unpainted(page, page.locator(selector))
    assert_min_target(page.locator(f"{_ICON_BUTTONS}, #demoHomeHead .home-toggle"))
    page.click("#openModalBtn")
    expect(page.locator("#demoDialog")).to_be_visible()
    page.mouse.move(0, 0)
    assert _style(page, "#demoDialogClose", "backgroundColor") == _TRANSPARENT
    assert_min_target(page.locator("#demoDialogClose"))
    page.click("#demoDialogClose")
    expect(page.locator("#demoDialog")).to_be_hidden()


def _assert_icon_button_targets(page: Page) -> None:
    """One 16px glyph whatever the box; a group's targets touch, never overlap."""
    glyphs = page.eval_on_selector_all(
        f"{_ICON_BUTTONS} .icon",
        "els => els.map(el => [getComputedStyle(el).width, getComputedStyle(el).height])",
    )
    assert glyphs and all(g == ["16px", "16px"] for g in glyphs), glyphs
    # The default box is 28px; the second group picks the control height.
    assert _style(page, "#demoIconButton", "width") == "28px"
    assert _style(page, "#demoIconButtonWide", "width") == "36px"
    for group in ("#demoIconButtonGroup", "#demoIconButtonGroupWide"):
        buttons = page.locator(f"{group} .icon-button")
        assert buttons.count() >= 2, group
        assert_no_overlap(buttons)
        # The gap is hit-min minus box: neighbouring targets touch exactly.
        rects = [effective_rect(buttons.nth(i)).effective for i in range(buttons.count())]
        for left, right in zip(rects, rects[1:]):
            assert abs(right.left - left.right) <= 0.5, (group, left, right)


def _check_icon_only_controls_unpainted(gallery: Page, theme: str) -> None:
    """Icon buttons, home-head toggles, modal close: unpainted, 44px targets, both themes."""
    _set_theme(gallery, theme)
    _assert_unpainted_at_rest(gallery)
    _assert_icon_button_targets(gallery)


def _check_sprite_open_about_view_control_glyphs(gallery: Page) -> None:
    """The sprite carries Open, About, View and Control, and each draws (#388)."""
    ids = ("i-external-link", "i-info", "i-eye", "i-mouse-pointer-2")
    drawn = gallery.eval_on_selector_all(
        "#demoGlyphRow svg.icon",
        """els => els.map(el => {
          const use = el.querySelector('use');
          const id = use.getAttribute('href').slice(1);
          const box = use.getBBox();
          return { id, symbol: !!document.getElementById(id),
                   drawn: box.width > 0 && box.height > 0 };
        })""",
    )
    assert [row["id"] for row in drawn] == list(ids)
    for row in drawn:
        assert row["symbol"] and row["drawn"], row


def _check_sprite_app_launcher_glyphs(gallery: Page) -> None:
    """The sprite carries the 16 glyphs upstreamed from app-launcher, and each draws (#391)."""
    ids = (
        "i-arrow-big-up", "i-arrow-down", "i-arrow-left", "i-arrow-right",
        "i-arrow-up", "i-bell", "i-chevron-down", "i-copy",
        "i-corner-down-left", "i-corner-down-right", "i-download", "i-eye-off",
        "i-file-diff", "i-gauge", "i-git-pull-request", "i-messages-square",
    )
    drawn = gallery.evaluate(
        """ids => ids.map(id => {
          const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
          const use = document.createElementNS('http://www.w3.org/2000/svg', 'use');
          use.setAttribute('href', '#' + id);
          svg.appendChild(use);
          document.body.appendChild(svg);
          const box = use.getBBox();
          svg.remove();
          return { id, symbol: !!document.getElementById(id),
                   drawn: box.width > 0 && box.height > 0 };
        })""",
        list(ids),
    )
    for row in drawn:
        assert row["symbol"] and row["drawn"], row


def _check_icon_button_contract(gallery: Page) -> None:
    """icon-button: hover and press change the glyph colour only (fleet-config#1259)."""
    gallery.mouse.move(0, 0)
    # Rest: the muted glyph; pressed takes accent-text; disabled is faint.
    assert _style(gallery, "#demoIconButton", "color") == "rgb(101, 109, 118)"
    assert _style(gallery, "#demoIconButtonPressed", "color") == "rgb(5, 80, 174)"
    assert _style(gallery, "#demoIconButtonDanger", "color") == "rgb(101, 109, 118)"
    assert _style(gallery, "#demoIconButtonDisabled", "color") == "rgb(209, 217, 224)"
    assert _style(gallery, "#demoIconButtonDisabled", "cursor") == "default"
    # Hover darkens the glyph to ink, and still paints nothing.
    gallery.hover("#demoIconButton")
    assert _style(gallery, "#demoIconButton", "color") == "rgb(31, 35, 40)"
    assert _style(gallery, "#demoIconButton", "backgroundColor") == _TRANSPARENT
    # A destructive one is quiet until hovered, then the danger tone.
    gallery.hover("#demoIconButtonDanger")
    assert _style(gallery, "#demoIconButtonDanger", "color") == "rgb(164, 14, 38)"
    assert _style(gallery, "#demoIconButtonDanger", "backgroundColor") == _TRANSPARENT
    # Dark: the same states re-skin from the dark tokens.
    _set_theme(gallery, "dark")
    gallery.mouse.move(0, 0)
    assert _style(gallery, "#demoIconButton", "color") == "rgb(125, 133, 144)"
    assert _style(gallery, "#demoIconButtonPressed", "color") == "rgb(88, 166, 255)"
    gallery.hover("#demoIconButton")
    assert _style(gallery, "#demoIconButton", "color") == "rgb(230, 237, 243)"


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
    # The control is the fleet's one choice shape, segmented (#353): the binder's
    # aria-pressed is what raises the chosen step, and the others rest flat.
    assert page.evaluate("document.getElementById('demoTextSize').classList.contains('segmented')")
    assert page.locator("#demoTextSize .range-tab").count() == 0
    assert _style(page, "#demoTextSizeLarge", "boxShadow") != "none"
    expect(page.locator("#demoTextSize [data-textsize][aria-pressed='true']")).to_have_count(1)
    assert _style(page, "#demoTextSize [data-textsize='small']", "boxShadow") == "none"
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


def _check_range_tab_contract(gallery: Page, static_server: str, browser: Browser) -> None:
    """range-tab: control-h height, card-off resting, accent-soft active pill.

    Plus #267: a selected state that survives greyscale, one-line labels, and
    44px effective targets on a coarse pointer (checked here rather than in a
    new node, to hold the suite's ratcheted budget). Plus #276: the text-size
    control (segmented since #353) and its boot snippet.
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

    # The text-size control (#276; a segmented group since #353), checked here
    # for the same budget reason. It navigates away from the gallery, so it runs last.
    _assert_text_size(gallery, static_server)


_SEG_GROUPS = ("#demoSegPicker", "#demoSeg5", "#demoSegVerbs", "#demoActionSegVerbs")
_AA = 4.5


def _assert_segmented_theme(page: Page, *, card: str, ink: str,
                            muted: tuple[int, int, int],
                            selected_fill: tuple[int, int, int]) -> None:
    """segmented in one theme: the raised selected segment, fg labels at AA.

    The selected segment is the state: a fill lighter than the track plus a
    shadow, never a hue (#341; dark fill #377). Every label (resting,
    selected, unavailable) is fg; contrast is judged as rendered, the
    translucent track composited over the card.
    """
    page.mouse.move(0, 0)
    r, g, b, a = _rgba(_style(page, "#demoSegPicker", "backgroundColor"))
    assert (r, g, b) == muted  # neutral-soft
    assert 0 < a < 1
    assert _style(page, "#demoSegPicker", "borderTopWidth") == "0px"
    track = _style(page, "#demoSegPicker", "backgroundColor")
    for group in _SEG_GROUPS:
        selected = f"{group} .segmented-item[aria-pressed='true']"
        resting = f"{group} .segmented-item[aria-pressed='false']:not(:disabled)"
        assert _rgba(_style(page, selected, "backgroundColor"))[:3] == selected_fill, group
        assert _style(page, selected, "boxShadow") != "none", group
        assert _style(page, resting, "backgroundColor") == _TRANSPARENT, group
        assert _style(page, resting, "boxShadow") == "none", group
        for seg in (selected, resting):
            assert _style(page, seg, "color") == ink, (group, seg)
    fill = _style(page, selected, "backgroundColor")
    # Raised, not pressed in: the selected fill is lighter than its track (the
    # contrast against black orders luminance; the track composites over card).
    black = "rgb(0, 0, 0)"
    assert _contrast(fill, black, card) > _contrast(track, black, card), (
        "selected segment is not lighter than its track")
    resting_ratio = _contrast(ink, track, card)
    selected_ratio = _contrast(ink, fill, card)
    assert resting_ratio >= _AA, f"label on track {resting_ratio:.2f}:1"
    assert selected_ratio >= _AA, f"selected label {selected_ratio:.2f}:1"
    # Unavailable: still the fg label, no opacity; the cursor says it.
    assert _style(page, "#demoSegFull", "color") == ink
    assert _style(page, "#demoSegFull", "opacity") == "1"
    assert _style(page, "#demoSegFull", "cursor") == "not-allowed"


def _check_segmented_contract(gallery: Page, static_server: str, browser: Browser) -> None:
    """segmented (#341, fleet-config#1334): the selected segment is the state.

    Both themes: card-raised selection, fg labels at AA on the track and on
    the selected segment, an unavailable segment that keeps its label. Then
    the caller-owned selection, and 44px vertical-only targets that never
    overlap on a coarse pointer (picker band, verbs row, the row cluster).
    """
    # Picker segments keep the control height; verbs are the real 44px row.
    assert _style(gallery, "#demoSegPicker", "height") == "36px"
    assert _style(gallery, "#demoSegMine", "height") == "30px"
    assert _style(gallery, "#demoSegVerbs", "height") == "44px"
    assert _style(gallery, "#demoSegOff", "height") == "38px"
    assert _style(gallery, "#demoSegMine", "whiteSpace") == "nowrap"
    _assert_segmented_theme(gallery, card="rgb(255, 255, 255)", ink="rgb(31, 35, 40)",
                            muted=(101, 109, 118), selected_fill=(255, 255, 255))
    _set_theme(gallery, "dark")
    _assert_segmented_theme(gallery, card="rgb(22, 27, 34)", ink="rgb(230, 237, 243)",
                            muted=(125, 133, 144), selected_fill=(53, 59, 67))
    _set_theme(gallery, "light")
    # Selection moves with a tap; an unavailable segment ignores one.
    gallery.click("#demoSegIssues")
    expect(gallery.locator("#demoSegIssues")).to_have_attribute("aria-pressed", "true")
    expect(gallery.locator("#demoSegMine")).to_have_attribute("aria-pressed", "false")
    gallery.click("#demoSegFull", force=True)
    expect(gallery.locator("#demoSegFull")).to_have_attribute("aria-pressed", "false")
    expect(gallery.locator("#demoSegPartial")).to_have_attribute("aria-pressed", "true")

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
        for group in _SEG_GROUPS:
            segments = phone.locator(f"{group} .segmented-item")
            assert_min_target(segments)
            assert_no_overlap(segments)
        # The band is vertical only: the visual segment keeps its height.
        assert _style(phone, "#demoSegMine", "height") == "30px"
    finally:
        context.close()


def _check_select_native_contract(gallery: Page) -> None:
    """select-native: control-height (36px via explicit height, not min-height), control-border border, input-bg fill."""
    # THE iOS decision: height is an explicit `height` (respected), never
    # `min-height` (ignored on a bare <select>, rendering it stubby).
    assert _style(gallery, "#demoSelectNative", "height") == "36px"
    assert _style(gallery, "#demoSelectNative", "borderRadius") == "12px"
    assert _style(gallery, "#demoSelectNative", "borderTopWidth") == "1px"
    assert _style(gallery, "#demoSelectNative", "borderTopColor") == "rgb(129, 139, 152)"  # control-border
    # input-bg is card-off in light (var(--card-off) = #f6f8fa).
    assert _style(gallery, "#demoSelectNative", "backgroundColor") == "rgb(246, 248, 250)"
    assert _style(gallery, "#demoSelectNative", "color") == "rgb(31, 35, 40)"


def _check_toast_contract(gallery: Page) -> None:
    """toast: nav-bar glass, centred above the nav, one line; only an error tints, never green."""
    gallery.click("#demoToastShow")
    toast = gallery.locator("#toast")
    expect(toast).to_be_visible()
    expect(toast).to_have_attribute("role", "status")
    expect(toast).to_have_attribute("aria-live", "polite")
    assert _style(gallery, "#toast", "position") == "fixed"
    # The nav-bar glass (--tabbar-bg), not a solid block and not a status colour.
    assert _style(gallery, "#toast", "backgroundColor") == "rgba(255, 255, 255, 0.62)"
    assert "blur(20px)" in _style(gallery, "#toast", "backdropFilter")
    assert _style(gallery, "#toast", "color") == "rgb(31, 35, 40)"
    assert _style(gallery, "#toast", "fontWeight") == "700"
    assert _style(gallery, "#toast", "textAlign") == "center"
    assert _style(gallery, "#toast", "borderRadius") == "12px"
    # 8px above the nav: nav height 61 + 2 x margin 21 + 8, with no safe-area inset here.
    assert _style(gallery, "#toast", "bottom") == "111px"
    geo = gallery.evaluate(
        "() => { const r = document.getElementById('toast').getBoundingClientRect();"
        " return { mid: (r.left + r.right) / 2, vw: innerWidth, w: r.width, h: r.height }; }"
    )
    assert abs(geo["mid"] - geo["vw"] / 2) <= 1, geo  # centred
    assert geo["w"] <= 560 and geo["h"] < 60, geo  # max-content: one line, bounded
    # Only a real error tints, and it interrupts.
    gallery.click("#demoToastError")
    expect(toast).to_have_attribute("aria-live", "assertive")
    assert _style(gallery, "#toast", "borderTopColor") == "rgb(207, 34, 46)"
    assert _style(gallery, "#toast", "color") == "rgb(255, 255, 255)"
    assert _style(gallery, "#toast", "backgroundColor") != "rgba(255, 255, 255, 0.62)"
    # The next neutral toast drops the tint again.
    gallery.click("#demoToastShow")
    assert _style(gallery, "#toast", "backgroundColor") == "rgba(255, 255, 255, 0.62)"
    # Dark: the same glass over the dark nav-bar fill.
    _set_theme(gallery, "dark")
    assert _style(gallery, "#toast", "backgroundColor") == "rgba(42, 45, 52, 0.55)"
    assert _style(gallery, "#toast", "color") == "rgb(230, 237, 243)"


# ---------------------------------------------------------------------- dark


def _check_dark_control_fill_is_not_true_black(gallery: Page) -> None:
    """Disabled button, select and empty-state action fill with #21262d in dark (#356, #352).

    Regression for the dark "black well": these fills used `--card-off` /
    `--bg`, true black (#010409) or near-black (#0d1117) on a #161b22 card.
    They follow `--input-bg`, which a dark host sets to the control fill.
    Light is unchanged (card-off, #f6f8fa).
    """
    fills = {
        "#demoButtonDisabled": "backgroundColor",
        "#demoSelectNative": "backgroundColor",
        "#demoEmptyHost .empty-state-action": "backgroundColor",
    }
    for selector, prop in fills.items():
        assert _style(gallery, selector, prop) == "rgb(246, 248, 250)", selector
    _set_theme(gallery, "dark")
    for selector, prop in fills.items():
        _wait_bg(gallery, selector, _DARK_CONTROL_FILL)
        assert _style(gallery, selector, prop) not in _DARK_BLACK_WELLS, selector
    # ... and the surface they sit on is the card, so the fill reads as a control.
    assert _style(gallery, "#demoEmptyHost", "backgroundColor") == "rgb(22, 27, 34)"


def _check_dark_labelled_surfaces_follow_the_control_fill(gallery: Page) -> None:
    """button-surface and the resting range-tab take the control fill and `fg` in dark (#358).

    Regression for the labelled black well: both filled with `--card-off`, true
    black (#010409) on a #161b22 card, with a `--muted` label at 4.08:1 on the
    control fill. They follow `--input-bg` and the label is `--ink` (`fg`,
    12.88:1). Light is unchanged, and the selected range-tab keeps its accent
    tint rather than the control fill.
    """
    resting = ("#demoButtonSurface", "#demoRangeWeek", "#demoRangeMonth")
    for selector in resting:
        assert _style(gallery, selector, "backgroundColor") == "rgb(246, 248, 250)", selector
        assert _style(gallery, selector, "color") == "rgb(101, 109, 118)", selector
    _set_theme(gallery, "dark")
    for selector in resting:
        _wait_bg(gallery, selector, _DARK_CONTROL_FILL)
        assert _style(gallery, selector, "color") == "rgb(230, 237, 243)", selector
    # The shared disabled recipe still wins over the dark label on a disabled tier.
    gallery.eval_on_selector("#demoButtonSurface", "el => { el.disabled = true; }")
    assert _style(gallery, "#demoButtonSurface", "color") == "rgb(125, 133, 144)"
    # The selected pill is unchanged: accent tint and accent-text, not the control fill.
    assert _style(gallery, "#demoRangeDay", "color") == "rgb(88, 166, 255)"
    assert _style(gallery, "#demoRangeDay", "backgroundColor") != _DARK_CONTROL_FILL


def _check_dark_theme_values(gallery: Page) -> None:
    """Every component re-skins from the dark token block — same structure."""
    _set_theme(gallery, "dark")
    # card surface goes to the dark elevated value.
    assert _style(gallery, "#demoCard", "backgroundColor") == "rgb(22, 27, 34)"
    # base: bare controls follow the body's text color into the dark theme.
    _assert_base_inherits(gallery)
    assert _style(gallery, "#demoBaseButton", "color") == "rgb(230, 237, 243)"
    # switch on-track re-skins to the dark accent-fill (waits out the 0.15s
    # track transition).
    _wait_bg(gallery, "#demoSwitchOn", "rgb(31, 111, 235)")
    # off-track is the dark control-border (fleet-config#963), not the hairline.
    _wait_bg(gallery, "#demoSwitchOff", "rgb(110, 118, 129)")
    # icon-tile fill steps to the dark tile-blue (the emphasis step, so the
    # white glyph holds contrast).
    assert _style(gallery, "#demoTileBlue", "backgroundColor") == "rgb(31, 111, 235)"
    # structure is theme-independent: closed height and radii hold.
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "height") == "52px"
    assert _style(gallery, "#demoCard", "borderRadius") == "16px"
    # modal disabled recipe holds AA on the dark surface (the dark control
    # fill #21262d / muted, fleet-config#1368 -- not true black).
    gallery.click("#openModalBtn")
    assert _style(gallery, "#demoSaveBtn", "backgroundColor") == _DARK_CONTROL_FILL
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
    assert _style(gallery, "#demoButtonDanger", "backgroundColor") == "rgba(0, 0, 0, 0)"
    assert _style(gallery, "#demoButtonDanger", "borderColor") == "rgb(248, 81, 73)"  # deficit
    assert _contrast("rgb(255, 123, 114)", "rgb(22, 27, 34)", "rgb(22, 27, 34)") >= 4.5
    assert _style(gallery, "#demoButtonDisabled", "backgroundColor") == _DARK_CONTROL_FILL
    assert _style(gallery, "#demoButtonDisabled", "color") == "rgb(125, 133, 144)"
    # range-tab active pill re-skins to the dark accent-text, and its selection
    # still reads without hue on the dark surfaces.
    assert _style(gallery, "#demoRangeDay", "color") == "rgb(88, 166, 255)"
    _assert_range_selection_reads_in_greyscale(gallery)
    # page-foot readout re-skins to the dark muted value.
    assert _style(gallery, "#demoBuildReadout", "color") == "rgb(125, 133, 144)"
    # home-head toggles stay unpainted in dark too (--close-bg defaults to
    # transparent, #324; test_icon_only_controls_unpainted sweeps both themes);
    # the 52px row geometry is theme-independent.
    assert _style(gallery, "#demoHomeHead", "minHeight") == "52px"
    assert _style(gallery, "#demoHomeToggle", "backgroundColor") == _TRANSPARENT
    assert _style(gallery, "#demoHomeSettings", "backgroundColor") == _TRANSPARENT
    # select-native fill re-skins to the dark --input-bg (the control fill #21262d);
    # the 36px control height is theme-independent.
    assert _style(gallery, "#demoSelectNative", "height") == "36px"
    assert _style(gallery, "#demoSelectNative", "backgroundColor") == _DARK_CONTROL_FILL
    assert _style(gallery, "#demoSelectNative", "borderTopColor") == "rgb(110, 118, 129)"
    # action-row re-skins from the dark tokens; its rows-scale heights hold.
    assert _style(gallery, "#demoActionTwoLine", "minHeight") == "60px"
    assert_action_row_colors(
        gallery, muted="rgb(125, 133, 144)", ink="rgb(230, 237, 243)",
        control_border="rgb(110, 118, 129)", attention="rgb(210, 153, 34)",
    )
    # action-row extensions (#341): the avatar and its badge ring re-skin too.
    assert_action_row_ext_colors(
        gallery, muted=(125, 133, 144), ink="rgb(230, 237, 243)", card="rgb(22, 27, 34)",
        success="rgb(63, 185, 80)", danger="rgb(248, 81, 73)",
    )
    assert_action_row_meta_figures(gallery)


def test_gallery_component_contracts(new_gallery: Callable[[], AbstractContextManager[Page]], static_server: str, browser: Browser) -> None:
    """Every gallery component's contract, one case per component, each on a freshly loaded gallery."""
    with cases() as c:
        with c.case("card_contract"), new_gallery() as gallery:
            _check_card_contract(gallery=gallery)
        with c.case("disclosure_contract"), new_gallery() as gallery:
            _check_disclosure_contract(gallery=gallery)
        with c.case("switch_contract"), new_gallery() as gallery:
            _check_switch_contract(gallery=gallery)
        with c.case("switch_builder"), new_gallery() as gallery:
            _check_switch_builder(gallery=gallery)
        with c.case("empty_state_contract"), new_gallery() as gallery:
            _check_empty_state_contract(gallery=gallery)
        with c.case("modal_contract"), new_gallery() as gallery:
            _check_modal_contract(gallery=gallery)
        with c.case("modal_row_label_only"), new_gallery() as gallery:
            _check_modal_row_label_only(gallery=gallery)
        with c.case("modal_autofocus_title_has_no_ring"), new_gallery() as gallery:
            _check_modal_autofocus_title_has_no_ring(gallery=gallery)
        with c.case("icon_tile_contract"), new_gallery() as gallery:
            _check_icon_tile_contract(gallery=gallery)
        with c.case("button_contract"), new_gallery() as gallery:
            _check_button_contract(gallery=gallery)
        for theme in ["light", "dark"]:
            with c.case(f"icon_only_controls_unpainted[{theme}]"), new_gallery() as gallery:
                _check_icon_only_controls_unpainted(gallery=gallery, theme=theme)
        with c.case("sprite_open_about_view_control_glyphs"), new_gallery() as gallery:
            _check_sprite_open_about_view_control_glyphs(gallery=gallery)
        with c.case("sprite_app_launcher_glyphs"), new_gallery() as gallery:
            _check_sprite_app_launcher_glyphs(gallery=gallery)
        with c.case("icon_button_contract"), new_gallery() as gallery:
            _check_icon_button_contract(gallery=gallery)
        with c.case("range_tab_contract"), new_gallery() as gallery:
            _check_range_tab_contract(gallery=gallery, static_server=static_server, browser=browser)
        with c.case("segmented_contract"), new_gallery() as gallery:
            _check_segmented_contract(gallery=gallery, static_server=static_server, browser=browser)
        with c.case("select_native_contract"), new_gallery() as gallery:
            _check_select_native_contract(gallery=gallery)
        with c.case("toast_contract"), new_gallery() as gallery:
            _check_toast_contract(gallery=gallery)
        with c.case("dark_control_fill_is_not_true_black"), new_gallery() as gallery:
            _check_dark_control_fill_is_not_true_black(gallery=gallery)
        with c.case("dark_labelled_surfaces_follow_the_control_fill"), new_gallery() as gallery:
            _check_dark_labelled_surfaces_follow_the_control_fill(gallery=gallery)
        with c.case("dark_theme_values"), new_gallery() as gallery:
            _check_dark_theme_values(gallery=gallery)
        for avatar in _action_row_avatar_checks.AVATARS:
            with c.case(f"avatar_hit_box_reaches_44px_without_growing_the_paint[{avatar}]"), new_gallery() as gallery:
                _action_row_avatar_checks.check_avatar_hit_box_reaches_44px_without_growing_the_paint(gallery=gallery, avatar=avatar)
        with c.case("avatar_hit_area_does_not_replace_the_badge"), new_gallery() as gallery:
            _action_row_avatar_checks.check_avatar_hit_area_does_not_replace_the_badge(gallery=gallery)
        with c.case("code_listing_copy_is_an_unpainted_icon_button_in_a_list_item"), new_gallery() as gallery:
            _code_listing_checks.check_code_listing_copy_is_an_unpainted_icon_button_in_a_list_item(gallery=gallery)
        with c.case("code_listing_copy_puts_the_listing_on_the_clipboard_and_confirms"), new_gallery() as gallery:
            _code_listing_checks.check_code_listing_copy_puts_the_listing_on_the_clipboard_and_confirms(gallery=gallery)
        with c.case("code_listing_copy_failure_is_said_not_swallowed"), new_gallery() as gallery:
            _code_listing_checks.check_code_listing_copy_failure_is_said_not_swallowed(gallery=gallery)
        with c.case("day_row_and_day_marks_contract"), new_gallery() as gallery:
            _day_checks.check_day_row_and_day_marks_contract(gallery=gallery)
