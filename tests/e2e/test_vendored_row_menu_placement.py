"""Placement harness for the vendored `row-menu/` on a phone (issue #362).

The fleet's one ⋮ menu must open where every item is tappable: below its
kebab, flipped above it when below would run under the floating nav pill (or
off the screen), clamped with an internal scroll only when neither side fits,
and re-fitted while it is open. The bug this pins: a menu on the last visible
row opened under the pill with its lower items untappable (app-launcher#1508,
local-llm-hub#767), because the placement only knew the viewport edge.

Runs at 390x844 with a coarse pointer, so the real `nav/nav-tabs.css` lays the
real skeleton out as the fixed bottom pill, over the gallery's tokens. The
menus are built from the real `row-menu.js` with invented items.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from playwright.sync_api import Browser, Page

from tests.e2e._color_assertions import style as _style
from tests.e2e.conftest import STATIC_DIR

NAV_DIR = STATIC_DIR / "_vendored" / "nav"
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


@pytest.fixture()
def phone(static_server: str, browser: Browser) -> Iterator[Page]:
    """The gallery (for its tokens) with the real nav pill, at 390x844, touch."""
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    try:
        page.goto(f"{static_server}/_vendored/demo.html")
        page.wait_for_selector("body[data-demo-ready='1']")
        page.add_style_tag(url=f"{static_server}/_vendored/nav/nav-tabs.css")
        skeleton = (NAV_DIR / "nav-tabs.html").read_text(encoding="utf-8")
        page.evaluate("(html) => document.body.insertAdjacentHTML('afterbegin', html)", skeleton)
        # Boot check, not a skip: without the fixed pill every assertion below
        # would pass against a bare viewport and prove nothing.
        assert _style(page, "nav.tabs", "position") == "fixed", (
            "the nav did not lay out as the fixed phone pill — coarse-pointer "
            "emulation is off, so this harness would assert nothing"
        )
        yield page
    finally:
        context.close()


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


def test_row_menu_placement_and_size_on_a_phone(phone: Page) -> None:
    """One node for the whole placement rule (the suite is over its budget):
    below when it fits, above the pill when below would run under it, re-fitted
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
