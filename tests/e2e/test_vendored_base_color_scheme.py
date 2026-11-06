"""`base.css` makes `color-scheme` follow the chosen theme (#608).

Native UI (a `<select>` list, date and time pickers, scrollbars) is drawn from
`color-scheme`. An app that sets `light dark` on `:root` follows the OS, so a
dark app theme on a light OS opened native popups on a light background. The
vendored `base.css` pins `color-scheme` to `data-theme`, and an app's own bare
`:root { color-scheme: light dark }` must not undo that.

Playwright cannot screenshot a native popup, so the proof is the palette the
engine hands native UI: the `Canvas` system colour resolves to the scheme's
background. Run on WebKit as well, the engine of the reported iPhone.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Playwright

_BASE_CSS = (
    Path(__file__).resolve().parents[2] / "app/webapp/static/_vendored/base/base.css"
).read_text(encoding="utf-8")

# An app's own stylesheet, loaded AFTER base, restating the old fallback.
_APP_CSS = ":root { color-scheme: light dark; } body { background: Canvas; }"

_PAGE = """<!doctype html><html{attr}><head><style>{base}</style><style>{app}</style></head>
<body><select id="s"><option>a</option></select><input id="d" type="date"></body></html>"""


def _is_dark(rgb: str) -> bool:
    """Canvas is a different dark grey per engine (Chromium 18, WebKit 30)."""
    return sum(int(c) for c in rgb[rgb.index("(") + 1 : -1].split(",")[:3]) < 255


def _read(playwright: Playwright, engine: str, os_scheme: str, theme: str | None) -> dict[str, str]:
    attr = f' data-theme="{theme}"' if theme else ""
    browser = getattr(playwright, engine).launch()
    try:
        page = browser.new_page(color_scheme=os_scheme)
        page.set_content(_PAGE.format(attr=attr, base=_BASE_CSS, app=_APP_CSS))
        return page.evaluate(
            """() => ({
              scheme: getComputedStyle(document.documentElement).colorScheme,
              canvas: getComputedStyle(document.body).backgroundColor,
            })"""
        )
    finally:
        browser.close()


@pytest.mark.parametrize("engine", ["webkit", "chromium"])
@pytest.mark.parametrize(
    ("os_scheme", "theme", "scheme", "dark"),
    [
        ("light", "dark", "dark", True),  # the reported case
        ("dark", "light", "light", False),
        ("light", None, "light dark", False),  # unset theme: follow the OS
        ("dark", None, "light dark", True),
    ],
)
def test_color_scheme_follows_theme(
    playwright: Playwright, engine: str, os_scheme: str, theme: str | None, scheme: str, dark: bool
) -> None:
    got = _read(playwright, engine, os_scheme, theme)
    assert got["scheme"] == scheme, got
    # The scheme alone decides Canvas, so this is the colour native popups get.
    assert _is_dark(got["canvas"]) is dark, got
