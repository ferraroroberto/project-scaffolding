"""Checks for the vendored full-screen-on-Edge Settings row.

Each case opens the gallery in a fresh browser context; `test_vendored_components.py`
runs them as cases. The row is Edge-only: a non-Edge user agent never sees it, and an Edge
phone (touch, 390px, the `EdgA/` token) can switch it on, keep the choice across a
reload and re-enter full screen on the first tap, while leaving by hand never turns
the setting off.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from playwright.sync_api import Page, expect

from tests.e2e._cases import Cases
from tests.e2e.conftest import load_gallery

_EDGE_PHONE = {
    "viewport": {"width": 390, "height": 844},
    "has_touch": True,
    "is_mobile": True,
    "user_agent": (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/130.0.0.0 Mobile Safari/537.36 EdgA/130.0.0.0"
    ),
}
_ROW = "#demoFullscreenRow"
_SWITCH = "#demoFullscreenSwitch"
_KEY = "demo.fullscreen"
_IN_FULLSCREEN = "!!document.fullscreenElement"


def _wait_fullscreen(page: Page, want: bool) -> None:
    page.wait_for_function(f"{_IN_FULLSCREEN} === {str(want).lower()}")


def _stored(page: Page) -> object:
    return page.evaluate(f"localStorage.getItem('{_KEY}')")


def check_row_is_hidden_outside_edge(gallery: Page) -> None:
    """A browser that is not Edge never shows the row and never stores a choice."""
    assert "Edg" not in gallery.evaluate("navigator.userAgent")
    gallery.click("#openSettingsPage")
    expect(gallery.locator("#demoSettingsSwitchRow")).to_be_visible()
    expect(gallery.locator(_ROW)).to_be_hidden()
    assert _stored(gallery) is None


def check_edge_phone_enters_keeps_and_leaves(page: Page, static_server: str) -> None:
    """The switch enters full screen; the choice survives a reload; a tap re-enters."""
    load_gallery(page, static_server)
    page.evaluate(f"localStorage.removeItem('{_KEY}')")
    page.click("#openSettingsPage")
    row, switch = page.locator(_ROW), page.locator(_SWITCH)
    expect(row).to_be_visible()
    expect(switch).to_have_attribute("aria-checked", "false")  # off by default
    assert page.evaluate(_IN_FULLSCREEN) is False

    switch.click()
    _wait_fullscreen(page, True)
    expect(switch).to_have_attribute("aria-checked", "true")
    assert _stored(page) == "1"
    expect(row).to_have_attribute("data-armed", "false")

    # Leaving by hand (the back gesture) does not switch the setting off: the row
    # says a tap goes back in, and a tap anywhere does.
    page.evaluate("document.exitFullscreen()")
    _wait_fullscreen(page, False)
    expect(switch).to_have_attribute("aria-checked", "true")
    assert _stored(page) == "1"
    expect(row).to_have_attribute("data-armed", "true")
    expect(page.locator(f"{_ROW} .fullscreen-armed")).to_be_visible()
    page.click("#demoSettingsTitle")
    _wait_fullscreen(page, True)
    expect(row).to_have_attribute("data-armed", "false")
    expect(page.locator(f"{_ROW} .fullscreen-armed")).to_be_hidden()

    # A reload leaves full screen; the stored choice keeps the switch on and the
    # first tap anywhere (opening Settings) re-enters.
    page.reload()
    page.wait_for_selector("body[data-demo-ready='1']")
    assert page.evaluate(_IN_FULLSCREEN) is False
    page.click("#openSettingsPage")
    _wait_fullscreen(page, True)
    expect(switch).to_have_attribute("aria-checked", "true")

    # The switch is the one way off, and it leaves full screen at once.
    switch.click()
    _wait_fullscreen(page, False)
    expect(switch).to_have_attribute("aria-checked", "false")
    assert _stored(page) is None
    expect(row).to_have_attribute("data-armed", "false")
    page.click("#demoSettingsTitle")
    assert page.evaluate(_IN_FULLSCREEN) is False  # off: a tap no longer re-enters


def run_fullscreen_cases(
    c: Cases,
    new_gallery: Callable[[], AbstractContextManager[Page]],
    new_page: Callable[..., AbstractContextManager[Page]],
    static_server: str,
) -> None:
    """Run each full-screen check as its own case."""
    with c.case("fullscreen_row_is_hidden_outside_edge"), new_gallery() as gallery:
        check_row_is_hidden_outside_edge(gallery)
    with c.case("fullscreen_edge_phone_enters_keeps_and_leaves"), new_page(**_EDGE_PHONE) as page:
        check_edge_phone_enters_keeps_and_leaves(page, static_server)
