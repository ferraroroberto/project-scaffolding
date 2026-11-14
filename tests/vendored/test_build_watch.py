"""The vendored build-watch module's decisions, driven under Node.

`_build_watch_probe.mjs` loads the real `build-watch.js` against stubbed
browser globals and prints what it decided. The contract pinned here: a prompt
only when the boot stamp and the live `asset_hash` are both known and differ,
never a reload without the user's tap, a dismissal that holds until the server
moves again, and unknown (401, empty hash, failed read) never read as stale.
Node is part of the gate's toolchain, so its absence fails here rather than
skipping.
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
MODULE = REPO_ROOT / "app" / "webapp" / "static" / "_vendored" / "build-watch" / "build-watch.js"
PROBE = Path(__file__).resolve().parent / "_build_watch_probe.mjs"


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to run the build-watch test"
    done = subprocess.run(
        [node, str(PROBE), str(MODULE)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def test_cadence_is_a_minute_throttle_and_a_five_minute_poll(probe: dict[str, Any]) -> None:
    assert probe["constants"] == {"throttle": 60_000, "interval": 300_000}


def test_stale_only_when_both_hashes_are_known_and_differ(probe: dict[str, Any]) -> None:
    assert probe["verdict"]["stale"] == "stale"
    assert probe["verdict"]["current"] == "current"
    assert set(probe["verdict"]["unknown"]) == {"unknown"}


def test_throttle_reads_first_then_waits_out_the_window(probe: dict[str, Any]) -> None:
    assert probe["shouldCheck"] == [True, True, False, True, False]


def test_stamp_is_read_from_the_v_query_and_unknown_otherwise(probe: dict[str, Any]) -> None:
    assert probe["stampOf"] == ["abc123", "abc123", None, None, None, None]


def test_a_page_with_no_stamped_asset_never_starts(probe: dict[str, Any]) -> None:
    assert probe["noStamp"] == {"started": False, "reads": 0}


def test_boot_stamp_falls_back_to_the_pages_stamped_assets(probe: dict[str, Any]) -> None:
    assert probe["started"] is True
    assert probe["intervalMs"] == [300_000]


def test_a_newer_live_build_shows_the_prompt_on_the_toast_glass(probe: dict[str, Any]) -> None:
    stale = probe["stale"]
    assert stale["shown"] is True
    assert stale["className"] == "toast build-prompt"
    assert (stale["role"], stale["live"]) == ("status", "polite")
    assert stale["texts"][:2] == ["New version available", "Reload"]
    assert stale["tracks"] == [None, "build.reload", "build.dismiss"]
    assert stale["read"]["url"] == "/api/version"
    assert stale["read"]["init"]["cache"] == "no-store"


def test_a_visibility_flick_inside_the_throttle_does_not_reread(probe: dict[str, Any]) -> None:
    assert probe["throttled"] is True


def test_dismiss_holds_until_the_server_moves_again(probe: dict[str, Any]) -> None:
    assert probe["dismissedHidden"] is True
    assert probe["dismissStaysDown"] is True
    assert probe["newBuildReshows"] is True


def test_only_the_users_tap_reloads(probe: dict[str, Any]) -> None:
    assert (probe["reloadsBeforeTap"], probe["reloadsAfterTap"]) == (0, 1)


def test_back_on_the_boot_build_hides_the_prompt(probe: dict[str, Any]) -> None:
    assert probe["currentHides"] is True


@pytest.mark.parametrize("case", ["unauthorized", "emptyHash", "noField", "network"])
def test_unknown_is_never_stale(probe: dict[str, Any], case: str) -> None:
    assert probe[case] is True


def test_a_callers_own_reader_replaces_fetch(probe: dict[str, Any]) -> None:
    assert probe["ownReader"] == {"started": True, "urls": ["/x/version"], "fetchCalls": 0}
