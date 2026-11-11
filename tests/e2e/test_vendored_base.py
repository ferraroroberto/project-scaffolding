"""The vendored `base/` contract: components own their controls' typeface, and `color-scheme` follows the theme.

## Controls inherit the body font

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

## `color-scheme` follows the chosen theme

Native UI (a `<select>` list, date and time pickers, scrollbars) is drawn from
`color-scheme`. An app that sets `light dark` on `:root` follows the OS, so a
dark app theme on a light OS opened native popups on a light background. The
vendored `base.css` pins `color-scheme` to `data-theme`, and an app's own bare
`:root { color-scheme: light dark }` must not undo that.

Playwright cannot screenshot a native popup, so the proof is the palette the
engine hands native UI: the `Canvas` system colour resolves to the scheme's
background. Run on WebKit as well, the engine of the reported iPhone.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path

from playwright.sync_api import Page, Playwright, Route

from tests.e2e._cases import cases
from tests.e2e._color_assertions import style as _style
from tests.e2e._nav_graft import mount_nav

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


def _check_gallery_controls_inherit_without_base(static_server: str, page: Page) -> None:
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


def _check_nav_tabs_inherit_without_base(static_server: str, page: Page) -> None:
    """The nav's `<button class="tab">` takes the body's font with no `base.css`."""
    _drop_base_css(page)
    mount_nav(page, static_server)
    assert _assert_inherit(page, ".tabs") >= 2

_BASE_CSS = (
    Path(__file__).resolve().parents[2] / "app/webapp/static/_vendored/base/base.css"
).read_text(encoding="utf-8")

# An app's own stylesheet, loaded AFTER base, restating the old fallback.
_APP_CSS = ":root { color-scheme: light dark; } body { background: Canvas; }"

_PAGE = """<!doctype html><html{attr}><head><style>{base}</style><style>{app}</style></head>
<body><select id="s"><option>a</option></select><input id="d" type="date"></body></html>"""


def _is_dark(rgb: str) -> bool:
    """Canvas is a different dark grey per engine (Chromium 18, WebKit 30)."""
    return sum(int(c) for c in rgb[rgb.index("(") + 1 : -1].split(",")[:3]) < 255


def _read(playwright: Playwright, engine: str, os_scheme: str, theme: str | None) -> dict[str, str]:
    attr = f' data-theme="{theme}"' if theme else ""
    browser = getattr(playwright, engine).launch()
    try:
        page = browser.new_page(color_scheme=os_scheme)
        page.set_content(_PAGE.format(attr=attr, base=_BASE_CSS, app=_APP_CSS))
        return page.evaluate(
            """() => ({
              scheme: getComputedStyle(document.documentElement).colorScheme,
              canvas: getComputedStyle(document.body).backgroundColor,
            })"""
        )
    finally:
        browser.close()


# OS scheme, data-theme, the color-scheme base.css must compute, whether it reads dark.
_SCHEMES = [
    ("light", "dark", "dark", True),  # the reported case
    ("dark", "light", "light", False),
    ("light", None, "light dark", False),  # unset theme: follow the OS
    ("dark", None, "light dark", True),
]


def _check_color_scheme_follows_theme(
    playwright: Playwright, engine: str, os_scheme: str, theme: str | None, scheme: str, dark: bool
) -> None:
    got = _read(playwright, engine, os_scheme, theme)
    assert got["scheme"] == scheme, got
    # The scheme alone decides Canvas, so this is the colour native popups get.
    assert _is_dark(got["canvas"]) is dark, got


def test_base_contract(new_page: Callable[..., AbstractContextManager[Page]], static_server: str, playwright: Playwright) -> None:
    """Gallery controls and nav tabs take the body font with no `base.css` loaded, and `color-scheme` follows the theme on both engines."""
    with cases() as c:
        with c.case("gallery_controls_inherit_without_base"), new_page() as page:
            _check_gallery_controls_inherit_without_base(static_server=static_server, page=page)
        with c.case("nav_tabs_inherit_without_base"), new_page() as page:
            _check_nav_tabs_inherit_without_base(static_server=static_server, page=page)
        for engine in ["webkit", "chromium"]:
            for os_scheme, theme, scheme, dark in _SCHEMES:
                with c.case(f"color_scheme_follows_theme[{engine}-os_{os_scheme}-theme_{theme}]"):
                    _check_color_scheme_follows_theme(playwright=playwright, engine=engine, os_scheme=os_scheme, theme=theme, scheme=scheme, dark=dark)
