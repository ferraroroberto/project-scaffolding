"""The vendored `action-row` contract assertions, shared by the gallery's light and dark cases.

`test_vendored_components.py` checks the action row as a card modifier in the
light theme (`card_contract`) and re-skinned in the dark one
(`dark_theme_values`); these helpers hold the row's geometry, colours,
extensions and meta figures so both cases assert the same contract.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e._color_assertions import rgba as _rgba
from tests.e2e._color_assertions import style as _style
from tests.e2e._geometry import (
    assert_min_target,
    assert_no_overlap,
)

_TRANSPARENT = "rgba(0, 0, 0, 0)"


_ACTION_LIST = "#demoActionList"


def assert_action_row_colors(page: Page, *, muted: str, ink: str, control_border: str,
                              attention: str) -> None:
    """action-row: the theme-dependent colors (meta, verbs, filter, favorite)."""
    assert _style(page, "#demoActionTwoLine .action-row-meta", "color") == muted
    # A row verb is a plain icon-button: no fill, no
    # border, the muted glyph at rest, at the 44px square. The Stop alias
    # renders exactly like Run, not outlined.
    page.mouse.move(0, 0)
    for verb in ("#demoActionVerb", "#demoActionStop"):
        assert _style(page, verb, "backgroundColor") == _TRANSPARENT, verb
        assert _style(page, verb, "borderTopWidth") == "0px", verb
        assert _style(page, verb, "color") == muted, verb
        assert _style(page, verb, "width") == "44px", verb
        assert _style(page, verb, "height") == "44px", verb
    assert _style(page, "#demoActionFilter", "borderTopColor") == control_border
    assert _style(page, "#demoActionFavOn", "color") == attention


def assert_action_row(page: Page) -> None:
    """action-row: tap-the-row geometry and contract.

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
    # A verb under hover changes its glyph colour only (to ink): still no fill,
    # still no border.
    for verb in ("#demoActionVerb", "#demoActionStop"):
        page.hover(verb)
        assert _style(page, verb, "color") == _style(page, "#demoActionTwoLine .action-row-title", "color"), verb
        assert _style(page, verb, "backgroundColor") == _TRANSPARENT, verb
        assert _style(page, verb, "borderTopWidth") == "0px", verb
    page.mouse.move(0, 0)
    # The open kebab takes the accent; the filter hides rows (a flex row
    # must still honour [hidden]).
    page.click("#demoActionKebab")
    expect(page.locator("#demoActionKebab")).to_have_attribute("aria-expanded", "true")
    assert _style(page, "#demoActionKebab", "color") == "rgb(9, 105, 218)"
    page.fill("#demoActionFilterInput", "backup")
    expect(page.locator(f"{_ACTION_LIST} .action-row:visible")).to_have_count(1)
    page.fill("#demoActionFilterInput", "")
    expect(page.locator(f"{_ACTION_LIST} .action-row:visible")).to_have_count(5)


# The rect of the last character of an element's text, and whether it lies inside
# the element's own box: a figure an ellipsis cut is laid out past the right edge
# (or collapsed to nothing), a figure on a wrapped second line stays inside.
_LAST_CHAR_VISIBLE_JS = """el => {
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let last = null;
  while (walker.nextNode()) last = walker.currentNode;
  const range = document.createRange();
  range.setStart(last, last.data.length - 1);
  range.setEnd(last, last.data.length);
  const c = range.getBoundingClientRect(), box = el.getBoundingClientRect();
  return { shown: c.width > 0 && c.right <= box.right + 0.5 && c.bottom <= box.bottom + 0.5,
           lines: Math.round(box.height / parseFloat(getComputedStyle(el).lineHeight)),
           overflowX: el.scrollWidth > el.clientWidth + 1,
           overflowY: el.scrollHeight > el.clientHeight + 1 };
}"""


def assert_action_row_meta_figures(page: Page) -> None:
    """action-row meta (LAYOUT-09): wraps to two lines, so its trailing figures stay.

    At the 390px phone width a `<words> · <time> · <count>` status line used to
    keep one line and lose `12 conversations` behind an ellipsis. It now wraps
    to at most two lines (a third is clamped), the title keeps one line, and a
    one-line meta keeps the rows-scale height. Runs in the theme the caller set;
    the original viewport comes back afterwards.
    """
    original = page.viewport_size
    page.set_viewport_size({"width": 390, "height": 844})
    try:
        meta = page.eval_on_selector("#demoActionMetaFiguresText", _LAST_CHAR_VISIBLE_JS)
        assert meta == {"shown": True, "lines": 2, "overflowX": False, "overflowY": False}, meta
        clamped = page.eval_on_selector("#demoActionMetaClampedText", _LAST_CHAR_VISIBLE_JS)
        assert clamped["lines"] == 2 and clamped["overflowY"], clamped
        for row in ("#demoActionMetaFigures", "#demoActionMetaClamped"):
            title = f"{row} .action-row-title"
            assert _style(page, title, "whiteSpace") == "nowrap", row
            assert page.eval_on_selector(title, "el => el.scrollWidth <= el.clientWidth + 1"), row
        # A one-line meta keeps the rows-scale height (the wrap only adds height).
        assert _style(page, "#demoActionTwoLine", "minHeight") == "60px"
        assert page.eval_on_selector(
            "#demoActionTwoLine", "el => el.getBoundingClientRect().height"
        ) == 60
    finally:
        if original:
            page.set_viewport_size(original)


