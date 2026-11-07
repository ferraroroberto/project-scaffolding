"""The `site-header` brand and nav breakpoint.

The module runs under Node through its probe against stubbed browser globals. Node is part of
the gate's toolchain, so its absence fails here rather than skipping. The cascade itself (which
nav shows at which width) is browser behaviour the stylesheet assertions below only pin.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPONENT = REPO_ROOT / "app" / "site" / "static" / "_vendored" / "site-header"
TOKENS = REPO_ROOT / "app" / "site" / "static" / "_vendored" / "site-tokens" / "site-tokens.css"
PROBE = Path(__file__).resolve().parent / "_site_header_probe.mjs"


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to run the site-header tests"
    done = subprocess.run(
        [node, "--no-warnings", str(PROBE), str(COMPONENT / "site-header.js")],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def test_a_site_that_sets_nothing_keeps_the_1024_breakpoint(probe: dict[str, Any]) -> None:
    assert probe["defaultWide"] == {"min": [1024], "nav": "inline"}
    assert probe["defaultPhone"] == {"min": [1024], "nav": "menu"}


def test_a_site_raises_the_breakpoint_with_the_token(probe: dict[str, Any]) -> None:
    assert probe["raised"] == {"min": [1200], "nav": "menu"}
    assert probe["raisedWide"] == {"min": [1200], "nav": "inline"}


def test_a_value_the_stylesheet_cannot_honour_falls_back_to_1024(probe: dict[str, Any]) -> None:
    """Below the floor the stylesheet's own 1024px query shows the nav anyway; a non-px length is unreadable."""
    for case in ("belowFloor", "notPx", "junk"):
        assert probe[case]["min"] == [1024], case


def test_crossing_the_breakpoint_flips_the_mode_and_closes_an_open_menu(probe: dict[str, Any]) -> None:
    assert probe["grow"] == {"nav": "inline", "open": False, "expanded": "false"}
    assert probe["shrink"] == {"nav": "menu", "open": False}
    assert probe["betweenStaysOpen"] == {"nav": "menu", "open": True}


def test_the_logo_never_shrinks_beside_a_long_nav() -> None:
    css = (COMPONENT / "site-header.css").read_text(encoding="utf-8")
    assert re.search(r"\.logo\s*\{\s*flex:\s*none;\s*\}", css)
    assert re.search(r"\.logo img\s*\{[^}]*width:\s*auto", css)


def test_the_menu_mode_rules_sit_after_and_below_the_open_panel() -> None:
    """:where() keeps them at the specificity of the desktop rules they undo, so `.menu-open .site-nav` still wins."""
    css = (COMPONENT / "site-header.css").read_text(encoding="utf-8")
    desktop = css.index("@media (min-width: 1024px) {\n  .logo img")
    menu = css.index(':where(.site-header[data-nav="menu"]) .site-nav {')
    assert menu > desktop
    assert not re.search(r'(?<!:where\()\.site-header\[data-nav="menu"\]', css)


def test_the_token_ships_a_1024px_default_the_site_can_override() -> None:
    assert re.search(r"--nav-breakpoint:\s*1024px;", TOKENS.read_text(encoding="utf-8"))
