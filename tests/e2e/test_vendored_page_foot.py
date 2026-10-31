"""page-foot is self-contained: it renders identically under any body font.

The build footer once set only colour and size, so its family and numerals
came from each app's body or container and the same line looked different on
the same phone. These tests mount the real `page-foot.css` under two
deliberately different body typefaces and assert the readout's computed type
and its rendered pixels match, then pin the type itself to the design.md
`caption` style with tabular numerals.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

from tests.e2e.conftest import STATIC_DIR

_CSS = (STATIC_DIR / "_vendored" / "page-foot" / "page-foot.css").read_text(encoding="utf-8")

# Tokens the way an app declares them; nothing here sets the footer's type.
_TOKENS = ":root { --muted: #656d76; --space-md: 16px; --space-xs: 4px; --font-caption: 0.75rem; }"

# Two bodies that disagree on everything the footer used to inherit.
_BODIES = {
    "serif": "font-family: Georgia, 'Times New Roman', serif; font-size: 20px; font-weight: 300;"
    " line-height: 2; letter-spacing: 0.1em; font-style: italic; text-transform: uppercase;",
    "mono": "font-family: 'Courier New', monospace; font-size: 11px; font-weight: 800;"
    " line-height: 1; letter-spacing: -0.02em; font-variant-numeric: oldstyle-nums;",
}

_READOUT = "Build: 0123abc · 2026-10-31 17:52"

_TYPE_PROPS = (
    "fontFamily",
    "fontSize",
    "fontWeight",
    "fontStyle",
    "lineHeight",
    "letterSpacing",
    "textTransform",
    "fontVariantNumeric",
    "textAlign",
    "color",
    "marginTop",
    "marginBottom",
)


def _mount(page: Page, body_style: str) -> None:
    page.set_viewport_size({"width": 390, "height": 300})
    page.set_content(
        f"<!doctype html><meta charset=utf-8><style>{_TOKENS}{_CSS}"
        f"body {{ margin: 0; background: #fff; color: #1f2328; {body_style} }}</style>"
        f'<main class="app"><footer class="page-foot" id="foot">'
        f'<p id="readout">{_READOUT}</p></footer></main>'
    )


def _computed(page: Page) -> dict[str, str]:
    return page.evaluate(
        """(props) => {
          const el = document.getElementById('readout');
          const cs = getComputedStyle(el);
          return Object.fromEntries(props.map(p => [p, cs[p]]));
        }""",
        list(_TYPE_PROPS),
    )


def test_readout_type_is_pinned_to_the_caption_style(page: Page) -> None:
    _mount(page, _BODIES["serif"])
    cs = _computed(page)
    assert cs["fontSize"] == "12px"
    assert cs["fontWeight"] == "600"
    assert cs["fontStyle"] == "normal"
    assert cs["lineHeight"] == "13.2px"  # 1.1 x 12px
    assert cs["letterSpacing"] == "normal"
    assert cs["textTransform"] == "none"
    assert cs["fontVariantNumeric"] == "tabular-nums"
    assert "system-ui" in cs["fontFamily"]
    assert cs["textAlign"] == "center"
    assert cs["color"] == "rgb(101, 109, 118)"


def test_readout_ignores_the_body_typeface(page: Page) -> None:
    computed: dict[str, dict[str, str]] = {}
    shots: dict[str, bytes] = {}
    for name, body in _BODIES.items():
        _mount(page, body)
        page.evaluate("document.fonts.ready")
        computed[name] = _computed(page)
        shots[name] = page.locator("#foot").screenshot(animations="disabled")
    assert computed["serif"] == computed["mono"]
    assert shots["serif"] == shots["mono"], "footer pixels differ between body fonts"


@pytest.mark.parametrize("body", sorted(_BODIES))
def test_readout_does_not_widen_with_the_body(page: Page, body: str) -> None:
    """The footer box itself is one line of caption height, whatever the body's line-height."""
    _mount(page, _BODIES[body])
    height = page.locator("#readout").evaluate("el => el.getBoundingClientRect().height")
    assert abs(height - 13.2) < 0.5, height
