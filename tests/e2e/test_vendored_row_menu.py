"""Render harness for the row-menu component.

Drives the `demo.html` gallery through the shared `gallery` fixture in `conftest.py`;
split from `test_vendored_components.py` to keep each harness module small.

The placement rule (a phone, the real nav pill) is checked beside it, as a second case.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any

from playwright.sync_api import Browser, Page, expect

from tests.e2e._cases import cases
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style
from tests.e2e._nav_graft import phone_nav

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


# --- placement on a phone (the menu opens where every item is tappable) ---

# Placement of the vendored `row-menu/` on a phone.
#
# The fleet's one ⋮ menu must open where every item is tappable: below its
# kebab, flipped above it when below would run under the floating nav pill (or
# off the screen), clamped with an internal scroll only when neither side fits,
# and re-fitted while it is open. The bug this pins: a menu on the last visible
# row opened under the pill with its lower items untappable (app-launcher#1508,
# local-llm-hub#767), because the placement only knew the viewport edge.
#
# Runs at 390x844 with a coarse pointer, so the real `nav/nav-tabs.css` lays the
# real skeleton out as the fixed bottom pill, over the gallery's tokens. The
# menus are built from the real `row-menu.js` with invented items.

_EDGE = 8

# Build one kebab inside a fixed full-screen scroller (below the pill in
# stacking order), at `y` px down its content, and attach a menu of `count`
# safe rows plus one destructive row. Returns nothing; the kebab is #kebab.
# With `placement`, the kebab sits inside #box (styled by `boxCss`, at `y`) and
# the menu floats against that box with the given side/align/offset/inset.
_BUILD = """
async ([y, count, placement, boxCss]) => {
  const { createRowMenu } = await import('/_vendored/row-menu/row-menu.js');
  document.getElementById('placementScroller')?.remove();
  const scroller = document.createElement('div');
  scroller.id = 'placementScroller';
  scroller.style.cssText = 'position:fixed;inset:0;overflow-y:auto;z-index:100;'
    + 'background:var(--bg)';
  const content = document.createElement('div');
  content.style.cssText = 'position:relative;height:3000px';
  const kebab = document.createElement('button');
  kebab.id = 'kebab';
  kebab.type = 'button';
  kebab.textContent = '⋮';
  kebab.style.cssText = `position:absolute;right:21px;top:${y}px;width:44px;height:44px`;
  if (placement) {
    const box = document.createElement('div');
    box.id = 'box';
    box.style.cssText = `position:absolute;top:${y}px;${boxCss}`;
    kebab.style.cssText = 'position:absolute;right:4px;top:8px;width:44px;height:44px';
    box.appendChild(kebab);
    content.appendChild(box);
    placement.against = () => box;
  } else {
    content.appendChild(kebab);
  }
  scroller.appendChild(content);
  document.body.appendChild(scroller);
  const items = [];
  for (let i = 0; i < count; i++) items.push({ label: `Action ${i + 1}`, glyph: 'pencil', onTap() {} });
  items.push({ label: 'Delete', glyph: 'trash-2', danger: true, onTap() {} });
  createRowMenu(placement ? { placement } : undefined).attach('demo-row', kebab, items);
}
"""

_GEOMETRY = """
() => {
  const r = (el) => { const b = el.getBoundingClientRect();
    return { top: b.top, bottom: b.bottom, left: b.left, right: b.right, height: b.height }; };
  const menu = document.querySelector('.row-menu');
  const rows = Array.from(menu.querySelectorAll('.row-menu-item'));
  const visible = rows.filter((el) => { const b = el.getBoundingClientRect();
    const m = menu.getBoundingClientRect(); return b.top >= m.top && b.bottom <= m.bottom; });
  const hits = visible.map((el) => { const b = el.getBoundingClientRect();
    const hit = document.elementFromPoint((b.left + b.right) / 2, (b.top + b.bottom) / 2);
    return !!hit && hit.closest('.row-menu-item') === el; });
  const box = document.getElementById('box');
  return { menu: r(menu), anchor: r(document.getElementById('kebab')), box: box && r(box),
    width: menu.getBoundingClientRect().width,
    nav: r(document.querySelector('nav.tabs')), vw: innerWidth, vh: innerHeight,
    maxHeight: menu.style.maxHeight, overflowY: menu.style.overflowY,
    scrollable: menu.scrollHeight > menu.clientHeight, allHit: hits.every(Boolean),
    visibleRows: visible.length };
}
"""

# Open a menu on a list row, then rebuild the list the way an app's poll does:
# build the new row and `attach()` it BEFORE it is inserted, swap it in, call
# `endRender()`. Samples the menu and the new kebab synchronously after the swap
# and on each of the next frames.
_REBUILD = """
async () => {
  const { createRowMenu } = await import('/_vendored/row-menu/row-menu.js');
  document.getElementById('placementScroller')?.remove();
  const scroller = document.createElement('div');
  scroller.id = 'placementScroller';
  scroller.style.cssText = 'position:fixed;inset:0;overflow-y:auto;z-index:100;'
    + 'background:var(--bg)';
  const list = document.createElement('div');
  list.style.cssText = 'position:relative;height:3000px;padding:300px 21px 0';
  scroller.appendChild(list);
  document.body.appendChild(scroller);
  const rowMenu = createRowMenu();
  const build = () => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;justify-content:flex-end';
    const kebab = document.createElement('button');
    kebab.type = 'button';
    kebab.className = 'rebuilt-kebab';
    kebab.textContent = '⋮';
    kebab.style.cssText = 'width:44px;height:44px';
    row.appendChild(kebab);
    rowMenu.attach('demo-row', kebab, [
      { label: 'Action 1', glyph: 'pencil', onTap() {} },
      { label: 'Delete', glyph: 'trash-2', danger: true, onTap() {} },
    ]);
    return row;
  };
  list.replaceChildren(build());
  list.querySelector('.rebuilt-kebab').click();
  const frame = () => new Promise((r) => requestAnimationFrame(r));
  await frame();
  list.replaceChildren(build());
  rowMenu.endRender();
  const samples = [];
  const sample = () => {
    const menu = document.querySelector('.row-menu');
    const kebab = list.querySelector('.rebuilt-kebab');
    const rect = (el) => { const b = el.getBoundingClientRect();
      return { top: b.top, bottom: b.bottom, left: b.left, right: b.right }; };
    samples.push({ visibility: getComputedStyle(menu).visibility, menu: rect(menu),
      anchor: rect(kebab), connected: menu.isConnected,
      focusInMenu: menu.contains(document.activeElement) });
  };
  sample();
  for (let i = 0; i < 4; i++) { await frame(); sample(); }
  return samples;
}
"""


@contextmanager
def _phone(static_server: str, browser: Browser) -> Iterator[Page]:
    """The gallery (for its tokens) with the real nav pill, at 390x844, touch."""
    with phone_nav(browser, static_server) as page:
        # Boot check, not a skip: without the fixed pill every assertion below
        # would pass against a bare viewport and prove nothing.
        assert _style(page, "nav.tabs", "position") == "fixed", (
            "the nav did not lay out as the fixed phone pill — coarse-pointer "
            "emulation is off, so this harness would assert nothing"
        )
        yield page


def _open(
    page: Page,
    y: int,
    count: int = 2,
    scroll: int = 0,
    placement: dict[str, Any] | None = None,
    box_css: str = "",
) -> dict[str, Any]:
    """Close any open menu, build a kebab at content offset `y` with the
    scroller at `scroll` (inside a `box_css` box the menu floats against, when
    `placement` is given), open its menu, and return the geometry."""
    page.keyboard.press("Escape")
    page.evaluate(_BUILD, [y, count, placement, box_css])
    page.evaluate("(t) => { document.getElementById('placementScroller').scrollTop = t; }", scroll)
    page.click("#kebab")
    page.wait_for_selector(".row-menu")
    geo: dict[str, Any] = page.evaluate(_GEOMETRY)
    return geo


def _assert_in_band(geo: dict[str, Any]) -> None:
    """The whole menu sits on screen, clear of the pill, every row tappable."""
    menu, nav = geo["menu"], geo["nav"]
    assert menu["top"] >= _EDGE - 0.5, geo
    assert menu["bottom"] <= nav["top"] - _EDGE + 0.5, geo
    assert menu["left"] >= _EDGE - 0.5 and menu["right"] <= geo["vw"] - _EDGE + 0.5, geo
    assert geo["allHit"], geo


def _assert_default_placement_and_fleet_size(phone: Page) -> None:
    """A row near the top keeps the default, and the menu has the fleet size."""
    # 1. A row near the top keeps the default: below, right edges aligned.
    geo = _open(phone, 120)
    menu, anchor = geo["menu"], geo["anchor"]
    assert menu["top"] >= anchor["bottom"], geo
    assert abs(menu["right"] - anchor["right"]) <= 1, geo
    _assert_in_band(geo)

    # The fleet size: body text at weight 500, a 16px glyph, 44px rows, 10px
    # gap, 12px side padding, stacked in front of the pill.
    row = ".row-menu-item"
    assert _style(phone, row, "fontSize") == "16px"
    assert _style(phone, row, "fontWeight") == "500"
    assert _style(phone, row, "columnGap") == "10px"
    assert _style(phone, row, "paddingLeft") == "12px"
    assert _style(phone, row, "paddingRight") == "12px"
    assert _style(phone, f"{row} .icon", "width") == "16px"
    assert phone.eval_on_selector(row, "el => el.getBoundingClientRect().height") >= 44
    assert int(_style(phone, ".row-menu", "zIndex")) > int(_style(phone, "nav.tabs", "zIndex"))


def _assert_flips_and_clamps(phone: Page, nav_top: int, near_pill: int) -> None:
    """Above the pill, re-fitted on scroll, and clamped with an internal scroll."""
    # 2. The last visible row: below fits the viewport but runs under the pill,
    # so the menu opens above its kebab, uncapped.
    geo = _open(phone, near_pill)
    menu, anchor = geo["menu"], geo["anchor"]
    below_bottom = anchor["bottom"] + 2 + menu["height"]
    assert nav_top - _EDGE < below_bottom <= geo["vh"] - _EDGE, geo  # the precondition
    assert menu["bottom"] <= anchor["top"], geo
    assert geo["maxHeight"] == "", geo
    _assert_in_band(geo)

    # 3. Opened below a row near the top, then the row scrolls down to the pill:
    # the open menu flips.
    y = 900
    geo = _open(phone, y, scroll=y - 100)
    assert geo["menu"]["top"] >= geo["anchor"]["bottom"], geo
    phone.evaluate(
        "(t) => { document.getElementById('placementScroller').scrollTop = t; }", y - near_pill
    )
    # Two animation frames: the scroll event, then the re-fit it schedules.
    phone.evaluate("() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    geo = phone.evaluate(_GEOMETRY)
    assert abs(geo["anchor"]["top"] - near_pill) <= 1, geo
    assert geo["menu"]["bottom"] <= geo["anchor"]["top"], geo
    _assert_in_band(geo)

    # 4. Too tall for either side: clamped to the band, scrolling inside.
    geo = _open(phone, 300, count=20)
    assert geo["maxHeight"] != "" and geo["overflowY"] == "auto", geo
    assert geo["scrollable"], geo
    _assert_in_band(geo)


def _assert_floats_against_another_element(phone: Page, nav_top: int) -> None:
    """The composer shape (above a box) and the sessions shape (left of a rail)."""
    # 5. Floated against another element than the kebab (#362), the composer
    # shape: above a wide box, right edges 10px in, 6px off it, 260px wide.
    above = {"side": "above", "align": "end", "offset": 6, "inset": 10, "minWidth": 260}
    composer = "left:16px;right:16px;height:60px"
    geo = _open(phone, 400, placement=above, box_css=composer)
    menu, box = geo["menu"], geo["box"]
    assert abs(menu["bottom"] - (box["top"] - 6)) <= 1, geo
    assert abs(menu["right"] - (box["right"] - 10)) <= 1, geo
    assert geo["width"] >= 260, geo
    _assert_in_band(geo)
    # No room above it near the top of the screen: mirrored below the box.
    geo = _open(phone, 20, placement=above, box_css=composer)
    assert abs(geo["menu"]["top"] - (geo["box"]["bottom"] + 6)) <= 1, geo
    _assert_in_band(geo)

    # 6. The sessions shape: left of the row's button rail, top-aligned, 4px
    # over it; on the last visible row, mirrored to bottom-aligned, off the pill.
    left = {"side": "left", "align": "start", "offset": -4}
    rail = "right:21px;width:52px;height:88px"
    geo = _open(phone, 120, placement=left, box_css=rail)
    menu, box = geo["menu"], geo["box"]
    assert abs(menu["top"] - box["top"]) <= 1, geo
    assert abs(menu["right"] - (box["left"] + 4)) <= 1, geo
    _assert_in_band(geo)
    geo = _open(phone, nav_top - 100, placement=left, box_css=rail)
    menu, box = geo["menu"], geo["box"]
    assert box["top"] + menu["height"] > nav_top - _EDGE, geo  # the precondition
    assert abs(menu["bottom"] - box["bottom"]) <= 1, geo
    _assert_in_band(geo)


def _assert_survives_a_list_rebuild(phone: Page) -> None:
    """A polled list rebuilt under an open menu never paints it at the viewport inset."""
    # 7. A polled list is rebuilt under an open menu (#373): the new row is
    # attached before it is inserted, as the README's example does. The menu
    # must never paint at the viewport inset, and settles beside the new kebab.
    phone.keyboard.press("Escape")  # the step-6 menu is still open
    samples = phone.evaluate(_REBUILD)
    assert len(samples) >= 3, samples
    for s in samples:
        if s["visibility"] == "hidden":
            continue
        assert s["menu"]["top"] >= s["anchor"]["bottom"], samples
        assert abs(s["menu"]["right"] - s["anchor"]["right"]) <= 1, samples
    assert samples[-1]["visibility"] == "visible", samples
    assert samples[-1]["connected"], samples
    assert samples[-1]["focusInMenu"], samples


def _check_row_menu_contract(gallery: Page) -> None:
    """row-menu: opens on the kebab, isn't clipped by a sideways scroller, closes
    on outside tap / Escape / choosing, follows the menu-button keyboard pattern,
    and re-skins in dark; the items are the caller's data. The options: a
    header line, brand marks, a screen-reader name apart from the caption, and
    a menu floated to the left of another element than its kebab."""
    _assert_wired_to_the_kebab(gallery)
    _assert_light_surface(gallery)
    _assert_not_clipped(gallery)
    _assert_keyboard_pattern(gallery)
    _assert_closes_and_chooses(gallery)
    _assert_dark_surface(gallery)
    _assert_options(gallery)


def _check_row_menu_placement_and_size_on_a_phone(phone: Page) -> None:
    """The whole placement rule: below when it fits, above the pill when below would run under it, re-fitted
    when an open menu's row scrolls down to the pill, clamped with an internal
    scroll when neither side fits — and the fleet size, in front of the pill.
    Then the same rule for a menu floated against another element on another
    side (#362): above a composer-like box, and left of a row's button rail."""
    nav_top = int(phone.evaluate(
        "() => document.querySelector('nav.tabs').getBoundingClientRect().top"
    ))
    # Room for the menu between this kebab and the pill, though not the viewport
    # edge: the case the viewport-only rule got wrong.
    near_pill = nav_top - 150
    _assert_default_placement_and_fleet_size(phone)
    _assert_flips_and_clamps(phone, nav_top, near_pill)
    _assert_floats_against_another_element(phone, nav_top)
    _assert_survives_a_list_rebuild(phone)


def test_row_menu_contract(
    new_gallery: Callable[[], AbstractContextManager[Page]], static_server: str, browser: Browser
) -> None:
    """The row-menu contract on the gallery, and its placement on a phone."""
    with cases() as c:
        with c.case("row_menu_contract"), new_gallery() as gallery:
            _check_row_menu_contract(gallery)
        with c.case("row_menu_placement_and_size_on_a_phone"), _phone(static_server, browser) as phone:
            _check_row_menu_placement_and_size_on_a_phone(phone)
