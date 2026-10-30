"""The vendored nav's standalone page-head dependency is shipped and stated.

The installed-app (standalone) pill is a plain bottom-anchored fixed bar that is
in place from the first frame of a cold launch only when the page sets
`apple-mobile-web-app-status-bar-style: default` (the status bar is then painted
in the page colour by `theme-color`) plus `viewport-fit=cover`. With
`black-translucent` the installed app grows its viewport after launch and the
bar rides that growth.

No desktop engine reproduces that, so the guard is textual: the markup skeleton
an adopter pastes, the CSS it copies and the README contract all name the pair,
and the gallery page that plays the app's head carries it.
"""

from __future__ import annotations

from pathlib import Path

VENDORED = Path(__file__).resolve().parent.parent / "app" / "webapp" / "static" / "_vendored"
NAV = VENDORED / "nav"

_STATUS_BAR_META = '<meta name="apple-mobile-web-app-status-bar-style" content="default">'
_WRONG_STATUS_BAR_META = (
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _viewport_metas(html: str) -> list[str]:
    return [line for line in html.splitlines() if '<meta name="viewport"' in line]


def test_skeleton_ships_the_standalone_head() -> None:
    skeleton = _read(NAV / "nav-tabs.html")
    assert _STATUS_BAR_META in skeleton
    assert _WRONG_STATUS_BAR_META not in skeleton
    viewports = _viewport_metas(skeleton)
    assert viewports and all("viewport-fit=cover" in v for v in viewports), viewports


def test_gallery_head_carries_the_standalone_head() -> None:
    demo = _read(VENDORED / "demo.html")
    head = demo.split("</head>", 1)[0]
    assert _STATUS_BAR_META in head
    assert _WRONG_STATUS_BAR_META not in head
    viewports = _viewport_metas(head)
    assert len(viewports) == 1 and "viewport-fit=cover" in viewports[0], viewports


def test_css_and_readme_state_the_dependency() -> None:
    css = _read(NAV / "nav-tabs.css")
    assert "`default` status-bar" in css

    readme = _read(NAV / "README.md")
    for needle in (
        "apple-mobile-web-app-status-bar-style",
        'content="default"',
        "viewport-fit=cover",
        "scroll-lock.js",
    ):
        assert needle in readme, f"README.md does not mention {needle}"
    assert _WRONG_STATUS_BAR_META not in readme
