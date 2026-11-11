"""The vendored nav's top glass emits the owner-validated translucent top bar.

nav-lab's exporter turns the validated recipe (`black-translucent`,
`viewport-fit=auto`, env inset, status-header region with no header row,
layer target, blur 20px, saturate 180%, page tint at 50%, 16px masked fade,
promoted layer, no hairline, revealed on scroll, content offset 0) into one
fixed layer from the viewport top through the safe area plus the fade, and
content padding of the safe area alone. A desktop engine cannot emulate the
installed app, so the guard is structural: the phone block's `body::after`
carries exactly those declarations, and the fixed standalone offset it
replaced is gone from the CSS and the README.
"""

from __future__ import annotations

import re
from pathlib import Path

NAV = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "_vendored" / "nav"

_PHONE = "@media (pointer: coarse) and (max-width: 520px) {"
_MASK = "linear-gradient(to bottom, #000 calc(100% - var(--nav-fade-band, 16px)), transparent 100%)"
_RECIPE = (
    "position: fixed;",
    "top: 0;",
    "left: 0;",
    "right: 0;",
    "height: calc(env(safe-area-inset-top, 0px) + var(--nav-fade-band, 16px));",
    "pointer-events: none;",
    "opacity: var(--nav-fade-on, 0);",
    "background: color-mix(in srgb, var(--bg) 50%, transparent);",
    "-webkit-backdrop-filter: blur(20px) saturate(180%);",
    "backdrop-filter: blur(20px) saturate(180%);",
    f"-webkit-mask-image: {_MASK};",
    f"mask-image: {_MASK};",
    "transform: translateZ(0);",
    "will-change: transform;",
)


def _css() -> str:
    return (NAV / "nav-tabs.css").read_text(encoding="utf-8")


def _phone_rule(selector: str) -> str:
    phone = _css().split(_PHONE, 1)[1]
    rule = re.search(r"\n  " + re.escape(selector) + r" \{(?P<body>[^}]*)\}", phone)
    assert rule, f"the phone block must carry a {selector} rule"
    return rule.group("body")


def test_top_glass_emits_the_recipe() -> None:
    body = _phone_rule("body::after")
    declarations = [line.strip() for line in body.strip().splitlines()]
    for declaration in _RECIPE:
        assert declaration in declarations, declaration
    assert not any(d.startswith("background: linear-gradient") for d in declarations), declarations


def test_reveal_distance_matches_the_fade_length() -> None:
    js = (NAV / "nav-tabs.js").read_text(encoding="utf-8")
    assert "getPropertyValue('--nav-fade-band')) || 16;" in js


def test_content_starts_at_the_safe_area_with_no_fixed_offset() -> None:
    assert "padding: env(safe-area-inset-top, 0px) var(--gap) var(--nav-bottom-reserve);" in _phone_rule(".app")
    css = _css()
    assert "--standalone-head-offset" not in css
    standalone = css.split(_PHONE, 1)[1].split("@media (display-mode: standalone) {", 1)[1]
    standalone = standalone.split("\n  }\n", 1)[0]
    assert ".app {" not in standalone, "the installed app adds no top offset of its own"


def test_readme_states_the_recipe_and_drops_the_offset() -> None:
    readme = (NAV / "README.md").read_text(encoding="utf-8")
    assert "--standalone-head-offset" not in readme
    assert "| `--nav-fade-band` | `16px` |" in readme
    assert "Every standalone surface follows the same top rule." in readme


def test_top_glass_is_not_generated_at_rest() -> None:
    """An installed iOS app paints a promoted backdrop-filter layer even at
    opacity 0, frosting the header at scroll-top, so the layer only exists
    once nav-tabs.js marks the page as scrolled."""
    declarations = [line.strip() for line in _phone_rule("body::after").strip().splitlines()]
    assert "content: none;" in declarations, declarations
    assert "content: '';" in _phone_rule("html[data-nav-top-glass] body::after")
    js = (NAV / "nav-tabs.js").read_text(encoding="utf-8")
    assert "root.toggleAttribute('data-nav-top-glass', reveal > 0);" in js
