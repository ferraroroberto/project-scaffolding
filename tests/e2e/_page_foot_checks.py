"""Checks for the page-foot restart readout's hit area.

The readout's touch target is a `::after` that must reach the fleet minimum
without ever extending the document: an app whose footer sits flush at the
window bottom (`margin-block-end: 0`, no scroll) must not gain page scroll.
`test_vendored_components.py` runs the case in a fresh browser context.
"""

from __future__ import annotations

from playwright.sync_api import Page

from tests.e2e._geometry import effective_rect

_VENDORED = "/_vendored"
_FLUSH_PAGE = """<!doctype html>
<html><head>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="{base}/page-foot/page-foot.css">
<link rel="stylesheet" href="{base}/page-foot/restart-sheet.css">
<style>
  html, body {{ margin: 0; }}
  .app {{ display: flex; flex-direction: column; min-height: 100vh; }}
  .app > main {{ flex: 1; }}
  .page-foot {{ margin-block-end: 0; }}
</style></head>
<body><div class="app">
<main>Content</main>
<footer class="page-foot"><p class="page-foot-restart" id="readout">Build: abc1234</p></footer>
</div></body></html>"""


def check_flush_footer_hit_area_adds_no_page_scroll(page: Page, static_server: str) -> None:
    """A footer flush at the window bottom keeps the page unscrollable, target still 44px."""
    page.set_content(_FLUSH_PAGE.format(base=f"{static_server}{_VENDORED}"))
    page.wait_for_function("document.fonts.status === 'loaded'")
    page.wait_for_function(
        "getComputedStyle(document.querySelector('.page-foot-restart'), '::after').position === 'absolute'"
    )
    scroll = page.evaluate(
        "({ doc: document.documentElement.scrollHeight, view: window.innerHeight })"
    )
    assert scroll["doc"] <= scroll["view"], f"the hit area added page scroll: {scroll}"
    rect = effective_rect(page.locator("#readout")).effective
    assert rect.height >= 44, f"the readout's tap target shrank to {rect.height}px"
    assert rect.bottom <= scroll["view"], "the hit area extends below the window"
