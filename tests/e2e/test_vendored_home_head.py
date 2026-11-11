"""Render harness for the page-foot and home-head components.

Drives the `demo.html` gallery through the shared `gallery` fixture in `conftest.py`;
split from `test_vendored_components.py` to keep each harness module small.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager

from playwright.sync_api import Browser, Page, expect

from tests.e2e._cases import cases
from tests.e2e._color_assertions import contrast as _contrast
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style
from tests.e2e._geometry import assert_min_target, assert_no_overlap
from tests.e2e._nav_graft import phone_nav
from tests.e2e.conftest import STATIC_DIR

_TRANSPARENT = "rgba(0, 0, 0, 0)"


def _check_page_foot_contract(gallery: Page) -> None:
    """page-foot: centered footer, muted/caption readout text, shared build-text format."""
    assert _style(gallery, "#demoPageFoot", "textAlign") == "center"
    assert _style(gallery, "#demoBuildReadout", "color") == "rgb(101, 109, 118)"
    assert _style(gallery, "#demoBuildReadout", "fontSize") == "12px"  # 0.75rem @ 16px root
    text = gallery.locator("#demoBuildReadout").inner_text()
    assert re.match(r"^Build: abc1234 · \d{4}-\d{2}-\d{2} \d{2}:\d{2}$", text), text


def _check_home_head_contract(gallery: Page) -> None:
    """home-head: 52px row at 0-14px inset, title glyph 18px, status ellipsizes, right-pinned 34px toggle + Settings gear (44px targets)."""
    # One row at the disclosure closed-summary geometry (rows.md 52px, 0 14px).
    assert _style(gallery, "#demoHomeHead", "minHeight") == "52px"
    assert _style(gallery, "#demoHomeHead", "paddingLeft") == "14px"
    assert _style(gallery, "#demoHomeHead", "paddingTop") == "0px"  # overrides the card's own padding
    assert _style(gallery, "#demoHomeHead", "display") == "flex"
    # Title glyph is title-size and muted.
    assert _style(gallery, "#demoHomeHead .home-title .icon", "width") == "18px"
    # Status fills the middle and ellipsizes so it can't wrap the row.
    assert _style(gallery, "#demoHomeStatus", "textOverflow") == "ellipsis"
    assert _style(gallery, "#demoHomeStatus", "whiteSpace") == "nowrap"
    # Icon-only theme toggle: an invisible 34px box (an icon button, #324 --
    # transparent at rest, no border), pinned right.
    assert _style(gallery, "#demoHomeToggle", "width") == "34px"
    assert _style(gallery, "#demoHomeToggle", "height") == "34px"
    assert _style(gallery, "#demoHomeToggle", "backgroundColor") == _TRANSPARENT
    assert _style(gallery, "#demoHomeToggle", "borderTopWidth") == "0px"
    # The Settings gear (fleet-config#1200: never a tab) is the second trailing
    # action: the same unpainted 34px box as the toggle, with no button tier.
    gear = "#demoHomeSettings"
    assert _style(gallery, gear, "width") == "34px"
    assert _style(gallery, gear, "height") == "34px"
    assert _style(gallery, gear, "backgroundColor") == _TRANSPARENT
    assert _style(gallery, gear, "borderTopWidth") == "0px"
    expect(gallery.locator(gear)).to_have_attribute("aria-label", "Settings")
    # The pair is pinned to the right: the gear's right edge sits within ~1px of
    # the row's content edge (row right minus the 14px inset), the toggle sits
    # one --gap (12px) to its left, and both come after the status. Only the
    # first action takes the auto margin, so the pair stays together.
    pinned = gallery.evaluate(
        "() => {"
        " const r = (id) => document.getElementById(id).getBoundingClientRect();"
        " const row = r('demoHomeHead'), tog = r('demoHomeToggle'),"
        "   gear = r('demoHomeSettings'), status = r('demoHomeStatus');"
        " return { gap: (row.right - 14) - gear.right, pair: gear.left - tog.right,"
        "   afterStatus: tog.left >= status.right - 1 };"
        "}"
    )
    assert abs(pinned["gap"]) <= 1.5, pinned
    assert abs(pinned["pair"] - 12) <= 1.5, pinned
    assert pinned["afterStatus"], pinned
    # Both are 44px targets (a 34px visual plus the 5px ::before), and the
    # 12px gap keeps the two expansions from overlapping.
    actions = gallery.locator("#demoHomeHead .home-toggle")
    assert_min_target(actions)
    assert_no_overlap(actions)


_TONE_STATUS = "#demoHomeStatusTone"

# Render into the gallery's tone-demo status slot through the vendored module,
# exactly as an adopter's refresh would, and report what the slot now holds.
_RENDER_STATUS_JS = """async ([exceptions, fallback]) => {
  const { renderHeadStatus } = await import('./home-head/home-head.js');
  const el = document.querySelector('#demoHomeStatusTone');
  renderHeadStatus(el, exceptions, fallback);
  return {
    text: el.textContent,
    tone: el.dataset.tone ?? null,
    parts: [...el.children].map((c) => ({ text: c.textContent, tone: c.dataset.tone,
      cls: c.className })),
  };
}"""


def _render_status(page: Page, exceptions: object, fallback: object) -> dict[str, object]:
    return page.evaluate(_RENDER_STATUS_JS, [exceptions, fallback])  # type: ignore[no-any-return]


def _check_home_head_status_colours_exceptions_by_tone(gallery: Page) -> None:
    """home-head: each exception part sits in its tone's *-text with AA contrast, both themes (#343)."""
    shown = _render_status(
        gallery,
        [{"text": "1 needs you", "tone": "attention"}, {"text": "1 stalled", "tone": "danger"}],
        "7 sessions",
    )
    # Severity order (design.md page-header): danger first, then attention.
    assert shown["text"] == "1 stalled · 1 needs you", shown
    assert [p["tone"] for p in shown["parts"]] == ["danger", "attention"]  # type: ignore[attr-defined]
    danger = f"{_TONE_STATUS} .head-exception[data-tone='danger']"
    attention = f"{_TONE_STATUS} .head-exception[data-tone='attention']"
    card = _style(gallery, "#demoHomeHeadTone", "backgroundColor")
    assert _style(gallery, danger, "color") == "rgb(164, 14, 38)"  # danger-text
    assert _style(gallery, attention, "color") == "rgb(125, 78, 0)"  # attention-text
    for sel in (danger, attention):
        assert _contrast(_style(gallery, sel, "color"), card, card) >= 4.5, sel
    _set_theme(gallery, "dark")
    card = _style(gallery, "#demoHomeHeadTone", "backgroundColor")
    assert _style(gallery, danger, "color") == "rgb(255, 123, 114)"
    assert _style(gallery, attention, "color") == "rgb(227, 179, 65)"
    for sel in (danger, attention):
        assert _contrast(_style(gallery, sel, "color"), card, card) >= 4.5, sel


