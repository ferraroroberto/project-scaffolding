"""The vendored `runBusy` helper, driven under Node.

`_busy_probe.mjs` loads the real `busy.js` (and its sibling `toast.js`) against a
minimal DOM. The contract pinned here: a second tap while the work is in flight
is ignored and runs nothing, busy is set for the whole run and cleared on
success and on error (sync throw included), the outcome goes to the toast with
the error's own text, and a start toast with no success message is dismissed.
Node is part of the gate's toolchain, so its absence fails here.
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
MODULE = REPO_ROOT / "app" / "webapp" / "static" / "_vendored" / "button" / "busy.js"
PROBE = Path(__file__).resolve().parent / "_busy_probe.mjs"


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to run the busy test"
    done = subprocess.run(
        [node, str(PROBE), str(MODULE)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def test_a_second_tap_in_flight_is_ignored(probe: dict[str, Any]) -> None:
    run = probe["inflight"]
    assert run["calls"] == 1
    assert run["second"] == {"ok": False, "ignored": True}
    assert run["busyWhileRunning"] == "true"
    assert run["startToast"] == {"text": "Refreshing", "hidden": False, "error": False}


def test_busy_clears_and_the_done_toast_shows_on_success(probe: dict[str, Any]) -> None:
    run = probe["inflight"]
    assert run["result"] == {"ok": True, "value": 7}
    assert run["busyAfter"] is None
    assert run["doneToast"] == {"text": "Got 7", "hidden": False, "error": False}


def test_busy_clears_and_the_error_text_shows_on_a_rejection(probe: dict[str, Any]) -> None:
    run = probe["rejected"]
    assert run["ok"] is False
    assert run["busyAfter"] is None
    assert run["toast"] == {"text": "Sync failed: timeout", "hidden": False, "error": True}


def test_a_synchronous_throw_clears_busy_and_a_later_tap_runs(probe: dict[str, Any]) -> None:
    run = probe["sync"]
    assert run["firstOk"] is False
    assert run["busyAfter"] is None
    assert run["again"] is True and run["ran"] == 1
    assert run["toast"] == {"text": "Saved", "hidden": False, "error": False}


def test_a_start_toast_with_no_done_message_is_dismissed(probe: dict[str, Any]) -> None:
    assert probe["dismissed"]["toast"]["hidden"] is True
