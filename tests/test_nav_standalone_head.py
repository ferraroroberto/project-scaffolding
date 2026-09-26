"""The vendored nav's standalone page-head dependency is shipped and stated (#287).

`nav-tabs.css` anchors the installed-app (standalone) pill at
`top: calc(100lvh - bar - margin)` and sizes `.app` with `100lvh`, which assumes
the web view spans the whole screen. iOS gives an installed app the whole screen
only when the page sets `apple-mobile-web-app-status-bar-style: black-translucent`
plus `viewport-fit=cover`. Without the pair the app starts below an opaque
status bar and the pill lands one status-bar height too low (parking-manager#24).

No desktop engine reproduces that, so the guard is textual: the markup skeleton
an adopter pastes, the CSS it copies and the README contract all name the pair,
and the gallery page that plays the app's head carries it.
"""

from __future__ import annotations

from pathlib import Path

VENDORED = Path(__file__).resolve().parent.parent / "app" / "webapp" / "static" / "_vendored"
NAV = VENDORED / "nav"

_STATUS_BAR_META = (
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">'
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _viewport_metas(html: str) -> list[str]:
    return [line for line in html.splitlines() if '<meta name="viewport"' in line]


def test_skeleton_ships_the_standalone_head() -> None:
    skeleton = _read(NAV / "nav-tabs.html")
    assert _STATUS_BAR_META in skeleton
    viewports = _viewport_metas(skeleton)
    assert viewports and all("viewport-fit=cover" in v for v in viewports), viewports


def test_gallery_head_carries_the_standalone_head() -> None:
    demo = _read(VENDORED / "demo.html")
    head = demo.split("</head>", 1)[0]
    assert _STATUS_BAR_META in head
    viewports = _viewport_metas(head)
    assert len(viewports) == 1 and "viewport-fit=cover" in viewports[0], viewports


def test_css_and_readme_state_the_dependency() -> None:
    for path in (NAV / "nav-tabs.css", NAV / "README.md"):
        text = _read(path)
        for needle in (
            "apple-mobile-web-app-status-bar-style",
            "black-translucent",
            "viewport-fit=cover",
        ):
            assert needle in text, f"{path.name} does not mention {needle}"