def _check_home_head_status_without_exceptions_renders_as_today(gallery: Page) -> None:
    """home-head: no exceptions = the plain muted fallback text, no spans, no tone; no .status = no-op (#343)."""
    # Dirty the slot first so the reset is what is measured.
    _render_status(gallery, [{"text": "1 stalled", "tone": "danger"}], "7 sessions")
    for none in ([], None, [{"text": "", "tone": "danger"}, None]):
        shown = _render_status(gallery, none, "7 sessions")
        assert shown == {"text": "7 sessions", "tone": None, "parts": []}, (none, shown)
        assert _style(gallery, _TONE_STATUS, "color") == _style(gallery, "#demoHomeStatus", "color")
    # An omitted fallback blanks the slot rather than printing "undefined".
    assert _render_status(gallery, [], None)["text"] == ""
    # A header with no .status slot: the renderer does nothing and does not throw.
    gallery.evaluate(
        "async () => { const { renderHeadStatus } = await import('./home-head/home-head.js');"
        " renderHeadStatus(null, [{ text: 'x', tone: 'danger' }], 'y');"
        " renderHeadStatus(undefined, [], 'y'); }"
    )


def _check_home_head_status_keeps_at_most_two_parts(gallery: Page) -> None:
    """home-head: two parts max, joined by ' · '; a neutral part keeps the slot's muted colour (#343)."""
    shown = _render_status(
        gallery,
        [{"text": "a", "tone": "attention"}, {"text": "b", "tone": "attention"},
         {"text": "c", "tone": "danger"}],
        "fallback",
    )
    assert shown["text"] == "c · a", shown  # danger first, caller order within a tone
    assert all(p["cls"] == "head-exception" for p in shown["parts"])  # type: ignore[attr-defined]
    shown = _render_status(gallery, [{"text": "n", "tone": "neutral"}], "fallback")
    assert shown["text"] == "n" and shown["tone"] == "neutral", shown
    assert _style(gallery, f"{_TONE_STATUS} .head-exception", "color") == _style(
        gallery, "#demoHomeStatus", "color"
    )


