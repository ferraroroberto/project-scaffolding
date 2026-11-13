"""The usage log's identified, consent-gated mode for public sites, in all three halves.

The client (`visitorCookie`, `stop()`) and the Cloudflare half (`identify`, `purgeIps`,
`returning`) run under Node through their probes against stubbed browser globals and an
in-memory SQLite standing in for D1; the Python half is checked for the same column and
the same `returning` count. Node is part of the gate's toolchain, so its absence fails here
rather than skipping.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src.no_window import NO_WINDOW
from src.usage_log import UsageLog, parse_batch
from tests.usage_log._summary import summary_of

REPO_ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CLIENT = REPO_ROOT / "app" / "webapp" / "static" / "_vendored" / "usage-log" / "usage-log.js"
WORKER = REPO_ROOT / "src" / "usage_log_worker.js"
ADDRESSES = ("203.0.113.9", "2001:db8::1")


def _run(probe: str, module: Path) -> dict[str, Any]:
    node = shutil.which("node")
    assert node, "node is required to run the usage-log identified-mode tests"
    done = subprocess.run(
        [node, "--no-warnings", str(HERE / probe), str(module)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
        creationflags=NO_WINDOW, check=False,
    )
    assert done.returncode == 0, done.stderr
    result: dict[str, Any] = json.loads(done.stdout)
    return result


@pytest.fixture(scope="module")
def client() -> dict[str, Any]:
    return _run("_usage_log_identified_client_probe.mjs", CLIENT)


@pytest.fixture(scope="module")
def worker() -> dict[str, Any]:
    return _run("_usage_log_identified_probe.mjs", WORKER)


# ------------------------------------------------------------ client


def test_importing_the_client_sends_nothing_and_sets_no_cookie(client: dict[str, Any]) -> None:
    assert client["beforeInit"] == {"sends": 0, "cookie": "", "writes": 0, "listeners": 0}


def test_init_sets_a_first_party_visitor_cookie_for_13_months(client: dict[str, Any]) -> None:
    [write] = client["afterInit"]["writes"]
    assert re.fullmatch(r"uv=[0-9a-f]{32}; Max-Age=34214400; Path=/; SameSite=Lax; Secure", write)
    assert client["bodyCarriesId"] is False


def test_a_later_visit_reuses_the_cookie_without_extending_it(client: dict[str, Any]) -> None:
    assert client["secondInit"]["writes"] == []
    assert client["secondInit"]["value"] == client["afterInit"]["value"]


def test_a_malformed_visitor_id_is_replaced(client: dict[str, Any]) -> None:
    assert client["replaced"] is True


def test_stop_drops_the_queue_detaches_listeners_and_deletes_the_cookie(client: dict[str, Any]) -> None:
    stop = client["stop"]
    assert stop["sends"] == 0
    assert stop["removed"] == ["document:visibilitychange", "root:click", "window:pagehide"]
    assert stop["deleteWrite"][-1] == "uv=; Max-Age=0; Path=/; SameSite=Lax; Secure"
    assert stop["cookie"] == ""


def test_plain_http_omits_secure_and_honours_the_lifetime_option(client: dict[str, Any]) -> None:
    [write] = client["http"]
    assert write.endswith("; Max-Age=2592000; Path=/; SameSite=Lax")


def test_a_bad_cookie_name_disables_the_logger(client: dict[str, Any]) -> None:
    assert client["badName"] == {"cookie": "", "sends": 0, "hasStop": True}


def test_without_visitor_cookie_no_cookie_is_touched(client: dict[str, Any]) -> None:
    assert client["plain"] == {"writes": 0, "cookie": ""}


# ------------------------------------------------------------ Cloudflare half


def test_without_consent_nothing_is_stored_and_no_table_is_touched(worker: dict[str, Any]) -> None:
    no = worker["noConsent"]
    assert no["statuses"] == [200, 200, 200]
    assert no["bodies"] == [{"accepted": 0, "rejected": 2}] * 3
    assert no["tables"] == []
    assert [line["event"] for line in no["logs"]] == ["usage.no_consent"] * 3


def test_with_consent_the_cookie_id_and_address_are_stored(worker: dict[str, Any]) -> None:
    consent = worker["consent"]
    assert consent["body"] == {"accepted": 2, "rejected": 0}
    pairs = [(r["view_id"], r["visitor"], r["ip"]) for r in consent["rows"] if r["kind"] == "view"]
    assert pairs == [
        ("about", "a" * 32, "203.0.113.9"),
        ("home", None, "2001:db8::1"),  # malformed cookie id: no visitor
        ("home", "0123456789abcdef0123456789abcdef", None),  # malformed address: not stored
    ]
    assert {r["country"] for r in consent["rows"]} == {"ES"}
    assert consent["salts"] == 0, "identified mode never creates a daily salt"


def test_a_write_clears_the_address_on_rows_past_the_retention(worker: dict[str, Any]) -> None:
    rows = worker["retention"]["rows"]
    by_day = {(r["ts"][:10], r["kind"]): r for r in rows}
    old = by_day[("2026-10-01", "view")]
    assert old["ip"] is None
    assert (old["country"], old["visitor"], old["view_id"]) == ("ES", "a" * 32, "home")
    assert by_day[("2026-10-31", "view")]["ip"] == "203.0.113.9"
    assert by_day[("2026-11-01", "view")]["ip"] == "203.0.113.9"


def test_purge_ips_is_exported_and_clears_only_older_rows(worker: dict[str, Any]) -> None:
    purge = worker["purge"]
    assert purge["before"] == ["203.0.113.9"] * 4
    assert purge["after"] == [None, None, "203.0.113.9", "203.0.113.9"]
    assert purge["badDays"] == "TypeError"


def test_a_misconfigured_identify_stores_nothing(worker: dict[str, Any]) -> None:
    assert worker["misconfigured"] == {"status": 503, "tables": [], "logs": ["usage.misconfigured"]}


def test_the_summary_counts_returning_visitors(worker: dict[str, Any]) -> None:
    summary = worker["summary"]
    assert summary["visitors"] == 2
    assert summary["returning"] == 1


def test_site_mode_still_stores_no_address_or_cookie(worker: dict[str, Any]) -> None:
    rows = worker["siteMode"]["rows"]
    assert {r["ip"] for r in rows} == {None}
    assert all(re.fullmatch(r"[0-9a-f]{16}", r["visitor"]) for r in rows)
    assert worker["siteSummaryReturning"] == 0


def test_an_older_d1_database_gains_the_ip_column(worker: dict[str, Any]) -> None:
    migrated = worker["migrated"]
    assert migrated["status"] == 200
    assert migrated["columns"][-1] == "ip"
    assert {r["ip"] for r in migrated["rows"]} == {"203.0.113.9"}


# ------------------------------------------------------------ Python half


def _body(events: list[dict[str, str]]) -> bytes:
    return json.dumps({"session_id": "s-aaaaaaaa", "device_class": "phone",
                       "os_class": "ios", "events": events}).encode()


def test_the_python_half_carries_the_ip_column_empty(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite3"
    raw = json.loads(_body([{"kind": "view", "id": "home"}]))
    raw["ip"] = ADDRESSES[0]
    UsageLog(db).record(parse_batch(json.dumps(raw).encode()))
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT ip FROM events").fetchall() == [(None,)]
    finally:
        conn.close()
    assert ADDRESSES[0].encode() not in db.read_bytes()


def test_the_python_summary_counts_returning_visitors_like_the_worker(tmp_path: Path) -> None:
    """An exported D1 file: visitor v1 seen before the window and in it, v2 only in it."""
    db = tmp_path / "usage.sqlite3"
    log = UsageLog(db)
    log.record(parse_batch(_body([{"kind": "view", "id": "home"}])))
    conn = sqlite3.connect(db)
    with conn:
        conn.execute("DELETE FROM events")
        conn.executemany(
            "INSERT INTO events (ts, session_id, kind, view_id, device_class, os_class, country, visitor, ip)"
            " VALUES (strftime('%Y-%m-%dT%H:%M:%SZ','now', ?), 's-aaaaaaaa', 'view', 'home',"
            " 'desktop', 'windows', 'ES', ?, NULL)",
            [("-40 days", "v1"), ("-1 days", "v1"), ("-1 days", "v2"), ("-0 days", "v2")],
        )
    conn.close()
    out = summary_of(log.db_path, 30)
    assert out["visitors"] == 2
    assert out["returning"] == 2  # v2 on two days inside the window, v1 across its start


def test_the_python_summary_reports_zero_returning_for_an_app(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite3"
    log = UsageLog(db)
    log.record(parse_batch(_body([{"kind": "view", "id": "home"}])))
    assert summary_of(log.db_path, 7)["returning"] == 0
