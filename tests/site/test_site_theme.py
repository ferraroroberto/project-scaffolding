"""The `site-theme` switch: system default, saved choice, and no first-paint flash.

The boot line and the module run under Node through their probe against stubbed browser
globals (a storage, a media query, one button, `<html>`). Node is part of the gate's
toolchain, so its absence fails here rather than skipping.
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
COMPONENT = REPO_ROOT / "app" / "site" / "static" / "_vendored" / "site-theme"
BOOT = COMPONENT / "theme-boot.js"
MODULE = COMPONENT / "site-theme.js"
PROBE = Path(__file__).resolve().parent / "_site_theme_probe.mjs"


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to run the site-theme tests"
    done = subprocess.run(
        [node, "--no-warnings", str(PROBE), str(BOOT), str(MODULE)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def _code(path: Path) -> str:
    """The file without its comment header: what the browser executes."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.startswith("//")).strip()


def test_the_system_setting_is_the_default_and_nothing_is_stored(probe: dict[str, Any]) -> None:
    assert probe["systemDark"] == {"pressed": "true", "theme": None, "writes": 0}
    assert probe["systemLight"] == {"pressed": "false", "theme": None, "writes": 0}
    assert probe["systemChange"] == {"pressed": "true", "theme": None}


def test_a_press_switches_saves_and_flips_back(probe: dict[str, Any]) -> None:
    assert probe["press"] == {"theme": "dark", "pressed": "true", "writes": [["theme", "dark"]]}
    assert probe["pressAgain"] == {"theme": "light", "pressed": "false", "writes": [["theme", "dark"], ["theme", "light"]]}
    assert probe["pressOnDarkSystem"] == {"theme": "light", "pressed": "false", "writes": [["theme", "light"]]}


def test_a_saved_choice_beats_the_system_and_a_system_change_does_not_move_it(probe: dict[str, Any]) -> None:
    assert probe["savedLight"] == {"pressed": "false", "theme": "light", "writes": 0}
    assert probe["savedLightStays"] == {"pressed": "false", "theme": "light"}


def test_blocked_storage_still_switches_this_page(probe: dict[str, Any]) -> None:
    assert probe["blockedPress"] == {"theme": "dark", "pressed": "true"}


def test_without_a_switch_in_the_markup_nothing_happens(probe: dict[str, Any]) -> None:
    assert probe["noButton"] == {"theme": None, "writes": 0}


def test_the_boot_line_applies_a_saved_choice_and_ignores_anything_else(probe: dict[str, Any]) -> None:
    boot = probe["boot"]
    assert boot["dark"] == {"theme": "dark", "threw": False}
    assert boot["light"] == {"theme": "light", "threw": False}
    assert boot["none"] == {"theme": None, "threw": False}
    assert boot["junk"] == {"theme": None, "threw": False}
    assert boot["blocked"] == {"theme": None, "threw": False}


def test_the_boot_line_runs_before_first_paint_as_a_plain_script() -> None:
    """A deferred or module script runs after the first paint, which is the flash this avoids."""
    code = _code(BOOT)
    assert "\n" not in code, "the boot is one line, so it can be pasted inline byte for byte"
    assert not re.search(r"\b(import|export|await|addEventListener|DOMContentLoaded|requestAnimationFrame|setTimeout)\b", code)
    # The boot touches only <html> and storage, so it can run in <head> before <body> exists.
    assert "querySelector" not in code and "document.body" not in code


def test_the_module_never_sets_the_theme_at_load_only_on_a_press() -> None:
    """Set at load, a stale module would repaint the page a second time."""
    assignments = re.findall(r"themeRoot\.dataset\.theme\s*=", _code(MODULE))
    assert len(assignments) == 1
    assert _code(MODULE).index("themeRoot.dataset.theme =") > _code(MODULE).index("addEventListener('click'")


def test_the_readme_pastes_the_same_boot_line_the_file_holds() -> None:
    readme = (COMPONENT / "README.md").read_text(encoding="utf-8")
    assert "theme-boot.js" in readme and "paste its one code line inline" in readme
    assert 'localStorage.getItem("theme")' in _code(BOOT)
    assert _code(BOOT) == (
        'try{var t=localStorage.getItem("theme");if(t==="light"||t==="dark")'
        "document.documentElement.dataset.theme=t}catch(e){}"
    )


def test_the_system_default_and_the_choice_are_pure_css_so_no_script_is_needed() -> None:
    css = (COMPONENT / "site-theme.css").read_text(encoding="utf-8")
    assert re.search(r":root\s*\{[^}]*color-scheme:\s*light dark", css)
    assert re.search(r':root\[data-theme="light"\]\s*\{[^}]*color-scheme:\s*light', css)
    assert re.search(r':root\[data-theme="dark"\]\s*\{[^}]*color-scheme:\s*dark', css)
    assert "@media (prefers-color-scheme: dark)" in css and ':root:not([data-theme="light"])' in css
    assert "transition" not in css, "a colour transition would show the wrong theme for a moment"


def test_the_icons_are_static_lucide_svgs_with_their_licence() -> None:
    readme = (COMPONENT / "README.md").read_text(encoding="utf-8")
    licence = (COMPONENT / "LICENSE-lucide.txt").read_text(encoding="utf-8")
    assert "ISC License" in licence and "Lucide" in licence
    assert 'M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z' in readme, "the Lucide moon"
    assert '<circle cx="12" cy="12" r="4"/>' in readme, "the Lucide sun"
    assert "stroke=\"currentColor\"" in readme, "icons follow the text colour in both themes"