# page-foot is self-contained: it renders identically under any body font.
#
# The build footer once set only colour and size, so its family and numerals
# came from each app's body or container and the same line looked different on
# the same phone. The standalone cases mount the real `page-foot.css` under two
# deliberately different body typefaces and assert the readout's computed type
# and its rendered pixels match, then pin the type itself to the design.md
# `caption` style with tabular numerals. The last case mounts it at the end of
# `.app` beside the real nav at phone size and asserts it ends clear of the
# bottom fade (the footer adds no bottom padding; the nav's reserve does).

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


def _check_readout_type_is_pinned_to_the_caption_style(page: Page) -> None:
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


def _check_readout_ignores_the_body_typeface(page: Page) -> None:
    computed: dict[str, dict[str, str]] = {}
    shots: dict[str, bytes] = {}
    for name, body in _BODIES.items():
        _mount(page, body)
        page.evaluate("document.fonts.ready")
        computed[name] = _computed(page)
        shots[name] = page.locator("#foot").screenshot(animations="disabled")
    assert computed["serif"] == computed["mono"]
    assert shots["serif"] == shots["mono"], "footer pixels differ between body fonts"


def _check_readout_does_not_widen_with_the_body(page: Page, body: str) -> None:
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


@contextmanager
def _phone(static_server: str, browser: Browser) -> Iterator[Page]:
    with phone_nav(browser, static_server) as page:
        page.add_style_tag(url=f"{static_server}/_vendored/page-foot/page-foot.css")
        page.evaluate(_MOUNT_JS)
        yield page


def _check_footer_ends_above_the_nav_fade_undimmed(phone: Page) -> None:
    page = phone
    page.evaluate("() => window.scrollTo({ top: 1e6, behavior: 'instant' })")
    state = page.evaluate(_STATE_JS)
    assert state["maxScroll"] > 1000, state  # the page really scrolls
    assert state["scrollY"] == state["maxScroll"], state  # and we are at its end
    assert state["fadeBottom"] == "0px", state  # fade anchored to the screen bottom
    assert state["footTop"] >= 0, state  # footer is on screen, not past the top
    assert state["fadeTop"] - state["footBottom"] >= _GAP - 0.5, state
    assert state["opacity"] == 1, state


def test_home_head_contract(
    new_gallery: Callable[[], AbstractContextManager[Page]],
    new_page: Callable[..., AbstractContextManager[Page]],
    static_server: str,
    browser: Browser,
) -> None:
    """The home head and its status line, and the page foot (gallery and standalone), one case per contract."""
    with cases() as c:
        with c.case("page_foot_contract"), new_gallery() as gallery:
            _check_page_foot_contract(gallery=gallery)
        with c.case("home_head_contract"), new_gallery() as gallery:
            _check_home_head_contract(gallery=gallery)
        with c.case("home_head_status_colours_exceptions_by_tone"), new_gallery() as gallery:
            _check_home_head_status_colours_exceptions_by_tone(gallery=gallery)
        with c.case("home_head_status_without_exceptions_renders_as_today"), new_gallery() as gallery:
            _check_home_head_status_without_exceptions_renders_as_today(gallery=gallery)
        with c.case("home_head_status_keeps_at_most_two_parts"), new_gallery() as gallery:
            _check_home_head_status_keeps_at_most_two_parts(gallery=gallery)
        with c.case("readout_type_is_pinned_to_the_caption_style"), new_page() as page:
            _check_readout_type_is_pinned_to_the_caption_style(page=page)
        with c.case("readout_ignores_the_body_typeface"), new_page() as page:
            _check_readout_ignores_the_body_typeface(page=page)
        for body in sorted(_BODIES):
            with c.case(f"readout_does_not_widen_with_the_body[{body}]"), new_page() as page:
                _check_readout_does_not_widen_with_the_body(page=page, body=body)
        with c.case("footer_ends_above_the_nav_fade_undimmed"), _phone(static_server, browser) as phone:
            _check_footer_ends_above_the_nav_fade_undimmed(phone=phone)
