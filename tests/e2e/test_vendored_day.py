"""Render harness for the day-row and day-marks components.

Drives the `demo.html` gallery through the shared `gallery` fixture in `conftest.py`;
split from `test_vendored_components.py` to keep each harness module small.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page

from tests.e2e._color_assertions import contrast as _contrast
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style
from tests.e2e._geometry import assert_min_target


_AA = 4.5
_TRANSPARENT = "rgba(0, 0, 0, 0)"
_DAY_ROWS = "#demoDayRows"
_DAY_CELLS = "#demoDayWeek .demo-day-cell"
_MARK_PAINT = {  # the property that carries each mark's colour
    "booked": "backgroundColor", "will": "borderTopColor", "extra": "borderTopColor",
    "looking": "borderTopColor", "off": "backgroundColor",
}
_FONT_MIN = 14.0
_NON_TEXT_AA = 3.0

# Everything a shape is, minus its colour: if two marks share this they differ
# only by hue, which the spec forbids ("each mark is distinct in shape alone").
_SHAPE_JS = """els => els.map(el => {
  const s = getComputedStyle(el);
  return { mark: el.dataset.mark,
           shape: [s.width, s.height, s.borderTopWidth, s.borderTopLeftRadius, s.transform,
                   s.backgroundImage !== 'none', _alpha(s.backgroundColor) > 0].join('|') };
  function _alpha(c) { const m = c.match(/[\\d.]+/g); return m.length > 3 ? +m[3] : 1; }
})"""


def _card_bg(page: Page) -> str:
    return _style(page, "#demoDayList", "backgroundColor")


def _assert_day_row_theme(page: Page) -> None:
    """Date tile floor, text floor and AA contrast, in whichever theme is set."""
    card = _card_bg(page)
    # Every date tile is at least the 44px floor, and every visible line of text on
    # the day row (the tile's two lines, the title, the context line, the chip) is >= 14px.
    tiles = page.locator(f"{_DAY_ROWS} .date-tile")
    assert tiles.count() == 6
    for box in tiles.evaluate_all(
        "els => els.map(el => { const r = el.getBoundingClientRect(); return [r.width, r.height]; })"
    ):
        assert box[0] >= 44 and box[1] >= 44, box
    for sel in (".date-tile-dow", ".date-tile-num", ".action-row-title", ".action-row-meta",
                ".day-row-chip"):
        sizes = page.eval_on_selector_all(
            f"{_DAY_ROWS} {sel}", "els => els.map(el => parseFloat(getComputedStyle(el).fontSize))"
        )
        assert sizes and min(sizes) >= _FONT_MIN, (sel, sizes)
    # AA for the tile's text on its own (translucent) fill, today's tint included, and for
    # every chip tone on its tint.
    pairs = [
        (".date-tile:not(.is-today) .date-tile-num", ".date-tile:not(.is-today)"),
        (".date-tile.is-today .date-tile-num", ".date-tile.is-today"),
        (".date-tile.is-today .date-tile-dow", ".date-tile.is-today"),
        (".day-row-chip[data-tone='danger']", ".day-row-chip[data-tone='danger']"),
        (".day-row-chip[data-tone='attention']", ".day-row-chip[data-tone='attention']"),
        (".day-row-chip[data-tone='accent']", ".day-row-chip[data-tone='accent']"),
    ]
    for text_sel, fill_sel in pairs:
        text = _style(page, f"{_DAY_ROWS} {text_sel}", "color")
        fill = _style(page, f"{_DAY_ROWS} {fill_sel}", "backgroundColor")
        # The text over the fill, the fill over the card: judge the glyph where it renders.
        assert _contrast(text, fill, card) >= _AA, (text_sel, text, fill)
    # Today is the only tinted tile; the chip tones are three different fills.
    fills = page.eval_on_selector_all(
        f"{_DAY_ROWS} .date-tile", "els => els.map(el => getComputedStyle(el).backgroundColor)"
    )
    assert len(set(fills)) == 2 and fills.count(fills[0]) == 1, fills
    chip_fills = page.eval_on_selector_all(
        f"{_DAY_ROWS} .day-row-chip", "els => els.map(el => getComputedStyle(el).backgroundColor)"
    )
    assert len(set(chip_fills)) == 3, chip_fills


def _assert_day_mark_theme(page: Page) -> None:
    """Every mark's paint holds contrast on the card; a ring does too; nothing is filled."""
    card = _card_bg(page)
    for mark, prop in _MARK_PAINT.items():
        paint = _style(page, f'{_DAY_CELLS} .day-mark[data-mark="{mark}"]', prop)
        assert _contrast(paint, card, card) >= _AA, (mark, paint, card)
    # The ring is non-text graphics: the 3:1 floor.
    for tone in ("danger", "attention"):
        shadow = _style(page, f'{_DAY_CELLS}[data-ring="{tone}"]', "boxShadow")
        ring = re.match(r"(rgba?\([^)]*\))", shadow)
        assert ring and "inset" in shadow, (tone, shadow)
        assert _contrast(ring.group(1), card, card) >= _NON_TEXT_AA, (tone, shadow)
    # No cell is ever filled with a status colour: only today's accent tint is a fill.
    fills = page.eval_on_selector_all(
        _DAY_CELLS, "els => els.map(el => [el.classList.contains('today'),"
        " getComputedStyle(el).backgroundColor])"
    )
    for today, fill in fills:
        assert today or fill == _TRANSPARENT, fill
    # The legend's words are body-sm or larger.
    legend = page.eval_on_selector_all(
        "#demoDayLegendHost li", "els => els.map(el => parseFloat(getComputedStyle(el).fontSize))"
    )
    assert len(legend) == 5 and min(legend) >= _FONT_MIN, legend


