"""The vendored page-foot restart sheet, driven under Node.

`_restart_sheet_probe.mjs` loads the real `restart-sheet.js` against stubbed
browser globals and scripted server answers. The contract pinned here: no
targets or no route leaves the readout untouched; a restart reloads only once
a new process answers and the server recorded `ok`; a failed, vanished,
refused or timed-out restart is said as such and never reloads; a target with
a warning asks twice; every control and the sheet carry constant tracking ids.
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
MODULE = REPO_ROOT / "app" / "webapp" / "static" / "_vendored" / "page-foot" / "restart-sheet.js"
PROBE = Path(__file__).resolve().parent / "_restart_sheet_probe.mjs"


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to run the restart-sheet test"
    done = subprocess.run(
        [node, str(PROBE), str(MODULE)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def test_cadence_is_a_short_poll_inside_a_ninety_second_window(probe: dict[str, Any]) -> None:
    assert probe["constants"] == {"timeout": 90_000, "poll": 1500}


def test_restarted_needs_a_new_process_and_an_ok_record(probe: dict[str, Any]) -> None:
    o = probe["outcomes"]
    assert o["restarted"] == "restarted"
    assert o["waiting"] == o["back_record_running"] == o["no_before_ok"] == "pending"
    assert o["other_run_failed"] == "pending"


def test_unknown_is_never_success(probe: dict[str, Any]) -> None:
    o = probe["outcomes"]
    assert o["failed"] == o["runner_gone"] == "failed"
    assert o["never_back"] == o["same_process_at_timeout"] == "timed-out"
    assert o["back_unrecorded_at_timeout"] == o["ok_but_same_process_at_timeout"] == "unconfirmed"


@pytest.mark.parametrize("case", ["no_targets", "no_route"])
def test_no_restart_offered_leaves_the_readout_plain(probe: dict[str, Any], case: str) -> None:
    assert probe[case] == {"offered": False, "readoutAttrs": {}, "sheets": 0}


def test_readout_becomes_a_tracked_button_opening_a_tracked_sheet(probe: dict[str, Any]) -> None:
    run = probe["restarted"]
    assert run["open"] is True
    assert run["readoutAttrs"]["role"] == "button"
    assert run["readoutAttrs"]["data-track"] == "build.restart-open"
    assert run["readoutClasses"] == ["page-foot-restart"]
    assert run["trackView"] == "build.restart"
    assert run["surface"] == "app.restart-sheet"
    assert run["tracks"] == ["build.restart-close", "build.restart-confirm"]
    assert probe["picker"]["tracks"] == ["build.restart-close", "build.restart-target", "build.restart-confirm"]


def test_a_restart_reloads_on_the_new_build(probe: dict[str, Any]) -> None:
    run = probe["restarted"]
    assert run["posted"] == {"target": "app"}
    assert run["note"] == "Restarted · Build: aaa1111 · 2026-11-21 10:01"
    assert run["reloads"] == 1


def test_a_failed_restart_shows_its_exit_and_log_and_does_not_reload(probe: dict[str, Any]) -> None:
    run = probe["failed"]
    assert (run["note"], run["tone"], run["log"], run["reloads"]) == (
        "Restart failed (exit 1).", "error", "ERROR: reclaim failed", 0)


def test_a_restart_that_never_comes_back_times_out_loudly(probe: dict[str, Any]) -> None:
    run = probe["timed_out"]
    assert run["note"].startswith("The app did not come back in 90 s.")
    assert (run["tone"], run["reloads"], run["elapsed"]) == ("error", 0, 90_000)


@pytest.mark.parametrize(("case", "note"), [
    ("refused", "Not allowed from here: sign in to this app first."),
    ("busy", "A restart is already running."),
])
def test_refusals_are_named(probe: dict[str, Any], case: str, note: str) -> None:
    assert (probe[case]["note"], probe[case]["reloads"]) == (note, 0)


def test_a_warned_target_asks_twice(probe: dict[str, Any]) -> None:
    run = probe["warned_once"]
    assert run["posted"] is None
    assert run["labels"] == ["Restart worker", "Restart anyway"]
    assert (run["note"], run["tone"]) == ("Stops the running jobs.", "warning")


def test_the_warning_is_the_one_true_when_the_sheet_opens(probe: dict[str, Any]) -> None:
    run = probe["warning_follows_live_state"]
    # Read 1 (page load) said 3 sessions; read 2 (the open) said 6.
    assert (run["note"], run["tone"]) == ("This ends 6 live sessions.", "warning")
    assert run["labels"] == ["Restart hub", "Restart anyway"]
    assert run["posted"] is None


def test_confirm_is_held_while_the_open_reads_the_targets(probe: dict[str, Any]) -> None:
    assert probe["warning_follows_live_state"]["lockedWhileReading"] is True


def test_a_failed_reread_keeps_the_warning_the_page_loaded_with(probe: dict[str, Any]) -> None:
    run = probe["warning_kept_when_the_reread_fails"]
    assert (run["note"], run["tone"]) == ("This ends 3 live sessions.", "warning")


def test_the_readouts_hit_area_grows_upward_only_with_webkit_slack() -> None:
    css = (MODULE.parent / "restart-sheet.css").read_text(encoding="utf-8")
    # Top inset only (bottom 0) so a flush footer gains no scroll; 1px covers line-box snapping.
    assert "inset: calc(1.1em - var(--hit-min, 44px) - 1px) 0 0;" in css
