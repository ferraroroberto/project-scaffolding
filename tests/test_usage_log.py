"""Unit tests for the usage-log convention (#349): validation, retention,
privacy, the FastAPI router, and the summary CLI.

The privacy contract is asserted here rather than trusted to the client: the
server drops anything outside the allowlists, stores no field it was not
designed to store, and the shipped client files name no host at all.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts import usage_summary
from src.usage_log import (
    MAX_BODY_BYTES,
    MAX_EVENTS_PER_BATCH,
    Batch,
    Event,
    PayloadError,
    UsageLog,
    format_ts,
    parse_batch,
    usage_router,
    validate_event,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CLIENT_DIR = REPO_ROOT / "app" / "webapp" / "static" / "_vendored" / "usage-log"
SESSION = "3f2b8c1e-0d4a-4b6f-9c2e-1a2b3c4d5e6f"
NOW = datetime(2026, 10, 12, 12, 0, 0, tzinfo=UTC)


def _body(events: list[object], **envelope: object) -> bytes:
    payload: dict[str, object] = {
        "session_id": SESSION, "device_class": "phone", "os_class": "ios", "events": events,
    }
    payload.update(envelope)
    return json.dumps(payload).encode()


def _rows(db: Path) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute(
            "SELECT kind, view_id, control_id, device_class, os_class FROM events ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


# ------------------------------------------------------------ event rules

def test_valid_events_are_kept() -> None:
    assert validate_event({"kind": "view", "id": "board"}) == Event("view", "board", None)
    assert validate_event({"kind": "tap", "id": "job:cancel", "view": "board"}) == Event(
        "tap", "board", "job:cancel")
    assert validate_event({"kind": "session_start"}) == Event("session_start", None, None)


@pytest.mark.parametrize("kind", ["click", "keystroke", "VIEW", "", None, 3])
def test_kind_outside_allowlist_is_rejected(kind: object) -> None:
    assert validate_event({"kind": kind, "id": "board"}) is None


@pytest.mark.parametrize(
    "bad_id",
    [
        "Quarterly report.docx",          # a file name with a space
        "https://example.invalid/x?q=1",  # a URL with a query string
        "notes/2026",                     # a path
        "a" * 65,                         # over the bound
        "-leading-dash",                  # must start alphanumeric
        "",
        None,
        42,
    ],
)
def test_view_id_outside_pattern_is_rejected(bad_id: object) -> None:
    assert validate_event({"kind": "view", "id": bad_id}) is None


@pytest.mark.parametrize("bad_id", ["Send message", "search?q=milk", "a" * 65, None])
def test_control_id_outside_pattern_is_rejected(bad_id: object) -> None:
    assert validate_event({"kind": "tap", "id": bad_id, "view": "board"}) is None


def test_tap_with_bad_context_view_is_rejected() -> None:
    assert validate_event({"kind": "tap", "id": "refresh", "view": "my secret doc"}) is None


def test_non_object_event_is_rejected() -> None:
    assert validate_event(["view", "board"]) is None


# ------------------------------------------------------------ envelope rules

@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (b"not json", "not JSON"),
        (b"[]", "not a JSON object"),
        (_body([], session_id="short"), "bad session_id"),
        (_body([], session_id="has space in it"), "bad session_id"),
        (_body([], device_class="Mozilla/5.0 (iPhone)"), "bad device_class"),
        (_body([], device_class=["phone"]), "bad device_class"),
        (_body([], os_class="macos"), "bad os_class"),
        (_body("view"), "bad events list"),
        (_body([{"kind": "session_start"}] * (MAX_EVENTS_PER_BATCH + 1)), "bad events list"),
        (b" " * (MAX_BODY_BYTES + 1), "too large"),
    ],
)
def test_bad_envelope_raises(body: bytes, reason: str) -> None:
    with pytest.raises(PayloadError, match=reason):
        parse_batch(body)


def test_batch_counts_rejected_events() -> None:
    batch = parse_batch(_body([
        {"kind": "view", "id": "board"},
        {"kind": "scroll", "id": "board"},
        {"kind": "tap", "id": "Typed search text"},
    ]))
    assert batch.events == [Event("view", "board", None)]
    assert batch.rejected == 2


def test_unknown_keys_are_never_stored(tmp_path: Path) -> None:
    """A client that sends more than the schema still only lands the schema."""
    db = tmp_path / "usage.sqlite3"
    secret = "Dear-Alice-the-launch-code-is-1234"
    batch = parse_batch(_body(
        [{"kind": "tap", "id": "send", "view": "chat", "text": secret, "value": secret}],
        user_agent=secret, ip=secret, url=secret,
    ))
    UsageLog(db).record(batch)
    conn = sqlite3.connect(db)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(events)")]
    finally:
        conn.close()
    assert columns == ["id", "ts", "session_id", "kind", "view_id", "control_id",
                       "device_class", "os_class"]
    assert _rows(db) == [("tap", "chat", "send", "phone", "ios")]
    for f in tmp_path.iterdir():
        assert secret.encode() not in f.read_bytes(), f.name


# ------------------------------------------------------------ retention

def test_rows_past_age_and_row_caps_are_pruned(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite3"
    log = UsageLog(db, max_age_days=365, max_rows=5)
    old = format_ts(NOW - timedelta(days=400))
    log.insert_rows([(old, SESSION, "view", "ancient", None, "desktop", "windows")] * 3, now=NOW)
    assert _rows(db) == [], "rows older than the age cap must be pruned on insert"

    fresh = format_ts(NOW - timedelta(days=1))
    log.insert_rows(
        [(fresh, SESSION, "view", f"v{i}", None, "desktop", "windows") for i in range(8)],
        now=NOW,
    )
    kept = [row[1] for row in _rows(db)]
    assert kept == ["v3", "v4", "v5", "v6", "v7"], "oldest rows beyond the row cap are pruned"


# ------------------------------------------------------------ summary

def test_summary_counts_views_taps_and_device_split(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.sqlite3")
    phone = Batch(SESSION, "phone", "ios", [
        Event("session_start", None, None), Event("view", "board", None),
        Event("tap", "board", "refresh"), Event("tap", "board", "refresh"),
        Event("view", "settings", None),
    ])
    desk = Batch("aaaaaaaa-desk", "desktop", "windows", [
        Event("view", "board", None), Event("tap", "board", "cancel"),
    ])
    log.record(phone, now=NOW)
    log.record(desk, now=NOW)
    out = log.summary(30, now=NOW)
    assert out["sessions"] == 2
    assert out["events"] == 7
    assert out["views"] == {"board": 2, "settings": 1}
    assert out["controls"] == {"refresh": 2, "cancel": 1}
    assert out["devices"] == {"desktop": 1, "phone": 1}
    assert out["os"] == {"ios": 1, "windows": 1}
    assert out["first_ts"] == out["last_ts"] == "2026-10-12T12:00:00Z"
    assert SESSION not in json.dumps(out), "session ids are counted, never returned"


def test_summary_window_excludes_older_rows(tmp_path: Path) -> None:
    log = UsageLog(tmp_path / "usage.sqlite3")
    log.insert_rows([(format_ts(NOW - timedelta(days=40)), SESSION, "view", "old", None,
                      "phone", "ios")], now=NOW)
    out = log.summary(30, now=NOW)
    assert out["events"] == 0 and out["views"] == {}


# ------------------------------------------------------------ router

def _client(db: Path) -> TestClient:
    app = FastAPI()
    app.include_router(usage_router(db))
    return TestClient(app)


def test_router_round_trip(tmp_path: Path) -> None:
    client = _client(tmp_path / "usage.sqlite3")
    r = client.post("/api/usage/events", content=_body([
        {"kind": "view", "id": "board"},
        {"kind": "tap", "id": "refresh", "view": "board"},
        {"kind": "paste", "id": "board"},
    ]))
    assert r.status_code == 200
    assert r.json() == {"accepted": 2, "rejected": 1}
    summary = client.get("/api/usage/summary", params={"days": 7}).json()
    assert summary["views"] == {"board": 1}
    assert summary["controls"] == {"refresh": 1}


def test_router_rejects_bad_envelope_and_oversize(tmp_path: Path) -> None:
    client = _client(tmp_path / "usage.sqlite3")
    assert client.post("/api/usage/events", content=b"nope").status_code == 400
    big = b"x" * (MAX_BODY_BYTES + 1)
    assert client.post("/api/usage/events", content=big).status_code == 413


def test_router_drops_batch_on_unwritable_db_with_one_info_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    unwritable = tmp_path / "is-a-directory"
    unwritable.mkdir()
    client = _client(unwritable)
    with caplog.at_level(logging.INFO, logger="src.usage_log"):
        r = client.post("/api/usage/events", content=_body([{"kind": "view", "id": "board"}]))
    assert r.status_code == 503
    lines = [rec for rec in caplog.records if rec.name == "src.usage_log"]
    assert len(lines) == 1 and lines[0].levelno == logging.INFO
    assert "dropped 1 event" in lines[0].getMessage()


def test_router_applies_the_apps_dependencies(tmp_path: Path) -> None:
    from fastapi import Depends, HTTPException

    def deny() -> None:
        raise HTTPException(status_code=401)

    app = FastAPI()
    app.include_router(usage_router(tmp_path / "usage.sqlite3", dependencies=[Depends(deny)]))
    client = TestClient(app)
    assert client.get("/api/usage/summary").status_code == 401
    assert client.post("/api/usage/events", content=_body([])).status_code == 401


# ------------------------------------------------------------ client privacy

def test_client_sends_only_to_a_same_origin_relative_url() -> None:
    files = sorted(CLIENT_DIR.iterdir())
    assert any(f.suffix == ".js" for f in files)
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"https?://", text, re.IGNORECASE), f"absolute URL in {f.name}"
        assert not re.search(r"""['"`]//[A-Za-z0-9]""", text), f"protocol-relative URL in {f.name}"
        assert "XMLHttpRequest" not in text and "WebSocket" not in text, f.name
    js = (CLIENT_DIR / "usage-log.js").read_text(encoding="utf-8")
    assert "const DEFAULT_ENDPOINT = '/api/usage/events';" in js
    assert "userAgent" not in js.split("export function osClass")[0], "UA read outside osClass"


# ------------------------------------------------------------ summary CLI

def test_cli_missing_db_exits_non_zero_with_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = usage_summary.main(["--app", "demo", "--db", str(tmp_path / "absent.sqlite3"), "--json"])
    assert code == usage_summary.EXIT_NO_DATA != 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no usage data yet" in captured.err and "not zero usage" in captured.err


def test_cli_resolves_app_under_fleet_data_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("FLEET_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("DEMO_APP_DATA_DIR", raising=False)
    UsageLog(tmp_path / "demo-app" / "usage.sqlite3").record(Batch(SESSION, "phone", "android", [
        Event("view", "board", None), Event("tap", "board", "refresh"),
    ]))
    assert usage_summary.main(["--app", "demo-app", "--days", "30", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["app"] == "demo-app"
    assert out["views"] == {"board": 1}
    assert out["controls"] == {"refresh": 1}
    assert out["devices"] == {"phone": 1}


def test_cli_existing_empty_db_is_zero_usage_not_no_data(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "usage.sqlite3"
    UsageLog(db).summary(1)  # creates the schema, no rows
    assert usage_summary.main(["--app", "demo", "--db", str(db)]) == 0
    assert "0 sessions" in capsys.readouterr().out
