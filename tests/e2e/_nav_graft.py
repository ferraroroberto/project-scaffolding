"""Graft the real nav skeleton onto the gallery's tokens, for the render harnesses.

The nav can't join `demo.html`'s gallery (it is a fixed, body-level bar), so
three harnesses — `test_vendored_nav.py`, `test_vendored_row_menu_placement.py`
and `test_vendored_font_inherit.py` — each load the gallery for its token blocks,
add `nav/nav-tabs.css` and insert the `nav/nav-tabs.html` skeleton. They had
re-typed that recipe, each with its own wait, so a change to how the skeleton
mounts (it must stay a direct `<body>` child) would have been found and applied
three times. This module is the single copy (`project-scaffolding#394`), beside
`_color_assertions.py` (#208).

The wait settled on is `.tabs .tab` attached, and nothing more. The skeleton is
inserted synchronously and `add_style_tag(url=...)` already resolves only once
the stylesheet has loaded, so the wait is a structural boot check on the part of
the skeleton this helper owns — the tab buttons. It is `attached`, not the
default `visible`, because whether a tab's icon (or the tab itself) is *visible*
is exactly what the harnesses assert, and a hidden one must fail there with a
named locator rather than time out in a fixture. It is not `.tab-icon`: the
icon is part of what the nav harness tests (#142), so a skeleton that lost its
icons would surface as an opaque fixture timeout instead of a named assertion.

Deliberately **not** a vendor-verbatim primitive: imported by this repo's own
test modules only. `_geometry.py`, `_browser_sweep.py` and `_e2e_live_guard.py`
are copied byte-identical into adopter repos and must stay self-contained.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from playwright.sync_api import Browser, Page

from tests.e2e.conftest import STATIC_DIR

NAV_DIR = STATIC_DIR / "_vendored" / "nav"

# The phone the pill is laid out for: a coarse pointer at 390x844.
_PHONE_VIEWPORT = {"width": 390, "height": 844}


def mount_nav(page: Page, base_url: str) -> Page:
    """Load the gallery (for its tokens), then graft on the real nav skeleton.

    Navigates itself, so a caller that needs a route installed first (the
    no-`base.css` harness) sets it up before calling.
    """
    page.goto(f"{base_url}/_vendored/demo.html")
    page.wait_for_selector("body[data-demo-ready='1']")
    page.add_style_tag(url=f"{base_url}/_vendored/nav/nav-tabs.css")
    skeleton = (NAV_DIR / "nav-tabs.html").read_text(encoding="utf-8")
    page.evaluate(
        "(html) => document.body.insertAdjacentHTML('afterbegin', html)", skeleton
    )
    page.wait_for_selector(".tabs .tab", state="attached")
    return page


@contextmanager
def phone_nav(browser: Browser, base_url: str) -> Iterator[Page]:
    """The nav skeleton at 390x844 with a coarse pointer (the fixed bottom pill)."""
    context = browser.new_context(
        viewport=_PHONE_VIEWPORT, has_touch=True, is_mobile=True
    )
    page = context.new_page()
    try:
        mount_nav(page, base_url)
        # Boot check, not a skip: if touch emulation stops flipping the pointer
        # media feature, every assertion that follows would silently test the
        # desktop rules instead of the pill.
        assert page.evaluate("matchMedia('(pointer: coarse)').matches"), (
            "coarse-pointer emulation is not active — the mobile pill rules "
            "never matched, so this harness would assert nothing"
        )
        yield page
    finally:
        context.close()
