"""Vendored components own their controls' typeface (#319).

`_vendored/base/base.css` carries the `button, input, select, textarea
{ font: inherit }` reset, but an app that never vendors `base` gets the
user-agent control font instead (Arial on Windows Chrome) — its nav tabs and
every row built as a `<button>` render in a second typeface. Each component
must therefore set `font: inherit` on its own control selector, so it is
correct whether or not the app brings the reset.

These tests load the real gallery and the real nav with `base.css` removed
(the "page with no global reset") and assert every component control's
computed `font-family` equals the body's. The gallery's own bare-element
`#demoBase` card is excluded: it exists to prove the *base* reset, so it is
supposed to fall back to the UA font here.
"""

from __future__ import annotations

from playwright.sync_api import Page, Route

from tests.e2e._color_assertions import style as _style
from tests.e2e.conftest import STATIC_DIR

_NAV_DIR = STATIC_DIR / "_vendored" / "nav"
_CONTROLS = "button, input, select, textarea"

# The floor below which the sweep would be vacuous: the gallery renders well
# over this many component controls, so a selector typo that matches nothing
# fails here instead of passing with zero assertions.
_MIN_CONTROLS = 30


def _drop_base_css(page: Page) -> None:
    """Serve `base/base.css` as an empty stylesheet for this page."""
    page.route(
        "**/_vendored/base/base.css",
        lambda route: _empty_css(route),
    )


def _empty_css(route: Route) -> None:
    route.fulfill(status=200, content_type="text/css", body="")


def _families(page: Page, scope: str) -> list[tuple[str, str]]:
    """(description, computed font-family) for every control under *scope*.

    Skips the gallery's `#demoBase` card (see the module docstring).
    """
    return page.evaluate(
        """([scope, controls]) => [...document.querySelectorAll(scope)]
            .flatMap(root => [...root.querySelectorAll(controls)])
            .filter(el => !el.closest('#demoBase'))
            .map(el => [
              el.tagName.toLowerCase() + (el.className ? '.' + String(el.className).trim().split(/\\s+/).join('.') : ''),
              getComputedStyle(el).fontFamily,
            ])""",
        [scope, _CONTROLS],
    )


def _assert_inherit(page: Page, scope: str) -> int:
    body = _style(page, "body", "fontFamily")
    rows = _families(page, scope)
    wrong = [(name, family) for name, family in rows if family != body]
    assert not wrong, f"controls not on the body font ({body}): {wrong}"
    return len(rows)


def test_gallery_controls_inherit_without_base(static_server: str, page: Page) -> None:
    """Every gallery control takes the body's font with no `base.css` loaded."""
    _drop_base_css(page)
    page.goto(f"{static_server}/_vendored/demo.html")
    page.wait_for_selector("body[data-demo-ready='1']")
    # base really is gone: the bare control is on the UA font, not the body's.
    assert _style(page, "#demoBaseButton", "fontFamily") != _style(page, "body", "fontFamily")
    # JS-built controls that only exist once opened: the row-menu items.
    page.click("#demoRowMenuKebab")
    page.wait_for_selector(".row-menu-item")
    count = _assert_inherit(page, "body")
    assert count >= _MIN_CONTROLS, count


def test_nav_tabs_inherit_without_base(static_server: str, page: Page) -> None:
    """The nav's `<button class="tab">` takes the body's font with no `base.css`."""
    _drop_base_css(page)
    page.goto(f"{static_server}/_vendored/demo.html")
    page.wait_for_selector("body[data-demo-ready='1']")
    page.add_style_tag(url=f"{static_server}/_vendored/nav/nav-tabs.css")
    page.evaluate(
        "(html) => document.body.insertAdjacentHTML('afterbegin', html)",
        (_NAV_DIR / "nav-tabs.html").read_text(encoding="utf-8"),
    )
    page.wait_for_selector(".tabs .tab", state="attached")
    assert _assert_inherit(page, ".tabs") >= 2
