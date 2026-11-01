"""The vendored usage-log client's `track(id)` (#479) and `site` option, driven under Node.

`tests/_usage_log_client_probe.mjs` loads the real `usage-log.js` against
stubbed browser globals; these tests assert on the events it reports sending.
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
CLIENT = REPO_ROOT / "app" / "webapp" / "static" / "_vendored" / "usage-log" / "usage-log.js"
PROBE = Path(__file__).resolve().parent / "_usage_log_client_probe.mjs"


@pytest.fixture(scope="module")
def probe() -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to run the usage-log client test"
    done = subprocess.run(
        [node, str(PROBE), str(CLIENT)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def test_track_queues_one_tap_with_the_current_view(probe: dict[str, Any]) -> None:
    assert probe["tracked"] == [{"kind": "tap", "id": "some.id", "view": "board"}]


def test_track_without_a_view_yet_carries_no_view(probe: dict[str, Any]) -> None:
    assert probe["beforeView"] == [{"kind": "tap", "id": "before.view"}]


def test_track_payload_is_byte_identical_to_a_data_track_click(probe: dict[str, Any]) -> None:
    assert json.dumps(probe["tracked"]) == json.dumps(probe["clicked"])


def test_track_with_an_id_outside_the_pattern_queues_nothing(probe: dict[str, Any]) -> None:
    assert probe["invalid"] == []


def test_track_is_a_silent_no_op_when_the_logger_is_disabled(probe: dict[str, Any]) -> None:
    assert probe["disabledHasTrack"] is True
    assert probe["disabledSends"] == 0


def test_site_mode_records_the_page_and_an_external_referrer_on_load(probe: dict[str, Any]) -> None:
    assert probe["siteLoad"] == [
        {"kind": "session_start"},
        {"kind": "referrer", "id": "linkedin.com"},
        {"kind": "view", "id": "about"},
    ]


def test_site_mode_records_followed_links_and_skips_anchors_and_scripts(probe: dict[str, Any]) -> None:
    assert probe["siteLinks"] == [
        {"kind": "tap", "id": "nav:inspiring-conversations:sara", "view": "about"},
        {"kind": "tap", "id": "out:twitter.com", "view": "about"},
        {"kind": "tap", "id": "mail", "view": "about"},
    ]


def test_site_mode_ignores_a_referrer_on_the_same_host(probe: dict[str, Any]) -> None:
    assert probe["sameHost"] == [{"kind": "session_start"}, {"kind": "view", "id": "about"}]


def test_without_site_mode_nothing_new_is_sent(probe: dict[str, Any]) -> None:
    assert probe["plainEvents"] == [{"kind": "session_start"}]


def test_page_host_and_link_ids_fit_the_id_pattern(probe: dict[str, Any]) -> None:
    ids = probe["ids"]
    assert ids["pages"][:3] == ["home", "about", "a:b-c"]
    assert len(ids["pages"][3]) == 64
    assert ids["hosts"] == ["google.com", None, None]
    assert ids["links"] == [None, "nav:contact", "out:example.org", None]
