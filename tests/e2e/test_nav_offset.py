"""Floating bottom-tab bar geometry per tab on a 390x844 phone.

An installed iOS app anchors `position: fixed` to the physical screen bottom
only while the document is scrollable, so a tab shorter than the screen left
the bar floating higher than on the first tab. Desktop engines don't reproduce
that anchoring, so beyond the bar's measured offset this pins the mechanism that
prevents it: every tab's document scrolls by at least 1px. It also pins the
scroll-edge fade bands at the top and under the bar. Run on both engines:
`pytest tests/e2e/test_nav_offset.py --browser chromium --browser webkit`.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator

import pytest
from PIL import Image
from playwright.sync_api import Browser, Page

from tests.e2e._nav_graft import mount_nav, phone_nav

_TABS = ("home", "stats", "history")

# The panes are left empty so every tab is far shorter than the screen, the case
# that used to float the bar; the gallery the skeleton is grafted onto is hidden
# for the same reason.
_SHORT_TABS_JS = """() => {
  document.querySelectorAll('body > :not(.tabs):not(.app)')
    .forEach((e) => { e.style.display = 'none'; });
}"""

_MEASURE_JS = """() => {
  const bar = document.querySelector('.tabs').getBoundingClientRect();
  const root = document.scrollingElement;
  return {
    pill: matchMedia('(pointer: coarse) and (max-width: 520px)').matches,
    barBottomOffset: window.innerHeight - bar.bottom,
    overflow: root.scrollHeight - root.clientHeight,
  };
}"""

_FADE_JS = """pseudo => {
  const s = getComputedStyle(document.body, pseudo);
  const bar = getComputedStyle(document.querySelector('.tabs'));
  return {
    position: s.position, top: s.top, bottom: s.bottom, height: parseFloat(s.height),
    image: s.backgroundImage, pointerEvents: s.pointerEvents,
    z: Number(s.zIndex), barZ: Number(bar.zIndex),
  };
}"""


@pytest.fixture()
def nav_phone(static_server: str, browser: Browser) -> Iterator[Page]:
    """The real `initNavTabs` on the phone pill, over short (empty) tabs."""
    with phone_nav(browser, static_server) as page:
        page.evaluate(_SHORT_TABS_JS)
        page.evaluate(
            "async () => { const m = await import('/_vendored/nav/nav-tabs.js');"
            " window.__nav = m.initNavTabs(); }"
        )
        yield page


def test_bar_sits_at_the_same_offset_on_every_tab(nav_phone: Page) -> None:
    page = nav_phone
    offsets: dict[str, float] = {}
    for tab in _TABS:
        page.locator(f".tabs .tab[data-tab='{tab}']").click()
        page.wait_for_selector(f".tabs .tab[data-tab='{tab}'].active")
        m = page.evaluate(_MEASURE_JS)
        assert m["pill"], m
        # The scrollable document is what keeps iOS anchoring the bar to the
        # screen bottom on a short tab.
        assert m["overflow"] >= 1, (tab, m)
        offsets[tab] = round(m["barBottomOffset"], 1)

    assert offsets["home"] == 21, offsets
    assert set(offsets.values()) == {offsets["home"]}, offsets


# `--nav-fade-band` (the top band) and `--nav-fade-tail` (the bottom band's
# reach above the bar) defaults.
_BAND = 12
_TAIL = 24
# The one eased curve, as page-colour coverage from the screen edge inward:
# (fraction of the band, coverage). Content opacity is one minus coverage.
_CURVE = ((0, 1), (0.10, 0.75), (0.25, 0.5), (0.50, 0.25), (0.75, 0.08), (1, 0))

# One gradient stop as both engines serialize it: a colour, then its offset.
_STOP_RE = re.compile(r"(rgba?\([^)]*\)|color\(srgb [^)]*\)|transparent)\s+([\d.]+)(px|%)")


def _stops(image: str) -> list[tuple[float, str, float]]:
    """(alpha, rgb, offset in px or %) per stop of a fade band's gradient."""
    stops = []
    for color, offset, _unit in _STOP_RE.findall(image):
        if color == "transparent":
            alpha, rgb = 0.0, ""
        elif color.startswith("color("):
            r, g, b, *rest = color[len("color(srgb "):-1].replace("/", " ").split()
            alpha = float(rest[0]) if rest else 1.0
            rgb = ",".join(str(round(float(c) * 255)) for c in (r, g, b))
        else:
            parts = [c.strip() for c in color[color.index("(") + 1:-1].split(",")]
            alpha = float(parts[3]) if len(parts) == 4 else 1.0
            rgb = ",".join(parts[:3])
        stops.append((alpha, rgb, float(offset)))
    return stops


