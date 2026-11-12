"""Checks for the nav's "no tab active" state, run as cases of `test_vendored_nav.py`.

A screen that is not a tab (Settings, an archive) must be able to say that no
tab is open: `setTab(null)` clears the accent, `aria-selected` and the phone
pill's capsule, and the nav keeps that state, through a re-layout, until the
next real selection.
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

# The same init as the slide checks: the real initNavTabs, onChange recorded.
from tests.e2e._nav_slide_checks import _INIT_JS

_STATE_JS = """() => {
  const nav = document.querySelector('.tabs');
  const pill = nav.querySelector('.tab-pill');
  const names = (selector) => [...nav.querySelectorAll(selector)].map((tab) => tab.dataset.tab);
  return {
    current: window.__nav.getTab(),
    open: nav.dataset.activeTab ?? null,
    accent: names('.tab.active'),
    selected: names('.tab[aria-selected="true"]'),
    stops: names('.tab[tabindex="0"]'),
    capsule: getComputedStyle(pill).display !== 'none' && getComputedStyle(pill).visibility === 'visible',
  };
}"""


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate(_STATE_JS)


def _assert_no_tab(page: Page, where: str) -> None:
    state = _state(page)
    assert state["current"] is None and state["open"] is None, (where, state)
    assert state["accent"] == [] and state["selected"] == [], (where, state)
    assert not state["capsule"], (where, state)
    # The bar stays reachable from the keyboard: exactly one tab stop.
    assert len(state["stops"]) == 1, (where, state)


def check_set_tab_null_leaves_no_tab_active(page: Page, pill: bool) -> None:
    """Select a tab, then no tab: nothing is active, through a re-layout, until a real selection."""
    page.evaluate(_INIT_JS)
    page.evaluate("() => window.__nav.setTab('stats')")
    state = _state(page)
    assert state["accent"] == ["stats"] and state["capsule"] is pill, state

    page.evaluate("() => window.__nav.setTab(null)")
    _assert_no_tab(page, "after setTab(null)")
    # Not a switch: the app that opened the screen owns onChange.
    assert page.evaluate("() => window.__changes") == ["home", "stats"]

    # A cell re-layout (the capsule's ResizeObserver) does not bring a tab back.
    page.evaluate("() => { document.querySelector('.tabs').style.maxWidth = '240px'; }")
    page.wait_for_timeout(100)
    _assert_no_tab(page, "after a re-layout")

    page.evaluate("() => window.__nav.setTab('history')")
    state = _state(page)
    assert state["current"] == "history" and state["open"] == "history", state
    assert state["accent"] == ["history"] and state["selected"] == ["history"], state
    assert state["stops"] == ["history"] and state["capsule"] is pill, state
