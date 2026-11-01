"""The Cloudflare half of the usage log, src/usage_log_worker.js, driven under Node.

`tests/_usage_log_worker_probe.mjs` runs the real module against an in-memory SQLite
standing in for D1 and prints what it stored. Its event validation is compared with
`usage_log.validate_event` on the same cases, so the two halves cannot drift apart. Node
is part of the gate's toolchain, so its absence fails here rather than skipping.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.no_window import NO_WINDOW
from src.usage_log import validate_event

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKER = REPO_ROOT / "src" / "usage_log_worker.js"
PROBE = Path(__file__).resolve().parent / "_usage_log_worker_probe.mjs"

CASES: list[object] = [
    {"kind": "session_start"},
    {"kind": "session_end", "id": "stray"},
    {"kind": "view", "id": "board"},
    {"kind": "view"},
    {"kind": "view", "id": "a/b"},
    {"kind": "tap", "id": "refresh", "view": "board"},
    {"kind": "tap", "id": "refresh", "view": "has space"},
    {"kind": "tap"},
    {"kind": "referrer", "id": "linkedin.com"},
    {"kind": "referrer", "id": "https://x.example/a"},
    {"kind": "referrer"},
    {"kind": "unknown", "id": "x"},
    {"kind": "tap", "id": "x" * 65},
    {"kind": 42},
    "not an object",
    [],
    None,
]


@pytest.fixture(scope="module")
def probe(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to run the usage-log worker test"
    cases = tmp_path_factory.mktemp("worker") / "cases.json"
    cases.write_text(json.dumps(CASES), encoding="utf-8")
    done = subprocess.run(
        [node, "--no-warnings", str(PROBE), str(WORKER), str(cases)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


def test_event_validation_matches_the_python_half(probe: dict[str, Any]) -> None:
    for raw, js in zip(CASES, probe["validated"], strict=True):
        event = validate_event(raw)
        expected = None if event is None else [event.kind, event.view_id, event.control_id]
        assert js == expected, raw


def test_a_batch_is_stored_with_country_and_visitor_and_nothing_else(probe: dict[str, Any]) -> None:
    assert probe["firstBody"] == {"accepted": 4, "rejected": 1}
    first = [r for r in probe["rows"] if r["ts"].startswith("2026-11-01T10")][:4]
    assert [(r["kind"], r["view_id"], r["control_id"]) for r in first] == [
        ("session_start", None, None),
        ("referrer", None, "linkedin.com"),
        ("view", "about", None),
        ("tap", "about", "out:twitter.com"),
    ]
    assert {r["country"] for r in first} == {"ES"}
    stored = json.dumps(probe["rows"])
    for secret in ("203.0.113.9", "198.51.100.7", "Probe/1.0", "secret"):
        assert secret not in stored


def test_the_visitor_hash_is_stable_within_a_day_and_changes_the_next(probe: dict[str, Any]) -> None:
    by_day: dict[str, set[str]] = {}
    for row in probe["rows"]:
        by_day.setdefault(row["ts"][:10], set()).add(row["visitor"])
    assert len(by_day["2026-11-01"]) == 2  # two addresses, one hash each
    same_visitor_day2 = by_day["2026-11-02"]
    assert len(same_visitor_day2) == 1
    assert not same_visitor_day2 & by_day["2026-11-01"]


def test_only_todays_salt_is_kept(probe: dict[str, Any]) -> None:
    assert probe["salts"] == ["2026-11-02"]


def test_bad_requests_are_refused(probe: dict[str, Any]) -> None:
    assert probe["statuses"] == [200, 200, 200, 200, 400, 405]


def test_the_summary_has_the_python_keys_plus_the_site_counts(probe: dict[str, Any]) -> None:
    summary = probe["summary"]
    assert set(summary) == {"days", "since", "events", "sessions", "first_ts", "last_ts", "views",
                            "controls", "devices", "os", "referrers", "countries", "visitors"}
    assert summary["views"] == {"home": 3, "about": 1}
    assert summary["referrers"] == {"linkedin.com": 1}
    assert summary["countries"] == {"ES": 1, "IT": 1}
    assert summary["visitors"] == 3