def test_scroll_edge_fades_top_and_bottom(nav_phone: Page) -> None:
    page = nav_phone

    bottom = page.evaluate(_FADE_JS, "::before")
    assert bottom["position"] == "fixed", bottom
    assert bottom["bottom"] == "0px", bottom
    # The tail above the bar + the 61px bar + its 21px bottom margin: the band
    # runs to the screen edge with no solid zone behind the bar.
    assert bottom["height"] == _TAIL + 61 + 21, bottom

    top = page.evaluate(_FADE_JS, "::after")
    assert top["position"] == "fixed", top
    # From the viewport top (safe area 0 here), one thin band.
    assert top["top"] == "0px", top
    assert top["height"] == _BAND, top

    for fade in (bottom, top):
        assert "linear-gradient" in fade["image"], fade
        assert "to top" not in fade["image"], fade
        assert fade["pointerEvents"] == "none", fade
        assert fade["z"] < fade["barZ"], fade


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_fades_follow_one_eased_curve_to_the_edge(nav_phone: Page, theme: str) -> None:
    """Both edges: content stays at least half visible over the inner three
    quarters of the band and vanishes only at the screen edge, with no solid
    zone (on the owner's iPhone a solid band behind the bar read as a wall and
    a short ramp as a hard cut). In the page colour of either theme."""
    page = nav_phone
    if theme == "dark":
        page.evaluate("() => { document.documentElement.dataset.theme = 'dark'; }")
    bg = page.evaluate(
        r"() => getComputedStyle(document.body).backgroundColor.match(/\d+/g).slice(0, 3).join(',')"
    )
    bottom_image, top_image = (page.evaluate(_FADE_JS, p)["image"] for p in ("::before", "::after"))

    # Top, drawn from the screen edge down, offsets in px of the band.
    top = _stops(top_image)
    assert [round(a, 2) for a, _, _ in top] == [c for _, c in _CURVE], top_image
    assert [o for _, _, o in top] == pytest.approx([f * _BAND for f, _ in _CURVE], abs=0.01), top
    # Bottom, drawn from the content down to the screen edge, offsets in %.
    bottom = _stops(bottom_image)
    assert [round(a, 2) for a, _, _ in bottom] == [c for _, c in reversed(_CURVE)], bottom_image
    assert [o for _, _, o in bottom] == pytest.approx([100 - f * 100 for f, _ in reversed(_CURVE)]), bottom
    assert all(rgb == bg for a, rgb, _ in top + bottom if a > 0), (bg, top, bottom)


