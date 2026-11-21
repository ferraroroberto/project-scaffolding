"""The vendored toast's action button, driven under Node.

`_toast_probe.mjs` loads the real `toast.js` against a minimal DOM. The contract pinned
here: a tap runs the action and then hides the toast, but a toast the action showed
itself (an Undo that says "Restored", sync or async) stays up, because the tap only
dismisses the toast it was on. Node is part of the gate's toolchain, so its absence
fails here.
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
MODULE = REPO_ROOT / "app" / "webapp" / "static" / "_vendored" / "toast" / "toast.js"
PROBE = Path(__file__).resolve().parent / "_toast_probe.mjs"


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to run the toast test"
    done = subprocess.run(
        [node, str(PROBE), str(MODULE)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def test_a_tap_runs_the_action_and_hides_its_toast(probe: dict[str, Any]) -> None:
    assert probe["plain"] == {"ran": 1, "hidden": True, "buttons": 1}


@pytest.mark.parametrize("case", ["confirmed", "asyncConfirmed"])
def test_a_toast_the_action_shows_stays_up(probe: dict[str, Any], case: str) -> None:
    assert probe[case] == {"hidden": False, "buttons": 0}


def test_a_failing_action_still_hides_its_toast(probe: dict[str, Any]) -> None:
    assert probe["rejected"] == {"hidden": True, "buttons": 1}
