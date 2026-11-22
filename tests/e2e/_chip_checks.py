"""Checks for the chip (toggle pill) component.

Each check takes a freshly loaded `demo.html` gallery; `test_vendored_components.py`
runs them as cases. They pin the contract: the pressed state is the accent-soft fill,
accent border and accent-text label (never a weight change), every label meets AA in
both themes, a chip keeps the 44px hit floor without overlapping a neighbour, and the
group either wraps or scrolls on one line.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from playwright.sync_api import Page, expect

from tests.e2e._cases import Cases
from tests.e2e._color_assertions import contrast as _contrast
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style
from tests.e2e._geometry import assert_min_target, assert_no_horizontal_overflow, assert_no_overlap
from tests.e2e.conftest import load_gallery

_PHONE = {"width": 390, "height": 844}
_AA = 4.5
_PRESSED = "#demoChipGroup .chip[aria-pressed='true']"
_RESTING = "#demoChipNorth"
_COUNT = "#demoChipNorth .chip-count"
_PRESSED_COUNT = "#demoChipAll .chip-count"


def _assert_theme(gallery: Page, *, card: str, ink: str, line: str, accent: str, accent_text: str) -> None:
    """One theme: the resting and pressed chip, each label at AA as rendered over the card."""
    gallery.mouse.move(0, 0)
    assert _style(gallery, _RESTING, "backgroundColor") == card
    assert _style(gallery, _RESTING, "borderTopColor") == line
    assert _style(gallery, _RESTING, "color") == ink
    assert _style(gallery, _PRESSED, "borderTopColor") == accent
    assert _style(gallery, _PRESSED, "color") == accent_text
    fill = _style(gallery, _PRESSED, "backgroundColor")
    assert fill != card and fill != "rgba(0, 0, 0, 0)", "pressed chip has no accent-soft fill"
    # The state is the fill and border: the label weight never moves, so a press shifts no neighbour.
    assert _style(gallery, _PRESSED, "fontWeight") == _style(gallery, _RESTING, "fontWeight")
    for label, background, what in (
        (ink, card, "resting label"),
        (accent_text, fill, "pressed label"),
        (_style(gallery, _COUNT, "color"), card, "resting count"),
        (_style(gallery, _PRESSED_COUNT, "color"), fill, "pressed count"),
    ):
        ratio = _contrast(label, background, card)
        assert ratio >= _AA, f"{what} {ratio:.2f}:1"
    # Unavailable keeps its label colour: the cursor and the title say it, never opacity.
    assert _style(gallery, "#demoChipOff", "opacity") == "1"
    assert _style(gallery, "#demoChipOff", "cursor") == "not-allowed"


def check_chip_pressed_state_in_both_themes(gallery: Page) -> None:
    """chip: card + line at rest, accent-soft + accent + accent-text pressed, AA in light and dark."""
    _assert_theme(gallery, card="rgb(255, 255, 255)", ink="rgb(31, 35, 40)", line="rgb(209, 217, 224)",
                  accent="rgb(9, 105, 218)", accent_text="rgb(5, 80, 174)")
    _set_theme(gallery, "dark")
    _assert_theme(gallery, card="rgb(22, 27, 34)", ink="rgb(230, 237, 243)", line="rgb(48, 54, 61)",
                  accent="rgb(47, 129, 247)", accent_text="rgb(88, 166, 255)")


def check_chip_is_a_pill_that_several_can_press(gallery: Page) -> None:
    """chip: a 36px pill at least 44px wide; the caller flips each chip alone, so two stay pressed."""
    assert _style(gallery, _RESTING, "height") == "36px"
    assert _style(gallery, _RESTING, "borderTopLeftRadius") == "9999px"
    assert _style(gallery, _RESTING, "whiteSpace") == "nowrap"
    assert float(_style(gallery, "#demoChipScroll .chip", "width").removesuffix("px")) >= 44
    expect(gallery.locator(_PRESSED)).to_have_count(2)
    gallery.evaluate("() => document.querySelector('#demoChipNorth').setAttribute('aria-pressed', 'true')")
    expect(gallery.locator(_PRESSED)).to_have_count(3)


def check_chip_group_wraps_and_scroll_group_stays_on_one_line(gallery: Page) -> None:
    """chip-group: wraps onto rows on a phone; --scroll keeps one line and scrolls inside itself."""
    gallery.set_viewport_size(_PHONE)
    tops = {round(box["y"]) for box in gallery.locator("#demoChipGroup .chip").evaluate_all(
        "els => els.map(e => e.getBoundingClientRect().toJSON())")}
    assert len(tops) > 1, "the wrapping group did not wrap at 390px"
    scroll_tops = {round(box["y"]) for box in gallery.locator("#demoChipScroll .chip").evaluate_all(
        "els => els.map(e => e.getBoundingClientRect().toJSON())")}
    assert len(scroll_tops) == 1, "the scroll group wrapped"
    assert gallery.evaluate(
        "() => { const g = document.querySelector('#demoChipScroll'); return g.scrollWidth > g.clientWidth; }"
    ), "the scroll group does not scroll at 390px"
    # The strip scrolls inside its own box: the page itself never gains a sideways scroll.
    assert_no_horizontal_overflow(gallery)


def _check_hit_floor(gallery: Page, base_url: str) -> None:
    """chip: every chip reaches 44px on a coarse pointer and no two targets overlap, wrapped or scrolling."""
    context = gallery.context.browser.new_context(viewport=_PHONE, has_touch=True, is_mobile=True)
    try:
        phone = load_gallery(context.new_page(), base_url)
        assert phone.evaluate("matchMedia('(pointer: coarse)').matches"), "coarse-pointer emulation is not active"
        for group in ("#demoChipGroup", "#demoChipScroll"):
            chips = phone.locator(f"{group} .chip")
            assert_min_target(chips)
            assert_no_overlap(chips)
    finally:
        context.close()


def run_chip_cases(c: Cases, new_gallery: Callable[[], AbstractContextManager[Page]], base_url: str) -> None:
    """Run every chip check as its own case, each on a freshly loaded gallery."""
    for check in (
        check_chip_pressed_state_in_both_themes,
        check_chip_is_a_pill_that_several_can_press,
        check_chip_group_wraps_and_scroll_group_stays_on_one_line,
    ):
        with c.case(check.__name__.removeprefix("check_")), new_gallery() as gallery:
            check(gallery)
    with c.case("chip_meets_the_hit_floor_without_overlap"), new_gallery() as gallery:
        _check_hit_floor(gallery, base_url)
