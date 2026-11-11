"""Checks for press-and-slide on the nav's phone pill, run as cases of `test_vendored_nav.py`.

The slide is pointer-event code: a press that moves 8px becomes a slide, the
capsule follows the finger, the tab under it takes the accent, and lifting
chooses it. It captures the pointer, and capture needs a live pointer id, so a
synthetic `PointerEvent` cannot stand in: every touch here goes through
Chromium's own input pipeline (`Input.dispatchTouchEvent`), the path a finger
takes.

At rest the capsule sits at the active tab's own `offsetLeft` and
`offsetWidth`, whole pixels; the checks assert it returns there after every
slide, because that placement is what keeps the pill's pixels the same as
before the slide existed (the screenshot baseline holds the pixels themselves).
"""

from __future__ import annotations

from typing import Any

from playwright.sync_api import Page

from tests.e2e._color_assertions import style

# nav-tabs.js: a press that wanders less than this is still a tap.
_SLOP_PX = 8

_INIT_JS = """async () => {
  const m = await import('/_vendored/nav/nav-tabs.js');
  window.__changes = [];
  window.__nav = m.initNavTabs({ onChange: (tab) => window.__changes.push(tab) });
}"""

_STATE_JS = """() => {
  const nav = document.querySelector('.tabs');
  const pill = nav.querySelector('.tab-pill');
  const names = (selector) => [...nav.querySelectorAll(selector)].map((tab) => tab.dataset.tab);
  return {
    open: nav.dataset.activeTab,
    accent: names('.tab.active'),
    selected: names('.tab[aria-selected="true"]'),
    sliding: nav.classList.contains('sliding'),
    x: pill.style.getPropertyValue('--pill-x'),
    w: pill.style.getPropertyValue('--pill-w'),
    cells: Object.fromEntries(
      [...nav.querySelectorAll('.tab')].map((tab) => [tab.dataset.tab, [tab.offsetLeft, tab.offsetWidth]])),
    shown: [...document.querySelectorAll('.pane')].filter((pane) => !pane.hidden).map((pane) => pane.id),
    changes: window.__changes.slice(),
    scrollY: window.scrollY,
  };
}"""


class _Finger:
    """One finger on the page, sent through Chromium's touch pipeline."""

    def __init__(self, page: Page) -> None:
        self._page = page
        self._cdp = page.context.new_cdp_session(page)

    def _send(self, kind: str, at: tuple[float, float] | None = None) -> None:
        points = [] if at is None else [{"x": at[0], "y": at[1]}]
        self._cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": points})
        # A touch is delivered to the page with the next frame.
        self._page.evaluate("() => new Promise((done) => requestAnimationFrame(() => requestAnimationFrame(done)))")

    def down(self, x: float, y: float) -> None:
        self._send("touchStart", (x, y))

    def move(self, x: float, y: float) -> None:
        self._send("touchMove", (x, y))

    def up(self) -> None:
        self._send("touchEnd")

    def cancel(self) -> None:
        self._send("touchCancel")


def _init(page: Page) -> None:
    page.evaluate(_INIT_JS)


def _state(page: Page) -> dict[str, Any]:
    return page.evaluate(_STATE_JS)


def _centre(page: Page, tab: str) -> tuple[float, float]:
    box = page.locator(f".tabs .tab[data-tab={tab}]").bounding_box()
    assert box is not None
    return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2


def _assert_at_rest_on(state: dict[str, Any], tab: str) -> None:
    """The capsule is parked on *tab* at that tab's whole-pixel offsets, and nothing slides."""
    left, width = state["cells"][tab]
    assert (state["x"], state["w"]) == (f"{left}px", f"{width}px"), state
    assert not state["sliding"], state
    assert state["open"] == tab and state["accent"] == [tab] and state["selected"] == [tab], state