def test_top_fade_is_off_at_rest_and_on_after_one_band_of_scroll(
    static_server: str, browser: Browser
) -> None:
    """At scroll-top the first row sits right under the status bar, undimmed;
    the top band switches on over the first band of scroll."""
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    try:
        page = context.new_page()
        page.goto(f"{static_server}/_vendored/demo.html?nav")
        page.wait_for_selector("body[data-nav-demo-ready='1']")
        padding = page.evaluate("() => getComputedStyle(document.querySelector('.app')).paddingTop")
        assert padding == "0px", padding
        seen = []
        for y in (0, _BAND // 2, _BAND * 10, 0):
            page.evaluate(f"() => window.scrollTo(0, {y})")
            page.wait_for_function(
                f"() => Math.round(scrollY) === {y} && document.documentElement.style"
                f".getPropertyValue('--nav-fade-on') === String(Math.min(1, {y} / {_BAND}))"
            )
            seen.append(page.evaluate("() => Number(getComputedStyle(document.body, '::after').opacity)"))
        assert seen == pytest.approx([0, 0.5, 1, 0], abs=0.01), seen
    finally:
        context.close()


def test_installed_app_anchors_the_bar_from_the_large_viewport_top(
    nav_phone: Page, browser_name: str
) -> None:
    """In the installed app iOS grows the viewport after launch, so the bar is
    placed from the top with 100lvh (its final position on frame one) rather
    than from the moving bottom edge. No engine here emulates the standalone
    display mode, so the nav's own standalone rules are applied unconditionally."""
    page = nav_phone
    if browser_name != "chromium":
        pytest.skip("the standalone rules are applied through a constructed stylesheet; Chromium only")

    m = page.evaluate("""() => {
      const found = [];
      const walk = rules => {
        for (const r of rules) {
          if (r.media && r.conditionText.includes('display-mode: standalone')) found.push(r);
          else if (r.cssRules) walk(r.cssRules);
        }
      };
      for (const sheet of document.styleSheets) {
        if (sheet.href && sheet.href.includes('nav-tabs.css')) walk(sheet.cssRules);
      }
      const sheet = new CSSStyleSheet();
      sheet.replaceSync(found.map(r => Array.from(r.cssRules, c => c.cssText).join(' ')).join(' '));
      document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
      // Grow the bar: a top-anchored bar keeps its top edge, a bottom-anchored
      // one keeps its bottom edge.
      const bar = document.querySelector('.tabs');
      const before = bar.getBoundingClientRect();
      bar.style.height = (before.height + 40) + 'px';
      const after = bar.getBoundingClientRect();
      bar.style.height = '';
      const floor = found.flatMap(r => Array.from(r.cssRules))
        .filter(c => c.selectorText === 'html').map(c => c.cssText).join(' ');
      return { blocks: found.length, topBefore: before.top, topAfter: after.top, lvh: innerHeight, floor };
    }""")
    assert m["blocks"] == 1, m
    # The scrollable-document floor keys to the stable large viewport, so the
    # keyboard's viewport resize never re-lays out the document.
    assert "100lvh" in m["floor"] and "dvh" not in m["floor"], m
    assert m["topAfter"] == m["topBefore"], m
    # 21px margin + 61px bar above the large-viewport bottom.
    assert m["topBefore"] == m["lvh"] - 82, m


def test_document_stays_scrollable_with_the_body_pinned(nav_phone: Page) -> None:
    """An app-side scroll lock pins the body while a dialog is open; if that left
    the document unscrollable, an installed iOS app would shrink its viewport and
    re-grow it over ~3s on close, revealing the bar bit by bit."""
    page = nav_phone
    page.evaluate(
        "() => { const b = document.body; b.style.position = 'fixed';"
        " b.style.top = '0'; b.style.left = '0'; b.style.right = '0'; b.style.width = '100%'; }"
    )
    overflow = page.evaluate(
        "() => document.scrollingElement.scrollHeight - document.scrollingElement.clientHeight"
    )
    assert overflow >= 1, overflow


def test_resize_without_moved_cells_leaves_the_pill_alone(nav_phone: Page) -> None:
    """iOS fires resize on every keyboard open and close; when the tab cells did
    not move, the capsule (and so the glass bar) must not be restyled."""
    page = nav_phone
    mutations = page.evaluate("""() => new Promise(resolve => {
      const pill = document.querySelector('.tabs .tab-pill');
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const seen = [];
        const obs = new MutationObserver(list => list.forEach(m => seen.push(m.attributeName)));
        obs.observe(pill, { attributes: true });
        window.dispatchEvent(new Event('resize'));
        requestAnimationFrame(() => requestAnimationFrame(() => { obs.disconnect(); resolve(seen); }));
      }));
    })""")
    assert mutations == [], mutations

    # A resize that does move the cells still re-places the capsule.
    page.set_viewport_size({"width": 360, "height": 844})
    page.wait_for_function(
        "() => { const p = document.querySelector('.tabs .tab-pill');"
        " const on = document.querySelector('.tabs .tab.active');"
        " return p.style.getPropertyValue('--pill-w') === on.offsetWidth + 'px'; }"
    )


def test_gallery_nav_mode_plays_the_installed_app(static_server: str, browser: Browser) -> None:
    """demo.html?nav is the on-device check page: the gallery becomes the Home
    tab of the real nav, and the status bar colour follows the theme toggle."""
    context = browser.new_context(
        viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True
    )
    try:
        page = context.new_page()
        page.goto(f"{static_server}/_vendored/demo.html?nav")
        page.wait_for_selector("body[data-nav-demo-ready='1']")
        assert page.locator("body > nav.tabs").count() == 1
        assert page.locator("body > main.app #paneHome > .gallery").count() == 1
        overflow = page.evaluate(
            "() => document.scrollingElement.scrollHeight - innerHeight"
        )
        assert overflow > 844, overflow
        theme_color = "() => document.querySelector('meta[name=theme-color]').content"
        light = page.evaluate(theme_color)
        page.locator("#themeToggle").click()
        dark = page.evaluate(theme_color)
        assert light != dark, (light, dark)
        assert dark == page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    finally:
        context.close()


_CONTRAST = (255, 0, 255)

# The page under the fixed layers is one flat contrast colour and everything
# but the body's own fade layers is hidden, so each row's pixel gives the
# bottom band's coverage.
_FLAT_PAGE_JS = r"""([contrast]) => {
  const probe = document.createElement('div');
  probe.style.background = 'var(--bg)';
  document.body.append(probe);
  const bg = getComputedStyle(probe).backgroundColor.match(/\d+/g).slice(0, 3).map(Number);
  probe.remove();
  const style = document.createElement('style');
  style.textContent = `
    html, body { background: rgb(${contrast.join(',')}) !important; }
    body > * { visibility: hidden !important; }`;
  document.head.append(style);
  return bg;
}"""


# WebKit only: the engine of the installed iOS app the curve is tuned on.
@pytest.mark.only_browser("webkit")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_bottom_fade_eases_to_solid_at_the_screen_edge_without_a_step(
    static_server: str, browser: Browser, theme: str
) -> None:
    """Going down from the content the page colour covers smoothly, with no
    step between rows, and is solid only at the very screen edge."""
    context = browser.new_context(
        viewport={"width": 430, "height": 932}, has_touch=True, is_mobile=True,
        device_scale_factor=1,
    )
    height = _TAIL + 61 + 21
    top = 932 - height - 4
    try:
        page = context.new_page()
        mount_nav(page, static_server)
        if theme == "dark":
            page.evaluate("() => { document.documentElement.dataset.theme = 'dark'; }")
        bg = page.evaluate(_FLAT_PAGE_JS, [list(_CONTRAST)])
        shot = Image.open(io.BytesIO(page.screenshot(
            clip={"x": 0, "y": top, "width": 430, "height": 932 - top}
        ))).convert("RGB")
    finally:
        context.close()

    channel = max(range(3), key=lambda c: abs(_CONTRAST[c] - bg[c]))
    span = _CONTRAST[channel] - bg[channel]
    coverage = [
        round((_CONTRAST[channel] - shot.getpixel((215, y))[channel]) / span, 3)
        for y in range(shot.height)
    ]
    assert max(coverage[:4]) <= 0.02, (theme, coverage)
    # Content still at least half visible three quarters of the way down.
    assert coverage[4 + round(height * 0.75)] <= 0.52, (theme, coverage)
    assert coverage[-1] >= 0.95, (theme, coverage)
    steps = [coverage[y + 1] - coverage[y] for y in range(len(coverage) - 1)]
    assert min(steps) >= -0.02, (theme, coverage)
    assert max(steps) <= 0.05, (theme, coverage)


# Hides both scroll-edge fade layers, so a clip shot with them on can be
# compared against the same pixels with nothing drawn over the content.
_FADES_OFF_CSS = "body::before, body::after { display: none !important; }"


def _undimmed(page: Page, selector: str) -> bool:
    """Whether the element's pixels are identical with the fades on and off."""
    box = page.locator(selector).bounding_box()
    assert box, selector
    clip = {"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"]}
    on = page.screenshot(clip=clip, animations="disabled")
    off_style = page.add_style_tag(content=_FADES_OFF_CSS)
    off = page.screenshot(clip=clip, animations="disabled")
    off_style.evaluate("el => el.remove()")
    return on == off


