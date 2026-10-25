"""Render harness for the row-menu component.

Drives the `demo.html` gallery through the shared `gallery` fixture in `conftest.py`;
split from `test_vendored_components.py` to keep each harness module small.
"""

from __future__ import annotations

from playwright.sync_api import Page, expect

from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style


_ROW_MENU_KEBAB = "#demoRowMenuKebab"
_ROW_MENU = ".row-menu"
_ROW_MENU_CHOSEN = "#demoRowMenuChosen"
_ROW_ITEM = ".row-menu-item"


def _row_menu_labels(page: Page) -> list[str]:
    """The captions of the open menu's rows, in order."""
    return page.eval_on_selector_all(
        f"{_ROW_MENU} .row-menu-label", "els => els.map(e => e.textContent)"
    )


def _focused_label(page: Page) -> str:
    """The caption of the menu row holding focus ('' when focus is elsewhere)."""
    return page.evaluate(
        "() => { const el = document.activeElement;"
        " return el && el.classList.contains('row-menu-item') ? el.textContent : ''; }"
    )


def _assert_wired_to_the_kebab(gallery: Page) -> None:
    """Open on the kebab: ARIA wiring, row kinds, the single tab stop, a disabled row."""
    kebab = gallery.locator(_ROW_MENU_KEBAB)
    menu = gallery.locator(_ROW_MENU)
    expect(menu).to_have_count(0)
    # The anchor is wired for the menu-button pattern.
    expect(kebab).to_have_attribute("aria-haspopup", "menu")
    expect(kebab).to_have_attribute("aria-expanded", "false")

    # Open on the kebab: the hidden item is absent, the destructive one is last
    # behind a divider, and focus lands on the first row (the only tab stop).
    kebab.click()
    expect(menu).to_be_visible()
    expect(kebab).to_have_attribute("aria-expanded", "true")
    expect(kebab).to_have_attribute("aria-controls", menu.get_attribute("id") or "")
    expect(menu).to_have_attribute("role", "menu")
    assert _row_menu_labels(gallery) == ["Rename", "Archive", "Delete"]
    kinds = gallery.eval_on_selector_all(
        f"{_ROW_MENU} > *", "els => els.map(e => e.getAttribute('role'))"
    )
    assert kinds == ["menuitem", "menuitem", "separator", "menuitem"], kinds
    assert _focused_label(gallery) == "Rename"
    tab_stops = gallery.eval_on_selector_all(
        f"{_ROW_MENU} .row-menu-item", "els => els.filter(e => e.tabIndex === 0).length"
    )
    assert tab_stops == 1
    # A disabled row stays focusable and says why; it is flat muted text.
    expect(gallery.locator(".row-menu-item", has_text="Archive")).to_have_attribute(
        "aria-disabled", "true"
    )
    expect(gallery.locator(".row-menu-item", has_text="Archive")).to_have_attribute(
        "title", "Nothing to archive"
    )


def _assert_light_surface(gallery: Page) -> None:
    """The light surface and the row states."""
    # Light surface and states.
    assert _style(gallery, _ROW_MENU, "position") == "fixed"
    assert _style(gallery, _ROW_MENU, "backgroundColor") == "rgb(246, 248, 250)"  # --card-2
    assert _style(gallery, _ROW_MENU, "borderTopColor") == "rgb(209, 217, 224)"  # --line
    assert _style(gallery, _ROW_MENU, "borderTopLeftRadius") == "12px"
    assert _style(gallery, _ROW_MENU, "boxShadow") != "none"
    assert _style(gallery, _ROW_ITEM, "color") == "rgb(31, 35, 40)"
    assert _style(gallery, ".row-menu-danger", "color") == "rgb(164, 14, 38)"  # --danger-text
    assert _style(gallery, '.row-menu-item[aria-disabled="true"]', "color") == "rgb(101, 109, 118)"
    assert gallery.eval_on_selector(_ROW_ITEM, "el => el.getBoundingClientRect().height") >= 44


