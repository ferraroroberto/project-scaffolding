"""Tests for the Starlette adapter of the usage log (`src/usage_log_starlette.py`).

Two things are proven: the owner check decides on the headers Tailscale's proxy
sets (a Funnel guest connects from loopback, so the peer alone cannot), and the
route serves the real router inside a Starlette app that has no FastAPI of its
own, ahead of a catch-all token route.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from src.usage_log_starlette import FORWARDED_HEADER, FUNNEL_HEADER, is_owner, usage_route

SESSION = "3f2b8c1e-0d4a-4b6f-9c2e-1a2b3c4d5e6f"
EVENT_BODY = json.dumps({
    "session_id": SESSION, "device_class": "phone", "os_class": "ios",
    "events": [{"kind": "tap", "id": "save"}],
})


@pytest.mark.parametrize(
    ("peer", "headers", "expected"),
    [
        ("127.0.0.1", {}, True),                                   # the owner on this machine
        ("::1", {}, True),
        ("::ffff:127.0.0.1", {}, True),                            # IPv4-mapped loopback
        ("100.101.102.103", {}, True),                             # a tailnet peer, direct
        ("fd7a:115c:a1e0::1", {}, True),
        ("192.168.1.20", {}, False),                               # LAN is not the tailnet
        ("8.8.8.8", {}, False),
        (None, {}, False),                                         # no peer address
        ("not-an-address", {}, False),
        ("127.0.0.1", {FUNNEL_HEADER: "?1"}, False),               # a funnelled guest
        ("127.0.0.1", {FUNNEL_HEADER: ""}, False),                 # present, even if empty
        ("127.0.0.1", {FORWARDED_HEADER: "100.101.102.103"}, True),
        ("127.0.0.1", {FORWARDED_HEADER: "::1"}, True),
        ("127.0.0.1", {FORWARDED_HEADER: "203.0.113.9"}, False),   # a public caller
        ("127.0.0.1", {FORWARDED_HEADER: "garbage"}, False),       # unparsable → not the owner
        ("127.0.0.1", {FORWARDED_HEADER: ""}, False),
        # the last hop decides, so a spoofed leading address cannot promote a guest
        ("127.0.0.1", {FORWARDED_HEADER: "100.64.0.1, 203.0.113.9"}, False),
        ("127.0.0.1", {FORWARDED_HEADER: "203.0.113.9, 100.64.0.1"}, True),
        ("127.0.0.1", {FUNNEL_HEADER: "?1", FORWARDED_HEADER: "100.64.0.1"}, False),
    ],
)
def test_is_owner(peer: str | None, headers: Mapping[str, str], expected: bool) -> None:
    assert is_owner(peer, headers) is expected


def _app(db: Path) -> Starlette:
    async def token(request: Request) -> JSONResponse:
        return JSONResponse({"token": request.path_params["token"]})

    # The catch-all comes after the usage route, as the module docstring says.
    return Starlette(routes=[usage_route(db), Route("/api/{token}", token)])


def _client(db: Path, host: str = "127.0.0.1") -> TestClient:
    return TestClient(_app(db), client=(host, 50000))


def _tap_rows(db: Path) -> list[tuple[object, ...]]:
    conn = sqlite3.connect(db)
    try:
        return conn.execute("SELECT kind, control_id FROM events").fetchall()
    finally:
        conn.close()


def test_owner_posts_and_reads(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite3"
    client = _client(db)
    posted = client.post("/api/usage/events", content=EVENT_BODY)
    assert posted.status_code == 200
    assert posted.json() == {"accepted": 1, "rejected": 0}
    assert _tap_rows(db) == [("tap", "save")]
    summary = client.get("/api/usage/summary")
    assert summary.status_code == 200
    assert summary.json()["controls"] == {"save": 1}
    assert client.get("/api/usage/time?days=1").status_code == 200


def test_guest_post_is_accepted_but_reads_are_owner_only(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite3"
    client = _client(db)
    guest = {FUNNEL_HEADER: "?1", FORWARDED_HEADER: "203.0.113.9"}
    assert client.post("/api/usage/events", content=EVENT_BODY, headers=guest).status_code == 200
    assert _tap_rows(db) == [("tap", "save")]
    for path in ("/api/usage/summary", "/api/usage/time"):
        refused = client.get(path, headers=guest)
        assert refused.status_code == 403
        assert refused.json() == {"detail": "owner only"}


def test_peer_outside_loopback_and_tailnet_cannot_read(tmp_path: Path) -> None:
    client = _client(tmp_path / "usage.sqlite3", host="198.51.100.7")
    assert client.get("/api/usage/summary").status_code == 403


def test_tailnet_peer_can_read(tmp_path: Path) -> None:
    client = _client(tmp_path / "usage.sqlite3", host="100.100.100.100")
    assert client.get("/api/usage/summary").status_code == 200


def test_usage_requests_never_reach_the_token_route(tmp_path: Path) -> None:
    client = _client(tmp_path / "usage.sqlite3")
    # `/api/usage/summary` is two segments, so it could not match `/api/{token}`
    # anyway; the one-segment sibling proves the catch-all still works around it.
    assert client.get("/api/abc123").json() == {"token": "abc123"}
    assert client.get("/api/usage/summary").json()["log_exists"] is False


def test_no_interactive_docs_are_served(tmp_path: Path) -> None:
    client = _client(tmp_path / "usage.sqlite3")
    for path in ("/api/usage/docs", "/api/usage/redoc", "/api/usage/openapi.json"):
        assert client.get(path).status_code == 404


def test_read_never_creates_the_database(tmp_path: Path) -> None:
    db = tmp_path / "usage.sqlite3"
    _client(db).get("/api/usage/summary")
    assert not db.exists()