# A long page ending in the build-identity footer (the vendored page-foot's
# shape, last child of .app) with no margin of its own: the strict case.
_LONG_PAGE_WITH_FOOT_JS = """() => {
  const app = document.querySelector('.app');
  const filler = document.createElement('div');
  filler.style.cssText = 'height: 1600px; background: var(--card)';
  const foot = document.createElement('footer');
  foot.className = 'page-foot';
  foot.id = 'testFoot';
  foot.style.cssText = 'margin: 0; text-align: center; color: var(--ink)';
  foot.innerHTML = '<p style="margin: 0">Build: 0123abc · 2026-01-01 00:00</p>';
  app.append(filler, foot);
}"""


@pytest.mark.parametrize("tail", [None, 60])
def test_build_footer_ends_a_gap_above_the_bottom_fade(nav_phone: Page, tail: int | None) -> None:
    """Scrolled to the end, the last content (the build footer) sits a full
    --gap above the bottom fade's top edge, so it is never dimmed, including
    when an app lengthens the fade's tail."""
    page = nav_phone
    if tail is not None:
        page.evaluate(f"() => document.documentElement.style.setProperty('--nav-fade-tail', '{tail}px')")
    page.evaluate(_LONG_PAGE_WITH_FOOT_JS)
    page.evaluate("() => window.scrollTo(0, document.scrollingElement.scrollHeight)")
    page.wait_for_function(
        "() => Math.ceil(scrollY + innerHeight) >= document.scrollingElement.scrollHeight"
    )
    m = page.evaluate("""() => ({
      footBottom: document.getElementById('testFoot').getBoundingClientRect().bottom,
      fadeTop: innerHeight - parseFloat(getComputedStyle(document.body, '::before').height),
    })""")
    assert m["fadeTop"] - m["footBottom"] >= 12, m
    assert _undimmed(page, "#testFoot"), m