def _assert_not_clipped(gallery: Page) -> None:
    """Not clipped by a sideways scroller, and the last row is what a hit test finds."""
    # Not clipped: the scroller is 96px tall with overflow-x (so overflow-y clips
    # an absolute child), yet the menu is fully on screen and extends past it,
    # and its last row is what a hit test finds at its centre.
    geo = gallery.evaluate(
        "() => { const s = document.getElementById('demoRowMenuScroller').getBoundingClientRect();"
        " const m = document.querySelector('.row-menu').getBoundingClientRect();"
        " const last = document.querySelector('.row-menu-danger').getBoundingClientRect();"
        " const hit = document.elementFromPoint((last.left + last.right) / 2,"
        " (last.top + last.bottom) / 2);"
        " return { menuBottom: m.bottom, scrollerBottom: s.bottom, top: m.top, left: m.left,"
        " right: m.right, vw: innerWidth, vh: innerHeight,"
        " hitIsRow: !!hit && hit.closest('.row-menu-danger') !== null }; }"
    )
    assert geo["menuBottom"] > geo["scrollerBottom"], geo
    assert geo["top"] >= 0 and geo["left"] >= 0, geo
    assert geo["right"] <= geo["vw"] and geo["menuBottom"] <= geo["vh"], geo
    assert geo["hitIsRow"], geo


def _assert_keyboard_pattern(gallery: Page) -> None:
    """Arrow keys, Home / End, Escape, and ArrowUp on the anchor."""
    kebab = gallery.locator(_ROW_MENU_KEBAB)
    menu = gallery.locator(_ROW_MENU)
    # Keyboard: arrows move (a disabled row is reachable) and wrap; Home / End jump.
    gallery.keyboard.press("ArrowDown")
    assert _focused_label(gallery) == "Archive"
    gallery.keyboard.press("ArrowDown")
    assert _focused_label(gallery) == "Delete"
    gallery.keyboard.press("ArrowDown")
    assert _focused_label(gallery) == "Rename"
    gallery.keyboard.press("End")
    assert _focused_label(gallery) == "Delete"
    gallery.keyboard.press("Home")
    assert _focused_label(gallery) == "Rename"

    # Escape closes, and focus returns to the kebab.
    gallery.keyboard.press("Escape")
    expect(menu).to_have_count(0)
    expect(kebab).to_have_attribute("aria-expanded", "false")
    expect(kebab).to_be_focused()

    # ArrowUp on the anchor opens on the last row.
    gallery.keyboard.press("ArrowUp")
    expect(menu).to_be_visible()
    assert _focused_label(gallery) == "Delete"
    gallery.keyboard.press("Escape")


def _assert_closes_and_chooses(gallery: Page) -> None:
    """Closing on a second tap / outside press, and choosing a disabled and a live row."""
    kebab = gallery.locator(_ROW_MENU_KEBAB)
    menu = gallery.locator(_ROW_MENU)
    # A second tap of the kebab closes; a press outside closes.
    kebab.click()
    expect(menu).to_be_visible()
    kebab.click()
    expect(menu).to_have_count(0)
    kebab.click()
    gallery.click("h2 >> nth=0")
    expect(menu).to_have_count(0)
    expect(kebab).to_have_attribute("aria-expanded", "false")

    # Choosing a disabled row does nothing and keeps the menu open.
    kebab.click()
    # `force`: Playwright treats aria-disabled as not actionable, but a real tap lands.
    gallery.click(".row-menu-item >> text=Archive", force=True)
    expect(menu).to_be_visible()
    assert gallery.text_content(_ROW_MENU_CHOSEN) == "Chosen: none"
    # Choosing a live row closes the menu, runs its action, focus back on the kebab.
    gallery.click(".row-menu-item >> text=Rename")
    expect(menu).to_have_count(0)
    assert gallery.text_content(_ROW_MENU_CHOSEN) == "Chosen: Rename"
    expect(kebab).to_be_focused()


def _assert_dark_surface(gallery: Page) -> None:
    """The same menu on the dark surface."""
    kebab = gallery.locator(_ROW_MENU_KEBAB)
    menu = gallery.locator(_ROW_MENU)
    # Dark: the same menu on the dark surface.
    kebab.click()
    _set_theme(gallery, "dark")
    assert _style(gallery, _ROW_MENU, "backgroundColor") == "rgb(33, 38, 45)"  # --card-2
    assert _style(gallery, _ROW_MENU, "borderTopColor") == "rgb(48, 54, 61)"
    assert _style(gallery, _ROW_ITEM, "color") == "rgb(230, 237, 243)"
    assert _style(gallery, ".row-menu-danger", "color") == "rgb(255, 123, 114)"
    assert _style(gallery, '.row-menu-item[aria-disabled="true"]', "color") == "rgb(125, 133, 144)"
    gallery.keyboard.press("Escape")
    expect(menu).to_have_count(0)
    _set_theme(gallery, "")