_ACTION_EXT = "#demoActionListExt"
_AFTER_JS ="(el, prop) => getComputedStyle(el, '::after')[prop]"


def _after(page: Page, selector: str, prop: str) -> str:
    """A computed property of the `::after` pseudo-element (the avatar badge)."""
    return page.eval_on_selector(selector, _AFTER_JS, prop)


def assert_action_row_ext_colors(page: Page, *, muted: tuple[int, int, int], ink: str,
                                  card: str, success: str, danger: str) -> None:
    """action-row extensions: avatar fill and badge, trailing value, per theme.

    The badge means alive and nothing else: `up` is success, `down` is
    danger, no attribute paints no dot, and the dot is ringed in the card
    colour so it reads cut out of the squircle.
    """
    r, g, b, a = _rgba(_style(page, "#demoAvatarUp", "backgroundColor"))
    assert (r, g, b) == muted  # neutral-soft: the muted mix
    assert 0 < a < 1
    assert _style(page, "#demoAvatarUp", "color") == ink
    assert _after(page, "#demoAvatarUp", "backgroundColor") == success
    assert _after(page, "#demoAvatarDown", "backgroundColor") == danger
    assert _after(page, "#demoAvatarPlain", "content") == "none"
    for badge in ("#demoAvatarUp", "#demoAvatarDown"):
        assert _after(page, badge, "boxShadow") == f"{card} 0px 0px 0px 2px", badge
        assert _after(page, badge, "width") == "12px", badge
    assert _style(page, "#demoActionValue", "color") == ink


def assert_action_row_ext(page: Page) -> None:
    """action-row extensions: one leading slot, one trailing item.

    The avatar is a 36px squircle inside the main button, so a tap on it is a
    tap on the row; the trailing item (switch, value, segmented verbs) is the
    main button's sibling, inset to the text column's edge; the check swaps
    its glyph when pressed; every target is 44px and none overlap.
    """
    assert _style(page, "#demoAvatarUp", "width") == "36px"
    assert _style(page, "#demoAvatarUp", "height") == "36px"
    assert _style(page, "#demoAvatarUp", "borderRadius") == "12px"
    assert _style(page, "#demoAvatarUp .icon", "width") == "20px"
    # The avatar is part of the tap target: a hit test at its centre lands in
    # the row's main button.
    assert page.evaluate(
        "() => { const r = document.getElementById('demoAvatarUp').getBoundingClientRect();"
        " const hit = document.elementFromPoint((r.left + r.right) / 2, (r.top + r.bottom) / 2);"
        " return !!hit && !!hit.closest('.action-row-main'); }"
    )
    # Rows-scale heights hold with an avatar: a meta row is 60px, title-only 52px.
    assert _style(page, "#demoActionAvatarRow", "minHeight") == "60px"
    assert _style(page, "#demoActionSegRow", "minHeight") == "52px"
    # Each trailing item sits outside the main button, its right edge at the
    # text column's inset (row 4px + 10px).
    for trail in ("#demoActionTrailSwitch", "#demoActionValue", "#demoActionSegVerbs",
                  "#demoActionVerbCluster"):
        geo = page.eval_on_selector(
            trail,
            "el => { const row = el.closest('.action-row').getBoundingClientRect();"
            " return { inMain: !!el.closest('.action-row-main'),"
            " inset: row.right - el.getBoundingClientRect().right }; }",
        )
        assert not geo["inMain"], (trail, geo)
        assert abs(geo["inset"] - 14) <= 0.5, (trail, geo)
    assert _style(page, "#demoActionValue", "fontVariantNumeric") == "tabular-nums"
    assert _style(page, "#demoActionValue", "fontWeight") == "600"
    # A segmented verb cluster in a row: 44px segments on the 44px verbs track.
    segments = page.locator("#demoActionSegVerbs .segmented-item")
    assert [_style(page, f"#demoActionSegVerbs .segmented-item:nth-child({i})", "width")
            for i in (1, 2, 3)] == ["44px"] * 3
    assert _style(page, "#demoActionSegVerbs", "height") == "44px"
    assert_min_target(segments)
    assert_no_overlap(segments)
    # Check: an empty circle at rest, a checked one when pressed (the shape is
    # what reads without hue), in icon-button's pressed accent-text.
    check = "#demoActionCheck"
    assert _style(page, f"{check} .action-row-check-on", "display") == "none"
    page.click(check)
    expect(page.locator(check)).to_have_attribute("aria-pressed", "true")
    assert _style(page, f"{check} .action-row-check-off", "display") == "none"
    assert _style(page, f"{check} .action-row-check-on", "display") != "none"
    assert _style(page, check, "color") == "rgb(5, 80, 174)"
    page.click(check)
    # Every control in the list is a >=44px target; none overlap.
    controls = page.locator(f"{_ACTION_EXT} .action-row > button")
    assert controls.count() == 7
    assert_min_target(controls)
    assert_no_overlap(controls)
    # A verb cluster is an icon-button group with no track: unpainted, 44px
    # boxes that touch (gap 0) and never overlap.
    cluster = "#demoActionVerbCluster"
    assert _style(page, cluster, "backgroundColor") == _TRANSPARENT
    assert _style(page, cluster, "columnGap") in ("0px", "normal")
    verbs = page.locator(f"{cluster} .icon-button")
    assert verbs.count() == 2
    assert_min_target(verbs)
    assert_no_overlap(verbs)
    assert [_style(page, f"{cluster} .icon-button:nth-child({i})", "width") for i in (1, 2)] == ["44px"] * 2
