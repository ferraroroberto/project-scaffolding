"""The vendored full-screen setting's Edge detection and stored choice, driven under Node.

`_fullscreen_probe.mjs` loads the real `fullscreen.js`. The row is meant for Edge only:
desktop Edge (`Edg/`) and Edge on Android (`EdgA/`) show it, every other browser,
Chrome and iOS Edge (`EdgiOS/`) included, does not. The stored choice is off unless it
is exactly `1`, and an unreadable store reads as off. Node is part of the gate's
toolchain, so its absence fails here.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE = REPO_ROOT / "app" / "webapp" / "static" / "_vendored" / "fullscreen" / "fullscreen.js"
PROBE = Path(__file__).resolve().parent / "_fullscreen_probe.mjs"

_CHROME = "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0"
AGENTS = {
    "desktop_edge": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) {_CHROME} Safari/537.36 Edg/130.0.0.0",
    "android_edge": f"Mozilla/5.0 (Linux; Android 14; Pixel 8) {_CHROME} Mobile Safari/537.36 EdgA/130.0.0.0",
    "desktop_chrome": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) {_CHROME} Safari/537.36",
    "android_chrome": f"Mozilla/5.0 (Linux; Android 14; Pixel 8) {_CHROME} Mobile Safari/537.36",
    "firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:131.0) Gecko/20100101 Firefox/131.0",
    "ios_safari": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
    "ios_edge": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/18.0 EdgiOS/130.0.0.0 Mobile/15E148 Safari/605.1.15",
    "empty": "",
}


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to run the fullscreen detection test"
    done = subprocess.run(
        [node, str(PROBE), str(MODULE), json.dumps(AGENTS)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


@pytest.mark.parametrize("name", ["desktop_edge", "android_edge"])
def test_edge_user_agents_are_detected(probe: dict[str, Any], name: str) -> None:
    assert probe["agents"][name] is True


@pytest.mark.parametrize(
    "name", ["desktop_chrome", "android_chrome", "firefox", "ios_safari", "ios_edge", "empty"]
)
def test_other_browsers_are_not_edge(probe: dict[str, Any], name: str) -> None:
    assert probe["agents"][name] is False


def test_the_stored_choice_is_on_only_for_one_and_per_app(probe: dict[str, Any]) -> None:
    assert probe["stored"] == {
        "unset": False, "on": True, "otherApp": False, "zero": False, "blocked": False,
    }