# task-os's header shape: a rounded header card as the first child of .app,
# under an app rule that keeps .app's top padding to the safe area alone.
_HEADER_CARD_JS = """([sticky]) => {
  const app = document.querySelector('.app');
  const head = document.createElement('div');
  head.className = 'card home-head';
  head.id = 'testHead';
  head.style.cssText = 'height: 56px; margin: 0 0 12px; border: 1px solid var(--line);'
    + 'border-radius: 16px; background: var(--card); box-sizing: border-box;'
    + (sticky ? 'position: sticky; top: 0; z-index: 2;' : '');
  const filler = document.createElement('div');
  filler.style.height = '1600px';
  app.prepend(head);
  app.append(filler);
  const style = document.createElement('style');
  style.textContent = '.app { padding-top: env(safe-area-inset-top, 0); }';
  document.head.append(style);
}"""


@pytest.mark.parametrize("standalone", [False, True], ids=["tab", "standalone"])
@pytest.mark.parametrize("sticky", [False, True], ids=["static", "sticky"])
def test_first_card_top_edge_is_undimmed_at_rest(
    static_server: str, browser: Browser, sticky: bool, standalone: bool
) -> None:
    """At scroll 0 nothing is dimmed: the first rounded header card's top edge,
    flush under the status bar, shows at full opacity, for a static or a
    sticky header, and in the installed app, whose 1px viewport-expanding
    scroll at startup must leave the top fade off once it returns to rest."""
    with phone_nav(browser, static_server) as page:
        page.evaluate(_SHORT_TABS_JS)
        page.evaluate(_HEADER_CARD_JS, [sticky])
        if standalone:
            page.evaluate(
                "() => { const real = window.matchMedia.bind(window);"
                " window.matchMedia = q => q.includes('display-mode: standalone')"
                " ? { matches: true, media: q, addEventListener() {}, removeEventListener() {} }"
                " : real(q); }"
            )
        page.evaluate(
            "async () => { const m = await import('/_vendored/nav/nav-tabs.js');"
            " window.__nav = m.initNavTabs(); }"
        )
        page.wait_for_function(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(true))))"
        )
        page.wait_for_function("() => scrollY === 0")
        top = page.evaluate("() => document.getElementById('testHead').getBoundingClientRect().top")
        assert top == 0, top
        assert _undimmed(page, "#testHead")
