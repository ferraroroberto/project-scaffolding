"""Render harness for the page-foot and home-head components.

Drives the `demo.html` gallery through the shared `gallery` fixture in `conftest.py`;
split from `test_vendored_components.py` to keep each harness module small.
"""

from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from tests.e2e._color_assertions import contrast as _contrast
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style
from tests.e2e._geometry import assert_min_target, assert_no_overlap

_TRANSPARENT = "rgba(0, 0, 0, 0)"


def test_page_foot_contract(gallery: Page) -> None:
    """page-foot: centered footer, muted/caption readout text, shared build-text format."""
    assert _style(gallery, "#demoPageFoot", "textAlign") == "center"
    assert _style(gallery, "#demoBuildReadout", "color") == "rgb(101, 109, 118)"
    assert _style(gallery, "#demoBuildReadout", "fontSize") == "12px"  # 0.75rem @ 16px root
    text = gallery.locator("#demoBuildReadout").inner_text()
    assert re.match(r"^Build: abc1234 · \d{4}-\d{2}-\d{2} \d{2}:\d{2}$", text), text


def test_home_head_contract(gallery: Page) -> None:
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


def test_home_head_status_colours_exceptions_by_tone(gallery: Page) -> None:
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


def test_home_head_status_without_exceptions_renders_as_today(gallery: Page) -> None:
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


def test_home_head_status_keeps_at_most_two_parts(gallery: Page) -> None:
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
