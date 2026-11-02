"""page-foot is self-contained: it renders identically under any body font.

The build footer once set only colour and size, so its family and numerals
came from each app's body or container and the same line looked different on
the same phone. These tests mount the real `page-foot.css` under two
deliberately different body typefaces and assert the readout's computed type
and its rendered pixels match, then pin the type itself to the design.md
`caption` style with tabular numerals. The last test mounts it at the end of
`.app` beside the real nav at phone size and asserts it ends clear of the
bottom fade (the footer adds no bottom padding; the nav's reserve does).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page

from tests.e2e._nav_graft import phone_nav
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


_GAP = 12  # design.md --gap; the last term of the nav's bottom reserve

_MOUNT_JS = """() => {
  document.querySelectorAll('body > :not(.tabs):not(.app)')
    .forEach((e) => { e.style.display = 'none'; });
  const app = document.querySelector('.app');
  app.replaceChildren();
  const filler = document.createElement('div');
  filler.style.height = '2000px';
  app.appendChild(filler);
  app.insertAdjacentHTML('beforeend',
    '<footer class="page-foot" id="foot"><p>Build: 0123abc \u00b7 2026-10-31 17:52</p></footer>');
}"""

_STATE_JS = """() => {
  const foot = document.getElementById('foot');
  const fade = getComputedStyle(document.body, '::before');
  const rect = foot.getBoundingClientRect();
  let node = foot;
  let opacity = 1;
  while (node) { opacity *= parseFloat(getComputedStyle(node).opacity); node = node.parentElement; }
  return {
    footBottom: rect.bottom,
    footTop: rect.top,
    fadeTop: innerHeight - parseFloat(fade.height),
    fadeBottom: fade.bottom,
    opacity,
    scrollY: scrollY,
    maxScroll: document.scrollingElement.scrollHeight - innerHeight,
  };
}"""


@pytest.fixture()
def phone(static_server: str, browser: Browser) -> Iterator[Page]:
    with phone_nav(browser, static_server) as page:
        page.add_style_tag(url=f"{static_server}/_vendored/page-foot/page-foot.css")
        page.evaluate(_MOUNT_JS)
        yield page


def test_footer_ends_above_the_nav_fade_undimmed(phone: Page) -> None:
    page = phone
    page.evaluate("() => window.scrollTo({ top: 1e6, behavior: 'instant' })")
    state = page.evaluate(_STATE_JS)
    assert state["maxScroll"] > 1000, state  # the page really scrolls
    assert state["scrollY"] == state["maxScroll"], state  # and we are at its end
    assert state["fadeBottom"] == "0px", state  # fade anchored to the screen bottom
    assert state["footTop"] >= 0, state  # footer is on screen, not past the top
    assert state["fadeTop"] - state["footBottom"] >= _GAP - 0.5, state
    assert state["opacity"] == 1, state
