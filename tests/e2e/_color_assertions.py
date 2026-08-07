"""Computed-style primitives shared by the vendored-component render harnesses.

`test_vendored_components.py` (the `demo.html` gallery) and `test_vendored_nav.py`
(the body-level nav, which can't join that gallery) both drive a real browser and
assert design-token values off `getComputedStyle`, so both need the same three
primitives: read a computed property, flip the document theme, and parse a
computed color string into channels. They were written once for the gallery and
re-typed for the nav — including the Chromium `color-mix()` serialization note —
so the next time Chromium changes how it serializes a computed color, one edit
would have had to be found and applied twice. This module is the single copy
(`project-scaffolding#208`).

Deliberately **not** a vendor-verbatim primitive: it is imported by this repo's
own test modules only. `tests/e2e/_geometry.py`, `_browser_sweep.py` and
`_e2e_live_guard.py` are copied byte-identical into adopter repos and must stay
self-contained — never refactor one of those to import this.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page

_RGBA_RE = re.compile(r"rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)")
# Chromium serializes a computed color-mix() as `color(srgb R G B / A)` with
# 0-1 float channels (legacy rgba() only when no color-mix is involved).
_COLOR_SRGB_RE = re.compile(r"color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: / ([\d.]+))?\)")


def style(page: Page, selector: str, prop: str) -> str:
    """The computed value of `prop` on the first element matching `selector`."""
    return page.eval_on_selector(
        selector, "(el, prop) => getComputedStyle(el)[prop]", prop
    )


def set_theme(page: Page, theme: str) -> None:
    """Flip `<html data-theme>` so the other theme's token block takes effect."""
    page.evaluate(
        "(t) => { document.documentElement.dataset.theme = t; }", theme
    )


def rgba(color: str) -> tuple[int, int, int, float]:
    """Parse a getComputedStyle color string into (r, g, b, alpha 0-1)."""
    m = _RGBA_RE.match(color)
    if m:
        a = float(m.group(4)) if m.group(4) is not None else 1.0
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), a
    m = _COLOR_SRGB_RE.match(color)
    assert m, f"unexpected color format: {color}"
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    return (round(float(m.group(1)) * 255), round(float(m.group(2)) * 255),
            round(float(m.group(3)) * 255), a)