def check_slide_follows_the_finger_and_lifting_chooses_the_tab(nav_mobile: Page) -> None:
    """Press Home, slide to History, lift: the capsule follows, the accent leads, the lift switches once."""
    page = nav_mobile
    _init(page)
    finger = _Finger(page)
    home, stats, history = (_centre(page, tab) for tab in ("home", "stats", "history"))
    _assert_at_rest_on(_state(page), "home")
    assert style(page, ".tab-pill", "transitionDuration").startswith("0.5s")

    finger.down(*home)
    finger.move(home[0] + _SLOP_PX - 3, home[1])
    assert not _state(page)["sliding"], "a press that wandered under the slop became a slide"

    # Two thirds of the way to Stats: the capsule is between the two cells and
    # Stats, the nearer tab, already carries the accent. Nothing has switched.
    finger.move(home[0] + (stats[0] - home[0]) * 2 / 3, home[1])
    mid = _state(page)
    assert mid["sliding"], mid
    assert mid["cells"]["home"][0] < float(mid["x"][:-2]) < mid["cells"]["stats"][0], mid
    assert mid["accent"] == ["stats"], mid
    assert mid["open"] == "home" and mid["selected"] == ["home"] and mid["changes"] == ["home"], mid
    assert mid["shown"] == ["paneHome"], mid
    # Under a finger the capsule keeps up instead of springing.
    assert style(page, ".tab-pill", "transitionDuration").startswith("0.12s")

    # Past the last tab the capsule stops on it.
    finger.move(*history)
    finger.move(history[0] + 400, history[1])
    end = _state(page)
    assert end["x"] == f"{end['cells']['history'][0]}px" and end["accent"] == ["history"], end
    assert end["open"] == "home", end

    finger.up()
    after = _state(page)
    _assert_at_rest_on(after, "history")
    assert after["changes"] == ["home", "history"] and after["shown"] == ["paneHistory"], after
    assert style(page, ".tab-pill", "transitionDuration").startswith("0.5s")


def check_a_tap_and_a_press_that_wanders_still_switch(nav_mobile: Page) -> None:
    """A plain tap works as before, and so does a press that moves less than the slop."""
    page = nav_mobile
    _init(page)
    page.touchscreen.tap(*_centre(page, "stats"))
    page.wait_for_function("() => document.querySelector('.tabs').dataset.activeTab === 'stats'")
    _assert_at_rest_on(_state(page), "stats")

    finger = _Finger(page)
    history = _centre(page, "history")
    finger.down(*history)
    finger.move(history[0] + _SLOP_PX - 3, history[1])
    finger.up()
    page.wait_for_function("() => document.querySelector('.tabs').dataset.activeTab === 'history'")
    after = _state(page)
    _assert_at_rest_on(after, "history")
    assert after["changes"] == ["home", "stats", "history"], after


def check_lifting_on_the_open_tab_or_a_cancelled_touch_changes_nothing(nav_mobile: Page) -> None:
    """Sliding away and back, or a touch the system cancels, leaves the open tab and the scroll alone."""
    page = nav_mobile
    _init(page)
    finger = _Finger(page)
    home, history = _centre(page, "home"), _centre(page, "history")
    page.evaluate("() => window.scrollTo(0, 200)")
    assert _state(page)["scrollY"] == 200, "the page under the harness does not scroll"

    finger.down(*home)
    finger.move(*history)
    assert _state(page)["accent"] == ["history"]
    finger.move(*home)
    finger.up()
    back = _state(page)
    _assert_at_rest_on(back, "home")
    assert back["changes"] == ["home"] and back["scrollY"] == 200, back

    finger.down(*home)
    finger.move(*history)
    assert _state(page)["sliding"]
    finger.cancel()
    cancelled = _state(page)
    _assert_at_rest_on(cancelled, "home")
    assert cancelled["changes"] == ["home"] and cancelled["scrollY"] == 200, cancelled

    # A click with no pointer behind it (keyboard, assistive tech) still
    # switches, once the window that drops a slide's stray click has passed.
    page.wait_for_timeout(350)
    page.evaluate("() => document.querySelector('.tab[data-tab=stats]').click()")
    _assert_at_rest_on(_state(page), "stats")


def check_a_drag_on_the_inline_control_is_not_a_slide(nav: Page) -> None:
    """Away from the phone pill there is no capsule to slide: a drag across the tabs does nothing."""
    page = nav
    _init(page)
    home, history = _centre(page, "home"), _centre(page, "history")
    page.mouse.move(*home)
    page.mouse.down()
    page.mouse.move(*history, steps=6)
    during = _state(page)
    assert not during["sliding"] and during["accent"] == ["home"], during
    page.mouse.up()
    after = _state(page)
    assert after["open"] == "home" and after["changes"] == ["home"] and not after["sliding"], after
    # The control still answers a click.
    page.locator(".tab[data-tab=stats]").click()
    assert _state(page)["open"] == "stats"