def test_day_row_and_day_marks_contract(gallery: Page) -> None:
    """day-row + day-marks (#350, fleet-config#1356): tile floor, text floor, AA, shapes.

    One node for both components and both themes: the suite's node budget is
    ratcheted (.fleet.toml [e2e] test_budget).
    """
    # --- day-row: structure, truncation, the open / read-only split.
    rows = gallery.locator(f"{_DAY_ROWS} .day-row")
    assert rows.count() == 6
    for min_height in rows.evaluate_all("els => els.map(el => el.getBoundingClientRect().height)"):
        assert min_height >= 60  # rows.lg, long text included: nothing wrapped to a second line
    assert gallery.locator(f"{_DAY_ROWS} .day-row-chip").count() == 3  # exceptions only
    assert gallery.locator(f"{_DAY_ROWS} .day-row-chevron").count() == 5  # open rows only
    holiday = gallery.locator(f"{_DAY_ROWS} .day-row[data-day='2026-09-18']")
    assert holiday.locator("button").count() == 0
    assert _style(gallery, f"{_DAY_ROWS} .day-row[data-day='2026-09-18'] .day-row-main", "cursor") == "default"
    # The tile carries the whole date to a screen reader; its two visible lines are hidden.
    first = gallery.locator(f"{_DAY_ROWS} .day-row").first
    assert first.locator(".date-tile-sr").inner_text() == "Monday 14 September"
    assert first.locator(".date-tile-dow").inner_text() == "Mon"
    assert first.locator(".date-tile-num").inner_text() == "14"
    assert first.locator(".day-row-main").get_attribute("aria-current") == "date"
    assert gallery.locator(f"{_DAY_ROWS} [aria-current]").count() == 1
    # The long title and context line stay on one line, ellipsized.
    long_row = gallery.locator(f"{_DAY_ROWS} .day-row[data-day='2026-09-21']")
    for part in (".action-row-title", ".action-row-meta"):
        css = long_row.locator(part).evaluate(
            "el => ({ ws: getComputedStyle(el).whiteSpace, to: getComputedStyle(el).textOverflow,"
            " over: el.scrollWidth > el.clientWidth })"
        )
        assert css == {"ws": "nowrap", "to": "ellipsis", "over": True}, (part, css)
    # The whole open row is the tap target (tile, text, chip and chevron live inside the button).
    assert_min_target(gallery.locator(f"{_DAY_ROWS} button.day-row-main"))
    # Open on click, Enter and Space, once each.
    gallery.evaluate("window.__dayOpened.length = 0")
    button = gallery.locator(f"{_DAY_ROWS} .day-row[data-day='2026-09-15'] button")
    button.click()
    button.focus()
    gallery.keyboard.press("Enter")
    gallery.keyboard.press("Space")
    assert gallery.evaluate("window.__dayOpened") == ["2026-09-15"] * 3
    # A phone width: nothing scrolls sideways.
    gallery.set_viewport_size({"width": 390, "height": 844})
    assert gallery.evaluate(
        "document.documentElement.scrollWidth <= document.documentElement.clientWidth"
    )
    # --- day-marks: five distinct shapes, whatever the colour.
    shapes = gallery.eval_on_selector_all(f"{_DAY_CELLS} .day-mark", _SHAPE_JS)
    assert {s["mark"] for s in shapes} == set(_MARK_PAINT)
    assert len({s["shape"] for s in shapes}) == 5, shapes
    assert gallery.locator("#demoDayLegendHost li").all_inner_texts() == [
        "Booked", "Will book", "Extra day", "Looking", "Not booked on purpose",
    ]
    # An unknown name draws nothing, never a stray shape.
    assert gallery.evaluate(
        "async () => (await import('./day-marks/day-marks.js')).markHtml('bogus')"
    ) == ""
    # Contrast, the floor and the rings, light then dark.
    for theme in ("light", "dark"):
        _set_theme(gallery, theme)
        _assert_day_row_theme(gallery)
        _assert_day_mark_theme(gallery)
