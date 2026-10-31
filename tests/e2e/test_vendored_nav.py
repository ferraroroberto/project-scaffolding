"""Render harness for the vendored `nav/` component (issue #142).

The nav can't join `demo.html`'s gallery — it's a sticky/fixed, body-level bar
that would sit on top of every other component — so this module mounts the real
`nav/nav-tabs.html` skeleton and the real `nav/nav-tabs.css` onto the gallery's
token blocks and asserts the icon contract on both surfaces.

The regression it exists to catch: `nav-tabs.css` used to hide `.tab-icon` on
desktop and reveal a `.tab-emoji` span instead, while every real adopter ships
SVG icons and no emoji span — so the desktop segmented control rendered
label-only tabs with no icon at all, silently, in five apps.

The computed-style primitives this harness shares with the gallery's
(`style`, `set_theme`, `rgba`) live once in `_color_assertions.py` (#208); the
gallery-plus-nav mount and the phone context live once in `_nav_graft.py` (#394).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e._color_assertions import contrast as _contrast
from tests.e2e._color_assertions import rgba as _rgba
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style
from tests.e2e._geometry import EFFECTIVE_RECT_JS
from tests.e2e._nav_graft import NAV_DIR, mount_nav, phone_nav

# Desktop token values the assertions below key on (from demo.html's :root,
# which transcribes ~/.claude/design.md). --font-label 0.875rem @ 16px root
# = 14px; the icon is sized 1.05em of that.
_DESKTOP_ICON_PX = 14 * 1.05
# Active-tab text and icon sit on the accent-soft tint, so they take
# accent-text, not the base accent (fleet-config#963).
_ACCENT_TEXT = "rgb(5, 80, 174)"
_ACCENT_TEXT_DARK = "rgb(88, 166, 255)"
_MUTED = "rgb(101, 109, 118)"
# design.md layout.wide / layout.rail (fleet-config#968).
_WIDE = 1100
_RAIL = 80


def _alpha(color: str) -> float:
    """Extract the alpha channel from a computed color string.

    A `color-mix(in srgb, ...)` result serializes as `rgba(r, g, b, a)` for
    the light-theme accent, but Chromium serializes the *dark*-theme accent's
    mix as `oklab(l a b / a)` instead (same `in srgb` mix, different output
    notation depending on the input channel values) — so this parses the
    alpha generically off the tail rather than assuming one color function.
    A solid, non-mixed `rgb(r, g, b)` (3 channels, no alpha) is opaque.
    """
    if "/" in color:
        return float(color.rsplit("/", 1)[1].rstrip(") ").strip())
    if color.startswith("rgba("):
        return float(color[len("rgba(") : -1].split(",")[3])
    return 1.0


def _wait_style(page: Page, selector: str, prop: str, expected: str) -> None:
    """Wait for a computed style property to settle on *expected*.

    `.tab` transitions `background`/`border-color`/`color` over 0.16s
    (nav-tabs.css), so an instant post-toggle read lands mid-interpolation —
    same reasoning as `test_vendored_components.py`'s `_wait_bg`.
    """
    page.wait_for_function(
        "([sel, prop, want]) => getComputedStyle(document.querySelector(sel))"
        "[prop] === want",
        arg=[selector, prop, expected],
    )


def _pseudo_content(page: Page, selector: str, pseudo: str) -> str:
    return page.evaluate(
        "([sel, p]) => getComputedStyle(document.querySelector(sel), p).content",
        [selector, pseudo],
    )


@pytest.fixture()
def nav(static_server: str, page: Page) -> Page:
    """The nav skeleton at a desktop viewport (fine pointer), below the rail."""
    page.set_viewport_size({"width": _WIDE - 1, "height": 800})
    return mount_nav(page, static_server)


@pytest.fixture()
def nav_mobile(static_server: str, browser: Browser) -> Iterator[Page]:
    """The nav skeleton at a phone viewport with a coarse pointer."""
    with phone_nav(browser, static_server) as page:
        yield page


def test_skeleton_ships_no_emoji_span() -> None:
    """The markup skeleton demonstrates icon + label only (#142), and no Settings tab."""
    skeleton = (NAV_DIR / "nav-tabs.html").read_text(encoding="utf-8")
    assert "tab-emoji" not in skeleton
    # Settings is the page-header gear, never a tab (fleet-config#1200): a new
    # app copies this skeleton, so a Settings tab here becomes one in every app.
    assert 'data-tab="settings"' not in skeleton
    assert 'id="tabSettings"' not in skeleton
    assert '<span class="tab-label">Settings</span>' not in skeleton


def test_desktop_control_and_wide_rail(nav: Page) -> None:
    """Desktop: the icon beside the label in the column, a left rail when wide.

    Below layout.wide the segmented control holds the layout.measure column.
    At 1100px and up it is the 80px full-height rail (#281, fleet-config#968):
    tabs stacked icon over label, content offset past it even when an app's
    own `body`/`.app` padding shorthand loads after the vendored file.
    """
    nav_box = nav.locator(".tabs").bounding_box()
    assert nav_box is not None
    assert nav_box["width"] == 772 - 12 - 12  # layout.measure minus 2x --gap
    icon = nav.locator("#tabHome .tab-icon")
    expect(icon).to_be_visible()
    box = icon.bounding_box()
    assert box is not None
    assert box["width"] == pytest.approx(_DESKTOP_ICON_PX, abs=0.5)
    assert box["height"] == pytest.approx(_DESKTOP_ICON_PX, abs=0.5)
    # Painted by the stylesheet, not by per-path attributes, so the glyph takes
    # the tab's colour: accent-text when active, muted when not.
    assert _style(nav, "#tabHome .tab-icon", "fill") == "none"
    assert _style(nav, "#tabHome .tab-icon", "stroke") == _ACCENT_TEXT
    assert _style(nav, "#tabStats .tab-icon", "stroke") == _MUTED
    # The icon leads; the label follows.
    label = nav.locator("#tabHome .tab-label").bounding_box()
    assert label is not None
    assert box["x"] + box["width"] <= label["x"]
    # The pill's square hit layer (#348) is coarse-pointer only.
    assert _pseudo_content(nav, ".tabs", "::before") == "none"

    nav.set_viewport_size({"width": 1440, "height": 900})
    rail = nav.locator(".tabs").bounding_box()
    assert rail == {"x": 0, "y": 0, "width": _RAIL, "height": 900}, rail
    assert _pseudo_content(nav, ".tabs", "::before") == "none"
    assert _style(nav, ".tabs", "backgroundColor") == "rgb(255, 255, 255)"  # card
    assert _style(nav, ".tabs", "borderRightWidth") == "1px"
    assert _style(nav, ".tabs", "borderRightColor") == "rgb(209, 217, 224)"  # line
    assert _style(nav, ".tabs", "borderLeftWidth") == "0px"
    tabs = nav.evaluate(
        "() => [...document.querySelectorAll('.tabs .tab')].map((t) => {"
        " const l = t.querySelector('.tab-label'); const lb = l.getBoundingClientRect();"
        " const ib = t.querySelector('.tab-icon').getBoundingClientRect();"
        " const b = t.getBoundingClientRect();"
        " return { top: b.top, height: b.height, iconW: ib.width,"
        "  iconAbove: ib.bottom <= lb.top + 0.5, labelW: lb.width,"
        "  clipped: l.scrollWidth > l.clientWidth + 0.5 }; })"
    )
    assert [t["top"] for t in tabs] == sorted(t["top"] for t in tabs), tabs
    for t in tabs:
        assert t["iconAbove"] and t["iconW"] == 24, t  # icons.size.feature
        assert t["labelW"] > 1 and not t["clipped"], t
        assert t["height"] >= 44, t
    # Placement only: the active state is the column's, unchanged.
    assert _style(nav, "#tabHome", "color") == _ACCENT_TEXT
    expect(nav.locator("#tabHome")).to_have_attribute("aria-selected", "true")
    # Content clears the rail, even against an app's later padding shorthand.
    nav.add_style_tag(content="body { padding: 0; } .app { padding: 0 12px; }")
    app_x = nav.evaluate("() => document.querySelector('.app').getBoundingClientRect().x")
    assert app_x >= _RAIL, app_x


# An app's generic icon utility, as home-automation and local-llm-hub ship it
# on every glyph, the nav's included. It loads after nav-tabs.css.
_APP_ICON_UTILITY = ".icon { display: inline-block; width: 1em; height: 1em; }"


def _adopt_icon_utility(page: Page) -> None:
    page.add_style_tag(content=_APP_ICON_UTILITY)
    page.evaluate(
        "() => document.querySelectorAll('.tabs .tab-icon')"
        ".forEach((i) => i.classList.add('icon'))"
    )


def _icon_width(page: Page) -> float:
    box = page.locator("#tabHome .tab-icon").bounding_box()
    assert box is not None
    return float(box["width"])


def test_app_icon_utility_does_not_resize_nav_glyphs(nav: Page) -> None:
    """An app's later `.icon { width: 1em }` can't shrink the nav's glyphs (#303).

    The icon-size rules used to be a bare `.tab-icon`, the same specificity as
    an app's icon utility, so whichever stylesheet loaded last won: the rail's
    icons rendered at 1em of the 12px caption (12px, not 24px) in
    home-automation, and local-llm-hub was right only because its styles.css
    loads first. The rail also keeps its 24px when an app leaves
    `--icon-feature` undefined.
    """
    _adopt_icon_utility(nav)
    assert _icon_width(nav) == pytest.approx(_DESKTOP_ICON_PX, abs=0.5)
    nav.evaluate(
        "() => document.documentElement.style.setProperty('--icon-feature', 'initial')"
    )
    nav.set_viewport_size({"width": 1440, "height": 900})
    assert _icon_width(nav) == 24  # icons.size.feature


def test_app_icon_utility_does_not_resize_pill_glyphs(nav_mobile: Page) -> None:
    """The pill's 24px glyph survives an app's later icon utility too (#303)."""
    _adopt_icon_utility(nav_mobile)
    assert _icon_width(nav_mobile) == 24  # the iOS tab-bar glyph size


_LONG_LABELS = ("Capture", "History", "Insights", "Energy", "Family")


def test_narrow_desktop_stacks_icon_over_label(nav: Page) -> None:
    """Below 520px on a fine pointer: never icon-only; the icon stacks over its label.

    Five tabs of 6-8 letters, the case that clipped with the icon beside the
    label (#278): every label renders whole under its centred icon, and each
    tab keeps the 44px floor.
    """
    nav.evaluate(
        "(labels) => { const bar = document.querySelector('.tabs');"
        " while (bar.querySelectorAll('.tab').length < labels.length)"
        "   bar.appendChild(bar.querySelector('.tab:last-child').cloneNode(true));"
        " bar.querySelectorAll('.tab-label').forEach((l, i) => { l.textContent = labels[i]; }); }",
        list(_LONG_LABELS),
    )
    for width in (320, 500):
        nav.set_viewport_size({"width": width, "height": 800})
        metrics = nav.evaluate(
            "() => [...document.querySelectorAll('.tabs .tab')].map((t) => {"
            " const l = t.querySelector('.tab-label').getBoundingClientRect();"
            " const i = t.querySelector('.tab-icon').getBoundingClientRect();"
            " const b = t.getBoundingClientRect(); const s = t.querySelector('.tab-label');"
            " return { clipped: s.scrollWidth > s.clientWidth + 0.5, labelW: l.width,"
            "  iconAbove: i.bottom <= l.top + 0.5, height: b.height,"
            "  offCentre: Math.abs((i.left + i.right) / 2 - (b.left + b.right) / 2) }; })"
        )
        assert len(metrics) == len(_LONG_LABELS)
        for label, m in zip(_LONG_LABELS, metrics):
            assert not m["clipped"] and m["labelW"] > 1, (width, label, m)
            assert m["iconAbove"], (width, label, m)
            assert m["height"] >= 44, (width, label, m)
            assert m["offCentre"] <= 1, (width, label, m)
    expect(nav.locator("#tabHome")).to_have_accessible_name("Capture")


def test_mobile_pill_stacks_icon_over_label(nav_mobile: Page) -> None:
    """The floating pill keeps its 24px icon above the label; no rail when coarse.

    The phone `.app` padding is part of the same contract: the top is the safe
    area plus the 24px top scroll fade band (the emulator's safe area is 0), so
    the first card starts where the fade ends; the sides keep `--gap` and the
    bottom keeps the reserve that clears the floating bar and its fade.
    """
    assert _style(nav_mobile, ".app", "paddingTop") == "24px"
    assert _style(nav_mobile, ".app", "paddingLeft") == "12px"
    assert _style(nav_mobile, ".app", "paddingRight") == "12px"
    assert _style(nav_mobile, ".app", "paddingBottom") == f"{21 + 61 + 21 + 12}px"
    icon = nav_mobile.locator("#tabHome .tab-icon")
    expect(icon).to_be_visible()
    assert _style(nav_mobile, "#tabHome .tab-icon", "width") == "24px"
    assert _style(nav_mobile, "#tabHome .tab-icon", "height") == "24px"
    assert _style(nav_mobile, "#tabHome .tab-icon", "stroke") == _ACCENT_TEXT
    box = icon.bounding_box()
    label = nav_mobile.locator("#tabHome .tab-label").bounding_box()
    assert box is not None and label is not None
    assert box["y"] + box["height"] <= label["y"]
    # A coarse pointer never gets the wide-layout rail, at any width (#281).
    nav_mobile.set_viewport_size({"width": 1440, "height": 900})
    assert nav_mobile.evaluate(f"matchMedia('(min-width: {_WIDE}px)').matches")
    bar = nav_mobile.locator(".tabs").bounding_box()
    assert bar is not None and bar["width"] > _RAIL and bar["height"] < 100, bar


# --------------------------------------------------- pill vs the list beneath
# project-scaffolding#348 (TOUCH-02). Invented rows; the controls are 24px
# boxes carrying the `.hit-target` expansion to 44px, at both ends of the row,
# so they pass under the pill's left and right corners as the list scrolls.

_LIST_ROWS = 24
_ROW_PX = 56
_SCROLL_STEP = 7  # coprime with the row height, so rows cross the pill at every offset

_LIST_JS = """([rows, rowPx]) => {
  document.querySelectorAll('body > :not(.tabs):not(.app)')
    .forEach((e) => { e.style.display = 'none'; });
  const style = document.createElement('style');
  style.textContent = `
    .demo-row { display: flex; align-items: center; justify-content: space-between;
      height: ${rowPx}px; margin: 0; padding: 0; }
    .demo-pick { position: relative; width: 24px; height: 24px; padding: 0;
      border: 1px solid var(--line); background: transparent; }
    .demo-pick::before { content: ''; position: absolute; inset: -10px; }`;
  document.head.appendChild(style);
  const list = document.createElement('ul');
  list.style.cssText = 'list-style: none; margin: 0; padding: 0;';
  for (let i = 1; i <= rows; i++) {
    list.insertAdjacentHTML('beforeend',
      `<li class="demo-row"><button class="demo-pick" role="checkbox" aria-checked="false"
        aria-label="Select item ${i}"></button><span>Item ${i}</span>
        <button class="demo-pick" aria-label="More for item ${i}"></button></li>`);
  }
  document.querySelector('#paneHome').appendChild(list);
}"""

# At one scroll offset: every pair of a tab's and a row control's effective
# rects that intersect, and every 1px sample of that intersection that does
# not hit-test into the nav. A sample landing on the row is the ambiguous tap
# TOUCH-02 counts; the nav winning the whole intersection is a covered pair.
_PAIRS_JS = """(effRect) => {
  const eff = eval(`(${effRect})`);
  const box = (el) => { const r = eff(el);
    return { l: r.left - r.expandLeft, t: r.top - r.expandTop,
             r: r.right + r.expandRight, b: r.bottom + r.expandBottom }; };
  const nav = document.querySelector('.tabs');
  const tabs = [...nav.querySelectorAll('.tab')].map((el) => [el.id, box(el)]);
  const picks = [...document.querySelectorAll('.demo-pick')]
    .map((el) => [el.getAttribute('aria-label'), box(el)]);
  const pairs = [], leaks = [];
  for (const [tab, a] of tabs) for (const [pick, b] of picks) {
    const l = Math.max(a.l, b.l, 0), r = Math.min(a.r, b.r, innerWidth);
    const t = Math.max(a.t, b.t, 0), bt = Math.min(a.b, b.b, innerHeight);
    if (l >= r || t >= bt) continue;
    pairs.push([tab, pick]);
    sweep: for (let x = Math.floor(l) + 0.5; x < r; x++) for (let y = Math.floor(t) + 0.5; y < bt; y++) {
      if (x < l || y < t) continue;
      const hit = document.elementFromPoint(x, y);
      if (!hit || !nav.contains(hit)) {
        leaks.push({ tab, pick, x, y, hit: hit ? hit.getAttribute('aria-label') || hit.tagName : null });
        break sweep;
      }
    }
  }
  return { scrollY, pairs, leaks };
}"""


def test_pill_takes_every_tap_where_a_tab_meets_a_list_row(nav_mobile: Page) -> None:
    """No tab's tap rectangle shares a tappable point with a list row's (#348, TOUCH-02).

    390x844, coarse pointer. Rows scroll under the floating pill by design;
    the pill must then take every tap over each tab's whole rectangle. The
    tab is a rectangle and the pill's corners are rounded (radius-nav, 30px),
    so before the fix the four corner slivers of the outer tabs reached past
    the painted pill and a tap there landed on the row beneath. Scrolled to
    the end, the `.app` bottom reserve keeps the last row clear of the pill
    altogether.
    """
    page = nav_mobile
    page.evaluate(_LIST_JS, [_LIST_ROWS, _ROW_PX])
    max_scroll = page.evaluate(
        "() => document.scrollingElement.scrollHeight - innerHeight"
    )
    assert max_scroll > 4 * _ROW_PX, max_scroll  # rows really scroll under the pill
    crossed = 0
    for offset in [*range(0, max_scroll, _SCROLL_STEP), max_scroll]:
        page.evaluate("(y) => window.scrollTo({ top: y, behavior: 'instant' })", offset)
        state = page.evaluate(_PAIRS_JS, EFFECTIVE_RECT_JS)
        assert not state["leaks"], state
        crossed += bool(state["pairs"])
    assert crossed > 0, "no row control ever met a tab: the sweep proved nothing"
    # The square hit layer is never painted.
    assert page.evaluate(
        "() => getComputedStyle(document.querySelector('.tabs'), '::before').backgroundColor"
    ) == "rgba(0, 0, 0, 0)"
    # Scrolled to the end: the reserve clears the pill, so no pair meets at all.
    assert state["scrollY"] == max_scroll and not state["pairs"], state
    last = page.evaluate(
        "() => document.querySelector('.demo-row:last-child').getBoundingClientRect().bottom"
    )
    bar = page.locator(".tabs").bounding_box()
    assert bar is not None
    assert bar["y"] - last >= 21 + 12, (last, bar)  # --bottom-tabs-margin + --gap


def test_mobile_pill_active_tab_is_accent_text_on_a_translucent_capsule(
    nav_mobile: Page,
) -> None:
    """Active tab: accent text and icon over the translucent `--tabbar-pill` capsule, both themes.

    Regression for the dark-mode "black hole": the active tab used to fill
    with `--card-off` (dark canvas-subtle, true black), which read as a hole
    punched through the translucent tabbar. The capsule must stay translucent.
    Before `initNavTabs` has placed the sliding capsule the active tab paints
    the same fill itself (`.tabs:not(.has-pill)`), so frame one is already right;
    after it the sliding `.tab-pill` carries the fill and the tab is clear.
    """
    assert _style(nav_mobile, "#tabHome", "color") == _ACCENT_TEXT
    assert 0 < _alpha(_style(nav_mobile, "#tabHome", "backgroundColor")) < 1

    _init_nav(nav_mobile)
    assert _alpha(_style(nav_mobile, "#tabHome", "backgroundColor")) == 0
    assert 0 < _alpha(_style(nav_mobile, ".tab-pill", "backgroundColor")) < 1

    _set_theme(nav_mobile, "dark")
    _wait_style(nav_mobile, "#tabHome", "color", _ACCENT_TEXT_DARK)
    dark_bg = _style(nav_mobile, ".tab-pill", "backgroundColor")
    # The pre-fix `--card-off` fill resolved to this exact opaque literal
    # (#010409 -- demo.html's dark `--card-off`, #299).
    assert dark_bg != "rgb(1, 4, 9)"
    assert 0 < _alpha(dark_bg) < 1


# --------------------------------------------------------------- count badge
# project-scaffolding#338. Fictional data only: the tabs are the skeleton's
# placeholders (Home / Stats / History).

_ATTENTION = "rgb(154, 103, 0)"  # demo.html :root --attention (design.md)
_ATTENTION_DARK = "rgb(210, 153, 34)"
_DANGER = "rgb(207, 34, 46)"  # demo.html :root --deficit (design.md danger)
_DANGER_DARK = "rgb(248, 81, 73)"


def _init_nav(page: Page) -> None:
    """Run the real `initNavTabs` on the grafted skeleton (the other tests need only CSS)."""
    page.evaluate(
        "async () => { const m = await import('/_vendored/nav/nav-tabs.js');"
        " window.__nav = m.initNavTabs(); }"
    )
    # The sliding capsule starts `.no-anim` and drops it two frames later; a DOM
    # snapshot taken before that would differ from one taken after.
    page.wait_for_function(
        "() => { const p = document.querySelector('.tab-pill');"
        " return !p || !p.classList.contains('no-anim'); }"
    )


def _set_badge(
    page: Page,
    tab: str,
    count: object,
    noun: str | None = None,
    tone: str | None = None,
) -> None:
    page.evaluate(
        "([t, c, n, o]) => window.__nav.setBadge(t, c, n ?? undefined, o ?? undefined)",
        [tab, count, noun, tone],
    )


def _badge_text(page: Page, tab: str) -> str | None:
    return page.evaluate(
        "(t) => { const b = document.querySelector(`.tab[data-tab=${t}] .tab-badge`);"
        " return b ? b.textContent : null; }",
        tab,
    )


def test_no_set_badge_call_leaves_the_dom_untouched(nav: Page) -> None:
    """An app that never calls setBadge has no badge nodes, and a round trip restores the DOM."""
    _init_nav(nav)
    for cls in (".tab-badge", ".tab-badge-sr", ".tab-icon-wrap"):
        assert nav.locator(cls).count() == 0, cls
    before = nav.evaluate("() => document.querySelector('.tabs').outerHTML")
    _set_badge(nav, "stats", 3, "waiting")
    assert nav.locator(".tab-badge").count() == 1
    _set_badge(nav, "stats", 0)
    assert nav.evaluate("() => document.querySelector('.tabs').outerHTML") == before


def test_set_badge_count_rules(nav: Page) -> None:
    """1-9 show the digit, 10+ show 9+, 0 / null / junk remove it; an unknown tab is a no-op."""
    _init_nav(nav)
    for count, shown in ((1, "1"), (9, "9"), (10, "9+"), (250, "9+"), (3.7, "3")):
        _set_badge(nav, "stats", count)
        assert _badge_text(nav, "stats") == shown, count
    for gone in (0, None, "nope", -2):
        _set_badge(nav, "stats", 4)
        assert _badge_text(nav, "stats") == "4"
        _set_badge(nav, "stats", gone)
        assert _badge_text(nav, "stats") is None, gone
    _set_badge(nav, "no-such-tab", 5)
    assert nav.locator(".tab-badge").count() == 0
    # A repeat call updates the node in place instead of stacking another.
    _set_badge(nav, "stats", 2)
    _set_badge(nav, "stats", 5)
    assert nav.locator("#tabStats .tab-badge").count() == 1
    assert nav.locator("#tabStats .tab-badge-sr").count() == 1


def test_badge_is_in_the_accessible_name_once(nav: Page) -> None:
    """The tab's name carries the count; the painted digit is aria-hidden so it is not read twice."""
    _init_nav(nav)
    _set_badge(nav, "stats", 2, "waiting")
    expect(nav.locator("#tabStats")).to_have_accessible_name("Stats, 2 waiting")
    expect(nav.locator("#tabStats .tab-badge")).to_have_attribute("aria-hidden", "true")
    _set_badge(nav, "stats", 12, "waiting")  # painted 9+, spoken exactly
    expect(nav.locator("#tabStats")).to_have_accessible_name("Stats, 12 waiting")
    _set_badge(nav, "stats", 2)  # no noun
    expect(nav.locator("#tabStats")).to_have_accessible_name("Stats, 2")
    _set_badge(nav, "stats", 0)
    expect(nav.locator("#tabStats")).to_have_accessible_name("Stats")
    # The aria tree shows one name per tab, with no separate badge node.
    _set_badge(nav, "history", 1, "waiting")
    expect(nav.locator(".tabs")).to_match_aria_snapshot(
        """
        - tablist "Sections":
          - tab "Home" [selected]
          - tab "Stats"
          - tab "History, 1 waiting"
        """
    )


def test_badge_text_meets_contrast_in_both_themes(nav: Page) -> None:
    """attention fill + card text clears WCAG AA (4.5:1), measured as rendered, light and dark."""
    _init_nav(nav)
    _set_badge(nav, "stats", 2, "waiting")
    badge = ".tab-badge"
    assert _style(nav, badge, "backgroundColor") == _ATTENTION
    fill, text = _style(nav, badge, "backgroundColor"), _style(nav, badge, "color")
    assert _contrast(text, fill, "rgb(255, 255, 255)") >= 4.5

    _set_theme(nav, "dark")
    _wait_style(nav, badge, "backgroundColor", _ATTENTION_DARK)
    fill, text = _style(nav, badge, "backgroundColor"), _style(nav, badge, "color")
    assert _contrast(text, fill, "rgb(22, 27, 34)") >= 4.5


def test_danger_badge_tone_meets_contrast_in_both_themes(nav: Page) -> None:
    """tone 'danger' paints the danger fill under card text at 4.5:1+, light and dark (#342)."""
    _init_nav(nav)
    badge = ".tab-badge"
    _set_badge(nav, "stats", 2, "triggered", "danger")
    expect(nav.locator(badge)).to_have_attribute("data-tone", "danger")
    assert _style(nav, badge, "backgroundColor") == _DANGER
    fill, text = _style(nav, badge, "backgroundColor"), _style(nav, badge, "color")
    assert _contrast(text, fill, "rgb(255, 255, 255)") >= 4.5

    _set_theme(nav, "dark")
    _wait_style(nav, badge, "backgroundColor", _DANGER_DARK)
    fill, text = _style(nav, badge, "backgroundColor"), _style(nav, badge, "color")
    assert _contrast(text, fill, "rgb(22, 27, 34)") >= 4.5


def test_badge_tone_defaults_to_attention_and_repaints(nav: Page) -> None:
    """Omitting the tone (or an unknown one) is attention; a later call repaints the same badge."""
    _init_nav(nav)
    badge = ".tab-badge"
    _set_badge(nav, "stats", 2, "waiting")
    expect(nav.locator(badge)).to_have_attribute("data-tone", "attention")
    assert _style(nav, badge, "backgroundColor") == _ATTENTION
    _set_badge(nav, "stats", 2, "waiting", "no-such-tone")
    assert _style(nav, badge, "backgroundColor") == _ATTENTION
    _set_badge(nav, "stats", 3, "triggered", "danger")
    assert nav.locator(badge).count() == 1
    assert _style(nav, badge, "backgroundColor") == _DANGER
    _set_badge(nav, "stats", 3, "waiting")
    assert _style(nav, badge, "backgroundColor") == _ATTENTION


def _geometry(page: Page, tab: str) -> dict[str, float]:
    return page.evaluate(
        "(t) => { const q = (s) => document.querySelector(`.tab[data-tab=${t}] ${s}`);"
        " const r = (s) => { const e = q(s); return e && e.getBoundingClientRect(); };"
        " const b = r('.tab-badge'), i = r('.tab-icon'), l = r('.tab-label'),"
        "  tab = q('.tab-label').closest('.tab').getBoundingClientRect(),"
        "  bar = document.querySelector('.tabs').getBoundingClientRect();"
        " return { bx: b ? b.x : 0, by: b ? b.y : 0, bw: b ? b.width : 0, bh: b ? b.height : 0,"
        "  ix: i.x, iy: i.y, iw: i.width, lx: l.x, ly: l.y, lw: l.width,"
        "  tx: tab.x, tw: tab.width, barTop: bar.top, vw: innerWidth }; }",
        tab,
    )


def _assert_badge_on_icon_corner(page: Page, tab: str, where: str) -> None:
    """The badge is 16px tall, straddles the icon's top-right corner, inside its tab, on screen."""
    g = _geometry(page, tab)
    assert g["bh"] == 16 and g["bw"] >= 16, (where, g)
    assert g["bx"] >= g["ix"] + g["iw"] / 2, (where, g)  # right of the icon's centre
    assert g["bx"] < g["ix"] + g["iw"], (where, g)  # overlapping its right edge
    assert g["by"] < g["iy"] < g["by"] + g["bh"], (where, g)  # straddling its top
    assert g["bx"] + g["bw"] <= g["tx"] + g["tw"], (where, g)  # inside its tab
    assert g["by"] >= 0 and g["bx"] + g["bw"] <= g["vw"], (where, g)  # on screen
    expect(page.locator(f".tab[data-tab={tab}] .tab-badge")).to_be_visible()


def _assert_badge_does_not_move_layout(page: Page, tab: str, where: str) -> None:
    """Showing the badge leaves the icon and label where they were."""
    _set_badge(page, tab, 0)
    before = _geometry(page, tab)
    _set_badge(page, tab, 3, "waiting")
    after = _geometry(page, tab)
    for key in ("ix", "iy", "iw", "lx", "ly", "lw"):
        assert after[key] == pytest.approx(before[key], abs=0.5), (where, key, before, after)


def test_badge_in_inline_desktop_tabs_and_wide_rail(nav: Page) -> None:
    """Desktop segmented control (icon beside label), the narrow stack, and the 80px rail."""
    _init_nav(nav)
    _set_badge(nav, "stats", 3, "waiting")
    _assert_badge_on_icon_corner(nav, "stats", "inline")
    _assert_badge_does_not_move_layout(nav, "stats", "inline")
    # On the active tab the accent-soft tint must not hide it: opaque attention fill.
    _set_badge(nav, "home", 2, "waiting")
    _assert_badge_on_icon_corner(nav, "home", "inline active")
    assert _rgba(_style(nav, "#tabHome .tab-badge", "backgroundColor")) == (154, 103, 0, 1.0)

    nav.set_viewport_size({"width": 400, "height": 800})  # fine pointer, icon over label
    _assert_badge_on_icon_corner(nav, "stats", "narrow stack")

    nav.set_viewport_size({"width": 1440, "height": 900})
    _assert_badge_on_icon_corner(nav, "stats", "rail")
    g = _geometry(nav, "home")
    assert g["bx"] + g["bw"] <= _RAIL, g  # not clipped by the 80px rail
    _assert_badge_does_not_move_layout(nav, "stats", "rail")


def test_badge_in_mobile_pill(nav_mobile: Page) -> None:
    """The phone pill (coarse pointer, iPhone-size viewport), on an inactive and the active tab."""
    _init_nav(nav_mobile)
    _set_badge(nav_mobile, "stats", 3, "waiting")
    _assert_badge_on_icon_corner(nav_mobile, "stats", "pill")
    g = _geometry(nav_mobile, "stats")
    assert g["by"] >= g["barTop"], g  # inside the bar, not poking out of its top edge
    _assert_badge_does_not_move_layout(nav_mobile, "stats", "pill")
    _set_badge(nav_mobile, "home", 12, "waiting")
    _assert_badge_on_icon_corner(nav_mobile, "home", "pill active")
    assert _style(nav_mobile, "#tabHome .tab-badge", "backgroundColor") == _ATTENTION
    # Never animated: no keyframes and no transition on the badge.
    assert _style(nav_mobile, "#tabHome .tab-badge", "animationName") == "none"
    assert _style(nav_mobile, "#tabHome .tab-badge", "transitionDuration") == "0s"


def test_badge_geometry_does_not_scale_with_text_size(nav: Page) -> None:
    """px, not rem: the Large text step (a bigger root font size) leaves the badge at 12px / 16px."""
    _init_nav(nav)
    _set_badge(nav, "stats", 3, "waiting")
    nav.evaluate("() => { document.documentElement.style.fontSize = '22px'; }")
    assert _style(nav, ".tab-badge", "fontSize") == "12px"
    assert _style(nav, ".tab-badge", "height") == "16px"
