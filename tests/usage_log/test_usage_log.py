"""Unit tests for the usage-log convention (#349): validation, retention,
privacy, the FastAPI router, the summary CLI, and foreground time (#403).

The privacy contract is asserted here rather than trusted to the client: the
server drops anything outside the allowlists, stores no field it was not
designed to store, and the shipped client files name no host at all.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scripts import usage_summary
from src.usage_log import (
    MAX_BODY_BYTES,
    MAX_EVENTS_PER_BATCH,
    NO_VIEW,
    Batch,
    Event,
    PayloadError,
    UsageLog,
    foreground_time,
    format_ts,
    local_window,
    parse_batch,
    usage_router,
    validate_event,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
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
        user_agent=secret, ip=secret, url=secret, country=secret, visitor=secret,
    ))
    UsageLog(db).record(batch)
    conn = sqlite3.connect(db)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(events)")]
        site_columns = conn.execute("SELECT country, visitor FROM events").fetchall()
    finally:
        conn.close()
    assert columns == ["id", "ts", "session_id", "kind", "view_id", "control_id",
                       "device_class", "os_class", "country", "visitor"]
    # Only a server half that sees the request fills these; a client never can.
    assert site_columns == [(None, None)]
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


def test_router_summary_absent_log_is_not_zero_usage(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite3"
    body = _client(db).get("/api/usage/summary", params={"days": 7}).json()
    assert body["log_exists"] is False and body["events"] == 0
    assert not db.exists(), "reading the summary never creates the log"


def test_router_summary_unavailable_on_unreadable_db(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite3"
    db.write_text("not a database")
    r = _client(db).get("/api/usage/summary", params={"days": 7})
    assert r.status_code == 503


def test_every_usage_get_route_is_read_only_and_reports_log_exists(tmp_path: Path) -> None:
    """Structural check (audit#439, recurring bucket): every ``GET`` route on
    the usage router must follow the read-only-and-report-``log_exists``
    contract documented on :func:`usage_router` and already followed by
    ``/time`` — not just the route a past fix happened to touch. Catches a
    future read route (or a regression in an existing one) that reintroduces
    "no data yet" reading as zero usage."""
    db = tmp_path / "usage.sqlite3"
    client = _client(db)
    spec = client.get("/openapi.json").json()["paths"]
    get_paths = [path for path, methods in spec.items()
                 if path.startswith("/api/usage/") and "get" in methods]
    assert len(get_paths) >= 2, "sanity: summary and time are both routed"
    for path in get_paths:
        resp = client.get(path)
        assert resp.status_code == 200, path
        assert resp.json().get("log_exists") is False, f"{path} must report log_exists"
        assert not db.exists(), f"{path} must never create the log file on read"


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
    assert client.get("/api/usage/time").status_code == 401
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


def test_cli_time_prints_per_day_minutes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    db = tmp_path / "usage.sqlite3"
    now = datetime.now(UTC)  # --days 2 starts at yesterday's local midnight
    UsageLog(db).insert_rows([
        (format_ts(now - timedelta(minutes=20)), SESSION, "session_start", None, None,
         "phone", "ios"),
        (format_ts(now - timedelta(minutes=10)), SESSION, "session_end", None, None,
         "phone", "ios"),
    ])
    assert usage_summary.main(["--app", "demo", "--db", str(db), "--days", "2",
                               "--time", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["app"] == "demo" and out["days"] == 2
    assert out["total_minutes"] == 10.0 and out["by_device"] == {"phone": 10.0}
    assert usage_summary.main(["--app", "demo", "--db", str(db), "--days", "2", "--time"]) == 0
    text = capsys.readouterr().out
    assert "foreground time: demo" in text and "phone 10.0" in text


# ------------------------------------------------------------ foreground time (#403)
# Synthetic visits only. Minutes are offsets from 09:00 UTC on DAY; the
# default window is that one UTC day.

DAY = datetime(2026, 10, 12, tzinfo=UTC)
OS_FOR = {"phone": "ios", "tablet": "android", "desktop": "windows"}
Row = tuple[str, str, str, str | None, None, str, str]


def _ev(
    minute: float, kind: str, *, visit: str = "visit-aaaa", device: str = "phone",
    view: str | None = None,
) -> Row:
    ts = format_ts(DAY + timedelta(hours=9, minutes=minute))
    return (ts, visit, kind, view, None, device, OS_FOR[device])


def _time(
    tmp_path: Path, rows: list[Row], *,
    since: datetime = DAY, until: datetime = DAY + timedelta(days=1),
    tz: tzinfo | None = UTC, **rules: timedelta,
) -> dict[str, Any]:
    """Insert ``rows`` in list order (so ``id`` follows it) and compute."""
    db = tmp_path / "usage.sqlite3"
    UsageLog(db).insert_rows(rows, now=NOW)
    conn = sqlite3.connect(db)
    try:
        return foreground_time(conn, since, until, tz, **rules)
    finally:
        conn.close()


def test_time_open_close(tmp_path: Path) -> None:
    out = _time(tmp_path, [_ev(0, "session_start"), _ev(30, "session_end")])
    assert out["total_minutes"] == 30.0
    assert out["by_device"] == {"phone": 30.0}
    assert out["days_series"] == [{"day": "2026-10-12", "minutes": 30.0,
                                   "by_device": {"phone": 30.0}, "by_view": {NO_VIEW: 30.0}}]


def test_time_missing_end_closes_at_last_event(tmp_path: Path) -> None:
    out = _time(tmp_path, [_ev(0, "session_start"), _ev(5, "view", view="board"),
                           _ev(20, "tap", view="board")])
    assert out["total_minutes"] == 20.0, "closed at the last event, never padded"


def test_time_double_start_closes_at_last_event_before_it(tmp_path: Path) -> None:
    out = _time(tmp_path, [
        _ev(0, "session_start"), _ev(10, "tap"),   # the hide beacon was lost here
        _ev(40, "session_start"), _ev(50, "session_end"),
    ])
    assert out["total_minutes"] == 20.0, "0-10 and 40-50; the 10-40 gap is not counted"


def test_time_end_without_start(tmp_path: Path) -> None:
    only_end = _time(tmp_path, [_ev(10, "session_end")])
    assert only_end["total_minutes"] == 0.0
    lost_start = _time(tmp_path / "b", [_ev(0, "view", view="board"), _ev(12, "session_end")])
    assert lost_start["total_minutes"] == 12.0, "opens at the first event of the visit"


def test_time_zero_length_visit_is_zero(tmp_path: Path) -> None:
    out = _time(tmp_path, [
        _ev(0, "session_start", visit="visit-phone"),
        _ev(0, "session_start", visit="visit-desk", device="desktop"),
        _ev(5, "session_start", visit="visit-both"), _ev(5, "session_end", visit="visit-both"),
    ])
    assert out["total_minutes"] == 0.0
    assert out["by_device"] == {} and out["by_view"] == {}


def test_time_desktop_idle_gap_is_clipped(tmp_path: Path) -> None:
    rows = [_ev(0, "session_start", device="desktop"), _ev(5, "tap", device="desktop"),
            _ev(65, "session_end", device="desktop")]
    assert _time(tmp_path, rows)["total_minutes"] == 20.0, "5 active + the 60 min gap as 15"
    shorter = _time(tmp_path / "b", rows, idle_gap_desktop=timedelta(minutes=5))
    assert shorter["total_minutes"] == 10.0, "the idle cut is overridable"
    assert shorter["rules"]["idle_gap_desktop_minutes"] == 5.0


def test_time_phone_gap_is_trusted(tmp_path: Path) -> None:
    out = _time(tmp_path, [_ev(0, "session_start"), _ev(65, "session_end")])
    assert out["total_minutes"] == 65.0, "auto-lock hides the page, so no idle cut"


def test_time_max_interval_caps_phone_and_tablet(tmp_path: Path) -> None:
    rows = [_ev(0, "session_start", device="tablet"), _ev(300, "session_end", device="tablet")]
    assert _time(tmp_path, rows)["total_minutes"] == 240.0
    capped = _time(tmp_path / "b", rows, max_interval=timedelta(hours=1))
    assert capped["total_minutes"] == 60.0
    assert capped["rules"]["max_interval_minutes"] == 60.0


def test_time_overlapping_tabs_same_device_count_once(tmp_path: Path) -> None:
    out = _time(tmp_path, [
        _ev(0, "session_start", visit="visit-tab1"), _ev(10, "session_start", visit="visit-tab2"),
        _ev(20, "session_end", visit="visit-tab1"), _ev(30, "session_end", visit="visit-tab2"),
    ])
    assert out["total_minutes"] == 30.0, "0-20 and 10-30 are 30 min, not 40"
    assert out["by_device"] == {"phone": 30.0}


def test_time_phone_and_desktop_overlap(tmp_path: Path) -> None:
    out = _time(tmp_path, [
        _ev(0, "session_start", visit="visit-phone"),
        _ev(10, "session_start", visit="visit-desk", device="desktop"),
        _ev(25, "tap", visit="visit-desk", device="desktop"),
        _ev(30, "session_end", visit="visit-phone"),
        _ev(40, "session_end", visit="visit-desk", device="desktop"),
    ])
    assert out["total_minutes"] == 40.0, "the total is the union"
    assert out["by_device"] == {"desktop": 30.0, "phone": 30.0}, "each device keeps its own"
    assert sum(out["by_device"].values()) > out["total_minutes"]


def test_time_splits_at_local_midnight_in_tz(tmp_path: Path) -> None:
    plus2 = timezone(timedelta(hours=2))
    rows = [  # 21:30-22:30 UTC is 23:30-00:30 at UTC+2
        _ev(12 * 60 + 30, "session_start"), _ev(13 * 60 + 30, "session_end"),
    ]
    since = datetime(2026, 10, 12, tzinfo=plus2)
    out = _time(tmp_path, rows, since=since, until=since + timedelta(days=2), tz=plus2)
    assert [(d["day"], d["minutes"]) for d in out["days_series"]] == [
        ("2026-10-12", 30.0), ("2026-10-13", 30.0)]
    assert out["tz"] == "UTC+02:00"
    in_utc = _time(tmp_path / "b", rows)
    assert [(d["day"], d["minutes"]) for d in in_utc["days_series"]] == [("2026-10-12", 60.0)]


def test_time_view_attribution_and_overlap_rule(tmp_path: Path) -> None:
    out = _time(tmp_path, [
        _ev(0, "session_start", visit="visit-phone"),
        _ev(0, "view", visit="visit-phone", view="board"),
        _ev(10, "view", visit="visit-phone", view="settings"),
        _ev(20, "session_start", visit="visit-desk", device="desktop"),
        _ev(20, "view", visit="visit-desk", device="desktop", view="jobs"),
        _ev(30, "session_end", visit="visit-phone"),
        _ev(32, "tap", visit="visit-desk", device="desktop", view="jobs"),
        _ev(40, "session_end", visit="visit-desk", device="desktop"),
    ])
    # 20-30 is covered by both visits: the more recently started one wins.
    assert out["by_view"] == {"jobs": 20.0, "board": 10.0, "settings": 10.0}
    assert sum(out["by_view"].values()) == out["total_minutes"] == 40.0


def test_time_before_first_view_and_view_carried_across_intervals(tmp_path: Path) -> None:
    out = _time(tmp_path, [
        _ev(0, "session_start"), _ev(5, "view", view="board"), _ev(10, "session_end"),
        _ev(30, "session_start"), _ev(40, "session_end"),   # back on the same view
    ])
    assert out["by_view"] == {"board": 15.0, NO_VIEW: 5.0}


def test_time_same_ts_batch_is_ordered_by_id(tmp_path: Path) -> None:
    out = _time(tmp_path, [
        # One batch, one server ts: the last view in id order is the current one.
        # (Not alphabetical, so a sort on view_id would pick the wrong one.)
        _ev(0, "session_start"), _ev(0, "view", view="settings"), _ev(0, "view", view="board"),
        # Hidden and shown again within the same second: end then start at 10.
        _ev(10, "session_end"), _ev(10, "session_start"), _ev(10, "view", view="jobs"),
        _ev(20, "session_end"),
    ])
    assert out["by_view"] == {"board": 10.0, "jobs": 10.0}
    assert out["total_minutes"] == 20.0


def test_time_window_clips_and_lists_zero_days(tmp_path: Path) -> None:
    rows = [  # 23:30 UTC the day before DAY until 00:30 UTC on DAY
        _ev(-9 * 60 - 30, "session_start"), _ev(-8 * 60 - 30, "session_end"),
    ]
    out = _time(tmp_path, rows, until=DAY + timedelta(days=3))
    assert out["days"] == 3
    assert [(d["day"], d["minutes"]) for d in out["days_series"]] == [
        ("2026-10-12", 30.0), ("2026-10-13", 0.0), ("2026-10-14", 0.0)]
    assert out["days_series"][1]["by_device"] == {}


def test_time_never_returns_session_ids(tmp_path: Path) -> None:
    out = _time(tmp_path, [_ev(0, "session_start", visit=SESSION),
                           _ev(9, "session_end", visit=SESSION)])
    assert out["total_minutes"] == 9.0
    assert SESSION not in json.dumps(out)


def test_time_rejects_empty_window(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="after since"):
        _time(tmp_path, [], until=DAY)


def test_local_window_starts_at_local_midnight() -> None:
    plus2 = timezone(timedelta(hours=2))
    now = datetime(2026, 10, 12, 23, 30, tzinfo=UTC)   # already 10-13 at UTC+2
    assert local_window(1, plus2, now=now) == (datetime(2026, 10, 12, 22, 0, tzinfo=UTC), now)
    assert local_window(7, UTC, now=now)[0] == datetime(2026, 10, 6, tzinfo=UTC)
    with pytest.raises(ValueError):
        local_window(0, UTC, now=now)


# ------------------------------------------------------------ GET /api/usage/time

def test_time_route_shape_and_by_values(tmp_path: Path) -> None:
    client = _client(tmp_path / "usage.sqlite3")
    client.post("/api/usage/events", content=_body([{"kind": "view", "id": "board"}]))
    day = client.get("/api/usage/time", params={"days": 7})
    assert day.status_code == 200
    body = day.json()
    assert body["days"] == 7 and len(body["days_series"]) == 7
    assert body["by"] == "day" and body["log_exists"] is True
    assert {"since", "until", "tz", "rules", "total_minutes"} <= body.keys()
    assert "by_device" not in body and "by_view" not in body
    assert set(body["days_series"][0]) == {"day", "minutes"}

    device = client.get("/api/usage/time", params={"days": 1, "by": "device"}).json()
    assert "by_device" in device and "by_view" not in device
    assert set(device["days_series"][0]) == {"day", "minutes", "by_device"}
    view = client.get("/api/usage/time", params={"by": "view"}).json()
    assert view["days"] == 7, "the default window"
    assert "by_view" in view and "by_device" not in view
    assert client.get("/api/usage/time", params={"by": "visit"}).status_code == 422


@pytest.mark.parametrize(("days", "status"), [(0, 422), (1, 200), (366, 200), (367, 422)])
def test_time_route_days_bounds(tmp_path: Path, days: int, status: int) -> None:
    client = _client(tmp_path / "usage.sqlite3")
    assert client.get("/api/usage/time", params={"days": days}).status_code == status


def test_time_route_absent_log_is_not_zero_usage(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite3"
    body = _client(db).get("/api/usage/time").json()
    assert body["log_exists"] is False and body["total_minutes"] == 0.0
    assert not db.exists(), "reading foreground time never creates the log"


def test_referrer_events_are_stored_with_their_host(tmp_path: Path) -> None:
    """A public site's client reports the external referrer host once per page load."""
    db = tmp_path / "usage.sqlite3"
    batch = parse_batch(_body([
        {"kind": "session_start"},
        {"kind": "referrer", "id": "linkedin.com"},
        {"kind": "referrer", "id": "https://x.example/a"},
        {"kind": "referrer"},
    ]))
    assert batch.rejected == 2
    log = UsageLog(db)
    log.record(batch)
    out = log.summary(7)
    assert out["referrers"] == {"linkedin.com": 1}
    assert out["countries"] == {} and out["visitors"] == 0


def test_an_older_file_gains_the_site_columns_in_place(tmp_path: Path) -> None:
    """A usage.sqlite3 created before the site columns existed is migrated on the next write."""
    db = tmp_path / "usage.sqlite3"
    conn = sqlite3.connect(db)
    conn.executescript(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, session_id TEXT NOT NULL,"
        " kind TEXT NOT NULL, view_id TEXT, control_id TEXT, device_class TEXT NOT NULL,"
        " os_class TEXT NOT NULL);"
    )
    conn.close()
    UsageLog(db).record(parse_batch(_body([{"kind": "view", "id": "board"}])))
    conn = sqlite3.connect(db)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(events)")]
    finally:
        conn.close()
    assert columns[-2:] == ["country", "visitor"]
    assert _rows(db) == [("view", "board", None, "phone", "ios")]


def test_summary_counts_countries_and_daily_visitors_when_present(tmp_path: Path) -> None:
    """Rows written by the Cloudflare half carry country and visitor; the summary counts them."""
    db = tmp_path / "usage.sqlite3"
    UsageLog(db).record(parse_batch(_body([{"kind": "view", "id": "home"}])))
    conn = sqlite3.connect(db)
    with conn:
        conn.executemany(
            "INSERT INTO events (ts, session_id, kind, view_id, device_class, os_class, country, visitor)"
            " VALUES (strftime('%Y-%m-%dT%H:%M:%SZ','now'), ?, 'view', 'home', 'phone', 'ios', ?, ?)",
            [("s-aaaaaaaa", "ES", "v1"), ("s-bbbbbbbb", "ES", "v1"), ("s-cccccccc", "IT", "v2")],
        )
    conn.close()
    out = UsageLog(db).summary(7)
    assert out["countries"] == {"ES": 2, "IT": 1}
    assert out["visitors"] == 2
