"""The vendored nav starts the installed phone app's content below the safe area.

iOS rasters the page header card soft at cold start when the content begins
right at the safe-area edge of the standalone app, and 20px lower is sharp on
the device. A desktop engine cannot emulate `display-mode: standalone`, so the
guard is structural: the offset has one token with a 20px fallback, it is plain
padding on top of the safe area, it applies in the installed phone app only, and
the rule adds no layer. The README states the contract and the token.
"""

from __future__ import annotations

import re
from pathlib import Path

NAV = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "_vendored" / "nav"

_PADDING = "padding-top: calc(env(safe-area-inset-top, 0px) + var(--standalone-head-offset, 20px));"
_PHONE = "@media (pointer: coarse) and (max-width: 520px) {"


def _css() -> str:
    return (NAV / "nav-tabs.css").read_text(encoding="utf-8")


def _standalone_app_rule() -> str:
    """The `.app { ... }` body inside the phone block's standalone media block."""
    phone = _css().split(_PHONE, 1)[1]
    standalone = re.search(r"\n  @media \(display-mode: standalone\) \{\n(?P<body>.*?)\n  \}\n", phone, re.S)
    assert standalone, "the phone block must carry an @media (display-mode: standalone) block"
    rule = re.search(r"\.app \{(?P<body>[^}]*)\}", standalone.group("body"))
    assert rule, "the phone standalone block must offset .app"
    return rule.group("body")


def test_installed_app_offsets_the_content_with_plain_padding() -> None:
    body = _standalone_app_rule()
    assert _PADDING in body
    for prop in ("transform", "will-change", "filter", "position"):
        assert prop not in body, prop


def test_offset_is_stated_once_and_only_for_the_installed_phone_app() -> None:
    assert _css().count(_PADDING) == 1
    assert _css().count("--standalone-head-offset: ") == 0, "the token is the app's to set, not nav's"


def test_readme_states_the_token_and_the_contract() -> None:
    readme = (NAV / "README.md").read_text(encoding="utf-8")
    assert "| `--standalone-head-offset` | `20px` |" in readme
    assert "The installed app starts its content 20px below the safe area." in readme