def _assert_options(gallery: Page) -> None:
    """The options (#362): no header by default, then a header, brand marks and a floated menu."""
    kebab = gallery.locator(_ROW_MENU_KEBAB)
    menu = gallery.locator(_ROW_MENU)
    # No header asked for, none drawn, and the caption is the accessible name.
    kebab.click()
    expect(gallery.locator(".row-menu-head")).to_have_count(0)
    assert gallery.get_attribute(_ROW_MENU, "aria-describedby") is None
    assert gallery.get_attribute(".row-menu-item >> nth=0", "aria-label") is None
    gallery.keyboard.press("Escape")

    # The options menu: left of the kebab's rail, top-aligned, 4px over it.
    gallery.click("#demoRowMenuKebab2")
    expect(menu).to_be_visible()
    geo = gallery.evaluate(
        "() => { const r = document.getElementById('demoRowMenuRail').getBoundingClientRect();"
        " const m = document.querySelector('.row-menu').getBoundingClientRect();"
        " return { menuTop: m.top, menuRight: m.right, railTop: r.top, railLeft: r.left }; }"
    )
    assert abs(geo["menuTop"] - geo["railTop"]) <= 1, geo
    assert abs(geo["menuRight"] - (geo["railLeft"] + 4)) <= 1, geo
    # The header: first, muted, not an item (arrow keys and the row count skip it),
    # and it describes the menu.
    head = gallery.locator(".row-menu-head")
    expect(head).to_have_text("Invented row · pid 4242")
    kinds = gallery.eval_on_selector_all(
        f"{_ROW_MENU} > *", "els => els.map(e => e.getAttribute('role'))"
    )
    assert kinds == ["presentation", "menuitem", "menuitem", "menuitem"], kinds
    expect(menu).to_have_attribute("aria-describedby", head.get_attribute("id") or "")
    # The header takes --ink, not --muted (#398): muted is 4.08:1 on the dark menu
    # surface. It stays the quieter line by weight (400 against the items' 500).
    assert _style(gallery, ".row-menu-head", "color") == "rgb(31, 35, 40)"  # --ink
    assert _style(gallery, ".row-menu-head", "fontWeight") == "400"
    _set_theme(gallery, "dark")
    assert _style(gallery, ".row-menu-head", "color") == "rgb(230, 237, 243)"  # --ink
    _set_theme(gallery, "light")
    assert _focused_label(gallery) == "Open"
    gallery.keyboard.press("ArrowUp")
    assert _focused_label(gallery) == "Other app"
    # The screen-reader name is the item's own, the caption stays short.
    expect(gallery.get_by_role("menuitem", name="Open the demo row")).to_have_text("Open")
    # Brand marks: the caller's symbol at 18px, greyed only while disabled.
    brand = ".row-menu-brand"
    assert gallery.eval_on_selector_all(
        brand, "els => els.map(e => e.querySelector('use').getAttribute('href'))"
    ) == ["#b-demo", "#b-demo"]
    assert _style(gallery, brand, "width") == "18px"
    assert _style(gallery, brand, "filter") == "none"
    assert _style(gallery, f'.row-menu-item[aria-disabled="true"] {brand}', "filter") == "grayscale(1)"
    gallery.keyboard.press("Escape")
    expect(menu).to_have_count(0)

def test_row_menu_contract(gallery: Page) -> None:
    """row-menu: opens on the kebab, isn't clipped by a sideways scroller, closes
    on outside tap / Escape / choosing, follows the menu-button keyboard pattern,
    and re-skins in dark; the items are the caller's data. The options (#362)
    ride in the same node (the suite is over its budget): a header line, brand
    marks, a screen-reader name apart from the caption, and a menu floated to
    the left of another element than its kebab."""
    _assert_wired_to_the_kebab(gallery)
    _assert_light_surface(gallery)
    _assert_not_clipped(gallery)
    _assert_keyboard_pattern(gallery)
    _assert_closes_and_chooses(gallery)
    _assert_dark_surface(gallery)
    _assert_options(gallery)
