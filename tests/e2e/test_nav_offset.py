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


# The fade band and its knee: `--nav-fade-band` and `--nav-fade-knee` defaults.
_BAND = 24
_KNEE = 0.3
# Solid page colour above the fixed origin: `--nav-fade-overhang`'s default.
_OVERHANG = 80

# One gradient stop as both engines serialize it: a colour, then its offset.
_STOP_RE = re.compile(r"(rgba?\([^)]*\)|color\(srgb [^)]*\))\s+([\d.]+)px")


def _stops(image: str) -> list[tuple[float, str, float]]:
    """(alpha, rgb, offset px) per stop of a fade band's gradient."""
    stops = []
    for color, offset in _STOP_RE.findall(image):
        if color.startswith("color("):
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
    # The fade band above the bar + the 61px bar + its 21px bottom margin.
    assert bottom["height"] == _BAND + 61 + 21, bottom

    top = page.evaluate(_FADE_JS, "::after")
    assert top["position"] == "fixed", top
    # Starts above the fixed origin (the installed app's status bar), then the
    # band, inside the .app top padding (safe area 0 here).
    assert top["top"] == f"-{_OVERHANG}px", top
    assert top["height"] == _OVERHANG + _BAND, top
    # Drawn from the screen edge down: strongest at the top, transparent last.
    assert "to top" not in top["image"], top

    for fade in (bottom, top):
        assert "linear-gradient" in fade["image"], fade
        assert fade["pointerEvents"] == "none", fade
        assert fade["z"] < fade["barZ"], fade


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_fade_drops_fast_to_half_then_trails_off(nav_phone: Page, theme: str) -> None:
    """Bottom: going down from the opaque middle the page colour covers content
    quickly to 50% at the knee, then a long light tail reaches solid at the edge.
    Top: that curve inverted, strongest at the screen edge and easing out to
    transparent over the content, so no fast ramp lands on the content side
    (on the owner's iPhone that ramp read as a hard cut across the header).
    Both in the page colour of either theme."""
    page = nav_phone
    if theme == "dark":
        page.evaluate("() => { document.documentElement.dataset.theme = 'dark'; }")
    bg = page.evaluate(
        r"() => getComputedStyle(document.body).backgroundColor.match(/\d+/g).slice(0, 3).join(',')"
    )
    images = [page.evaluate(_FADE_JS, p)["image"] for p in ("::before", "::after")]

    top = _stops(images[1])
    assert len(top) == 5, images[1]
    assert top[0][0] == 1 and top[0][2] == _OVERHANG, top
    assert top[-1][0] == 0 and top[-1][2] == _OVERHANG + _BAND, top
    assert [a for a, _, _ in top] == sorted((a for a, _, _ in top), reverse=True), top
    # The inverse of the bottom curve, stop for stop at the same offsets past
    # the solid overhang.
    for (ta, _, to), (ba, _, bo) in zip(top, _stops(images[0])):
        assert to - _OVERHANG == pytest.approx(bo, abs=0.01), (top, images[0])
        assert ta == pytest.approx(1 - ba, abs=0.01), (top, images[0])
    assert all(rgb == bg for a, rgb, _ in top if a > 0), (bg, top)

    stops = _stops(images[0])
    assert len(stops) == 5, images[0]
    alphas = [a for a, _, _ in stops]
    offsets = [o for _, _, o in stops]
    assert alphas[0] == 0 and offsets[0] == 0, stops
    assert alphas == sorted(alphas), stops
    assert alphas[2] == 0.5 and offsets[2] == pytest.approx(_BAND * _KNEE, abs=0.01), stops
    assert alphas[-1] == 1 and offsets[-1] == _BAND, stops
    # Fast to the knee, light after it.
    assert alphas[2] / offsets[2] > 2 * (1 - alphas[2]) / (offsets[-1] - offsets[2]), stops
    assert all(rgb == bg for a, rgb, _ in stops if a > 0), (bg, stops)


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


# The installed iOS app's status bar: content scrolls up behind it, but a
# `position: fixed; top: 0` layer starts below it, so the fixed layers are moved
# down by this much to play the device's geometry in a desktop engine.
_STATUS_BAR = 59
_CONTRAST = (255, 0, 255)

# Fixed layers start below the emulated status bar; the page under them is one
# flat contrast colour, so each row's pixel gives the top band's coverage.
_EMULATE_STATUS_BAR_JS = r"""([inset, contrast]) => {
  const probe = document.createElement('div');
  probe.style.background = 'var(--bg)';
  document.body.append(probe);
  const bg = getComputedStyle(probe).backgroundColor.match(/\d+/g).slice(0, 3).map(Number);
  probe.remove();
  const style = document.createElement('style');
  style.textContent = `
    body::after, body::before, .tabs { translate: 0 ${inset}px; }
    html, body { background: rgb(${contrast.join(',')}) !important; }
    body > * { visibility: hidden !important; }`;
  document.head.append(style);
  return bg;
}"""


# WebKit only: it is the engine of the installed iOS app this emulates, and
# Chromium does not paint the overhang of a fixed layer moved by `translate`.
@pytest.mark.only_browser("webkit")
@pytest.mark.parametrize("theme", ["light", "dark"])
def test_top_fade_covers_the_status_bar_strip_without_a_step(
    static_server: str, browser: Browser, theme: str
) -> None:
    """In the installed app (dark theme, owner's iPhone) the content behind the
    59px status bar showed through uncovered and the band began at its lower
    edge, so whatever scrolled under it was cut by a hard line. From the screen
    edge through the status bar the page colour must cover solid, then ease out
    over the band with no step between rows."""
    context = browser.new_context(
        viewport={"width": 430, "height": 932}, has_touch=True, is_mobile=True,
        device_scale_factor=1,
    )
    try:
        page = context.new_page()
        mount_nav(page, static_server)
        if theme == "dark":
            page.evaluate("() => { document.documentElement.dataset.theme = 'dark'; }")
        bg = page.evaluate(_EMULATE_STATUS_BAR_JS, [_STATUS_BAR, list(_CONTRAST)])
        rows = _STATUS_BAR + _BAND + 8
        shot = Image.open(io.BytesIO(page.screenshot(
            clip={"x": 0, "y": 0, "width": 430, "height": rows}
        ))).convert("RGB")
    finally:
        context.close()

    channel = max(range(3), key=lambda c: abs(_CONTRAST[c] - bg[c]))
    span = _CONTRAST[channel] - bg[channel]
    coverage = [
        round((_CONTRAST[channel] - shot.getpixel((215, y))[channel]) / span, 3)
        for y in range(rows)
    ]
    assert min(coverage[:_STATUS_BAR]) >= 0.97, (theme, coverage)
    steps = [coverage[y] - coverage[y + 1] for y in range(rows - 1)]
    assert min(steps) >= -0.02, (theme, coverage)
    assert max(steps) <= 0.15, (theme, coverage)
    assert coverage[_STATUS_BAR + _BAND + 2] <= 0.02, (theme, coverage)
