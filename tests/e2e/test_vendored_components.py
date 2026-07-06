"""Render harness for the vendored UI components (issue #120).

Drives `app/webapp/static/_vendored/demo.html` — the component gallery — in a
real browser and asserts each component's *key computed styles* in both the
light and dark themes, so a regression in any `_vendored/<name>/<name>.css`
fails loudly here rather than silently downstream in a consuming app.

The gallery is served over HTTP by an in-process `http.server` (session
fixture below) because the components' ESM imports (`switch.js`,
`empty-state.js`) don't run from `file://`.

Assertions are the contracts from `~/.claude/design.md` v2 ("Component
contracts" + the component token blocks); expected colors are the sRGB spec
values (the demo page omits the P3 twins on purpose).
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

STATIC_DIR = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # noqa: D102 — silence per-request stderr noise
        pass


@pytest.fixture(scope="session")
def static_server() -> Iterator[str]:
    """Serve app/webapp/static over HTTP on an ephemeral port for the session."""
    handler = partial(_QuietHandler, directory=str(STATIC_DIR))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture()
def gallery(static_server: str, page: Page) -> Page:
    """The demo gallery, loaded and module-script-ready, in the light theme."""
    page.goto(f"{static_server}/_vendored/demo.html")
    page.wait_for_selector("body[data-demo-ready='1']")
    return page


def _style(page: Page, selector: str, prop: str) -> str:
    return page.eval_on_selector(
        selector, "(el, prop) => getComputedStyle(el)[prop]", prop
    )


def _set_theme(page: Page, theme: str) -> None:
    page.evaluate(
        "(t) => { document.documentElement.dataset.theme = t; }", theme
    )


def _wait_bg(page: Page, selector: str, expected: str) -> None:
    """Wait for a background-color to settle on `expected`.

    The switch track transitions its background over 0.15s, so an instant
    computed-style read lands mid-interpolation; wait for the end value.
    """
    page.wait_for_function(
        "([sel, want]) => getComputedStyle(document.querySelector(sel))"
        ".backgroundColor === want",
        arg=[selector, expected],
    )


# --------------------------------------------------------------------- light


def test_card_contract(gallery: Page) -> None:
    """card: rounded.lg corners, spacing.md padding, hairline border, title glyph 18px."""
    assert _style(gallery, "#demoCard", "borderRadius") == "16px"
    assert _style(gallery, "#demoCard", "paddingTop") == "16px"
    assert _style(gallery, "#demoCard", "borderTopWidth") == "1px"
    assert _style(gallery, "#demoCard .card-title .icon", "width") == "18px"


def test_disclosure_contract(gallery: Page) -> None:
    """disclosure: 52px closed summary, zeroed card padding, open-state divider."""
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "height") == "52px"
    assert _style(gallery, "#demoDisclosureClosed", "paddingTop") == "0px"
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "paddingLeft") == "14px"
    # Only the OPEN disclosure draws the divider under its summary.
    assert _style(gallery, "#demoDisclosureOpen .collapse-summary", "borderBottomWidth") == "1px"
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "borderBottomWidth") == "0px"


def test_switch_contract(gallery: Page) -> None:
    """switch: 44x26 track, green (success) on-track, off-track = border."""
    assert _style(gallery, "#demoSwitchOn", "width") == "44px"
    assert _style(gallery, "#demoSwitchOn", "height") == "26px"
    # THE green decision (design.md v2): on = colors.success, not accent.
    assert _style(gallery, "#demoSwitchOn", "backgroundColor") == "rgb(26, 127, 55)"
    assert _style(gallery, "#demoSwitchOff", "backgroundColor") == "rgb(209, 217, 224)"


def test_switch_builder(gallery: Page) -> None:
    """switch.js: builder emits the contract markup and flips on click."""
    built = gallery.locator("#demoSwitchBuilt")
    expect(built).to_have_attribute("role", "switch")
    expect(built).to_have_attribute("aria-checked", "false")
    built.click()
    expect(built).to_have_attribute("aria-checked", "true")
    _wait_bg(gallery, "#demoSwitchBuilt", "rgb(26, 127, 55)")


def test_empty_state_contract(gallery: Page) -> None:
    """empty-state: builder emits glyph (24px feature size) + message + action."""
    host = gallery.locator("#demoEmptyHost .empty-state")
    expect(host).to_be_visible()
    assert _style(gallery, "#demoEmptyHost .empty-state-icon", "width") == "24px"
    expect(gallery.locator("#demoEmptyHost .empty-state-message")).to_have_text(
        "Nothing reachable"
    )
    expect(gallery.locator("#demoEmptyHost .empty-state-action")).to_have_text("Retry")


def test_modal_contract(gallery: Page) -> None:
    """modal: opens via the native API, 34px close, AA disabled recipe on Save."""
    gallery.click("#openModalBtn")
    expect(gallery.locator("#demoDialog")).to_be_visible()
    assert _style(gallery, "#demoDialogClose", "width") == "34px"
    assert _style(gallery, "#demoDialogClose", "height") == "34px"
    # Disabled primary = the flat card-off/muted/line recipe, not opacity.
    assert _style(gallery, "#demoSaveBtn", "backgroundColor") == "rgb(246, 248, 250)"
    assert _style(gallery, "#demoSaveBtn", "color") == "rgb(101, 109, 118)"
    gallery.click("#demoDialogClose")
    expect(gallery.locator("#demoDialog")).to_be_hidden()


def test_icon_tile_contract(gallery: Page) -> None:
    """icon-tile: rounded.md squircle, tile-blue fill, feature-size glyph."""
    assert _style(gallery, "#demoTileBlue", "borderRadius") == "12px"
    assert _style(gallery, "#demoTileBlue", "backgroundColor") == "rgb(9, 105, 218)"
    assert _style(gallery, "#demoTileBlue .icon", "width") == "24px"


# ---------------------------------------------------------------------- dark


def test_dark_theme_values(gallery: Page) -> None:
    """Every component re-skins from the dark token block — same structure."""
    _set_theme(gallery, "dark")
    # card surface goes to the dark elevated value.
    assert _style(gallery, "#demoCard", "backgroundColor") == "rgb(22, 27, 34)"
    # switch on-track stays green, at the brighter dark success value
    # (waits out the 0.15s track transition).
    _wait_bg(gallery, "#demoSwitchOn", "rgb(63, 185, 80)")
    # icon-tile fill steps to the brighter dark tile-blue.
    assert _style(gallery, "#demoTileBlue", "backgroundColor") == "rgb(47, 129, 247)"
    # structure is theme-independent: closed height and radii hold.
    assert _style(gallery, "#demoDisclosureClosed .collapse-summary", "height") == "52px"
    assert _style(gallery, "#demoCard", "borderRadius") == "16px"
    # modal disabled recipe holds AA on the dark surface (dark card-off/muted).
    gallery.click("#openModalBtn")
    assert _style(gallery, "#demoSaveBtn", "backgroundColor") == "rgb(1, 4, 9)"
    assert _style(gallery, "#demoSaveBtn", "color") == "rgb(125, 133, 144)"
