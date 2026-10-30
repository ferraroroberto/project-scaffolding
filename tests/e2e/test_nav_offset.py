"""Floating bottom-tab bar geometry per tab on a 390x844 phone.

An installed iOS app anchors `position: fixed` to the physical screen bottom
only while the document is scrollable, so a tab shorter than the screen left
the bar floating higher than on the first tab. Desktop engines don't reproduce
that anchoring, so beyond the bar's measured offset this pins the mechanism that
prevents it: every tab's document scrolls by at least 1px. It also pins the
scroll-edge fade bands at the top and under the bar. Run on both engines:
`pytest tests/e2e/test_nav_offset.py --browser chromium --browser webkit`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page

from tests.e2e._nav_graft import phone_nav

_TABS = ("home", "stats", "history")

# The panes are left empty so every tab is far shorter than the screen, the case
# that used to float the bar; the gallery the skeleton is grafted onto is hidden
# for the same reason.
_SHORT_TABS_JS = """() => {
  document.querySelectorAll('body > :not(.tabs):not(.app)')
    .forEach((e) => { e.style.display = 'none'; });
}"""

_MEASURE_JS = """() => {
  const bar = document.querySelector('.tabs').getBoundingClientRect();
  const root = document.scrollingElement;
  return {
    pill: matchMedia('(pointer: coarse) and (max-width: 520px)').matches,
    barBottomOffset: window.innerHeight - bar.bottom,
    overflow: root.scrollHeight - root.clientHeight,
  };
}"""

_FADE_JS = """pseudo => {
  const s = getComputedStyle(document.body, pseudo);
  const bar = getComputedStyle(document.querySelector('.tabs'));
  return {
    position: s.position, top: s.top, bottom: s.bottom, height: parseFloat(s.height),
    image: s.backgroundImage, pointerEvents: s.pointerEvents,
    z: Number(s.zIndex), barZ: Number(bar.zIndex),
  };
}"""


@pytest.fixture()
def nav_phone(static_server: str, browser: Browser) -> Iterator[Page]:
    """The real `initNavTabs` on the phone pill, over short (empty) tabs."""
    with phone_nav(browser, static_server) as page:
        page.evaluate(_SHORT_TABS_JS)
        page.evaluate(
            "async () => { const m = await import('/_vendored/nav/nav-tabs.js');"
            " window.__nav = m.initNavTabs(); }"
        )
        yield page


def test_bar_sits_at_the_same_offset_on_every_tab(nav_phone: Page) -> None:
    page = nav_phone
    offsets: dict[str, float] = {}
    for tab in _TABS:
        page.locator(f".tabs .tab[data-tab='{tab}']").click()
        page.wait_for_selector(f".tabs .tab[data-tab='{tab}'].active")
        m = page.evaluate(_MEASURE_JS)
        assert m["pill"], m
        # The scrollable document is what keeps iOS anchoring the bar to the
        # screen bottom on a short tab.
        assert m["overflow"] >= 1, (tab, m)
        offsets[tab] = round(m["barBottomOffset"], 1)

    assert offsets["home"] == 21, offsets
    assert set(offsets.values()) == {offsets["home"]}, offsets


def test_scroll_edge_fades_top_and_bottom(nav_phone: Page) -> None:
    page = nav_phone

    bottom = page.evaluate(_FADE_JS, "::before")
    assert bottom["position"] == "fixed", bottom
    assert bottom["bottom"] == "0px", bottom
    # 16px lead-in above the bar + the 61px bar + its 21px bottom margin.
    assert bottom["height"] == 98, bottom

    top = page.evaluate(_FADE_JS, "::after")
    assert top["position"] == "fixed", top
    assert top["top"] == "0px", top
    # The eased tail under the status bar, inside the 4px .app top padding.
    assert top["height"] == 4, top

    for fade in (bottom, top):
        assert "linear-gradient" in fade["image"], fade
        assert fade["pointerEvents"] == "none", fade
        assert fade["z"] < fade["barZ"], fade


def test_installed_app_anchors_the_bar_from_the_large_viewport_top(
    nav_phone: Page, browser_name: str
) -> None:
    """In the installed app iOS grows the viewport after launch, so the bar is
    placed from the top with 100lvh (its final position on frame one) rather
    than from the moving bottom edge. No engine here emulates the standalone
    display mode, so the nav's own standalone rules are applied unconditionally."""
    page = nav_phone
    if browser_name != "chromium":
        pytest.skip("the standalone rules are applied through a constructed stylesheet; Chromium only")

    m = page.evaluate("""() => {
      const found = [];
      const walk = rules => {
        for (const r of rules) {
          if (r.media && r.conditionText.includes('display-mode: standalone')) found.push(r);
          else if (r.cssRules) walk(r.cssRules);
        }
      };
      for (const sheet of document.styleSheets) {
        if (sheet.href && sheet.href.includes('nav-tabs.css')) walk(sheet.cssRules);
      }
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(found.map(r => Array.from(r.cssRules, c => c.cssText).join(' ')).join(' '));
      document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
      // Grow the bar: a top-anchored bar keeps its top edge, a bottom-anchored
      // one keeps its bottom edge.
      const bar = document.querySelector('.tabs');
      const before = bar.getBoundingClientRect();
      bar.style.height = (before.height + 40) + 'px';
      const after = bar.getBoundingClientRect();
      bar.style.height = '';
      return { blocks: found.length, topBefore: before.top, topAfter: after.top, lvh: innerHeight };
    }""")
    assert m["blocks"] == 1, m
    assert m["topAfter"] == m["topBefore"], m
    # 21px margin + 61px bar above the large-viewport bottom.
    assert m["topBefore"] == m["lvh"] - 82, m


def test_document_stays_scrollable_with_the_body_pinned(nav_phone: Page) -> None:
    """An app-side scroll lock pins the body while a dialog is open; if that left
    the document unscrollable, an installed iOS app would shrink its viewport and
    re-grow it over ~3s on close, revealing the bar bit by bit."""
    page = nav_phone
    page.evaluate(
        "() => { const b = document.body; b.style.position = 'fixed';"
        " b.style.top = '0'; b.style.left = '0'; b.style.right = '0'; b.style.width = '100%'; }"
    )
    overflow = page.evaluate(
        "() => document.scrollingElement.scrollHeight - document.scrollingElement.clientHeight"
    )
    assert overflow >= 1, overflow
