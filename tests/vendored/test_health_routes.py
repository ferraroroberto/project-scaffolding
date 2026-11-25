"""The vendored health routes: liveness, the version payload and its loopback bypass."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src import health_routes
from src.health_routes import health_router, is_local_caller

IDENTITY = {"git_sha": "abc1234", "built_at": "2026-11-25T10:00:00"}
LOCAL = ("127.0.0.1", 50000)
REMOTE = ("100.101.102.103", 50000)


def _client(host: tuple[str, int] = LOCAL, **kwargs: Any) -> TestClient:
    app = FastAPI()
    app.include_router(health_router(service="demo", identity=IDENTITY, **kwargs))
    return TestClient(app, client=host)


def _signed_in(request: Request) -> bool:
    return request.headers.get("authorization") == "Bearer good"


def test_healthz_is_open_and_names_the_service() -> None:
    reply = _client(REMOTE, authorize=lambda _r: False).get("/healthz")
    assert reply.status_code == 200
    assert reply.json() == {"ok": True, "service": "demo"}


def test_version_serves_the_captured_identity() -> None:
    reply = _client().get("/api/version")
    assert reply.status_code == 200
    assert reply.json() == IDENTITY


def test_identity_defaults_to_build_info_captured_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_identity() -> dict[str, str]:
        calls.append(1)
        return {"git_sha": "def5678", "built_at": "2026-11-25T11:00:00"}

    monkeypatch.setattr(health_routes, "build_identity", fake_identity)
    app = FastAPI()
    app.include_router(health_router(service="demo"))
    client = TestClient(app, client=LOCAL)
    assert client.get("/api/version").json()["git_sha"] == "def5678"
    client.get("/api/version")
    assert calls == [1], "captured when the router is built, never re-resolved per request"


def test_extra_fields_never_override_the_identity() -> None:
    reply = _client(extra={"version": "1.2.0", "git_sha": "spoofed"}).get("/api/version")
    assert reply.json() == {"version": "1.2.0", **IDENTITY}


def test_loopback_skips_authorize() -> None:
    assert _client(LOCAL, authorize=lambda _r: False).get("/api/version").status_code == 200


def test_a_remote_caller_needs_authorize() -> None:
    client = _client(REMOTE, authorize=_signed_in)
    assert client.get("/api/version").status_code == 401
    assert client.get("/api/version", headers={"Authorization": "Bearer good"}).json() == IDENTITY


@pytest.mark.parametrize("header", ["X-Forwarded-For", "Forwarded", "Tailscale-Funnel-Request"])
def test_a_proxied_loopback_request_is_remote(header: str) -> None:
    client = _client(LOCAL, authorize=_signed_in)
    assert client.get("/api/version", headers={header: "100.64.0.9"}).status_code == 401


def test_an_async_authorize_and_its_own_exception_are_honoured() -> None:
    async def allow(_request: Request) -> bool:
        return True

    def refuse(_request: Request) -> bool:
        raise HTTPException(status_code=403, detail="nope")

    assert _client(REMOTE, authorize=allow).get("/api/version").status_code == 200
    assert _client(REMOTE, authorize=refuse).get("/api/version").status_code == 403


def test_no_authorize_leaves_version_open() -> None:
    assert _client(REMOTE).get("/api/version").status_code == 200


def test_version_false_mounts_only_healthz() -> None:
    client = _client(version=False)
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/version").status_code == 404


@pytest.mark.parametrize(
    ("peer", "headers", "local"),
    [
        ("127.0.0.1", {}, True),
        ("::1", {}, True),
        ("::ffff:127.0.0.1", {}, True),
        ("127.0.0.1", {"x-forwarded-for": "127.0.0.1"}, False),
        ("192.168.1.5", {}, False),
        ("testclient", {}, False),
        (None, {}, False),
    ],
)
def test_is_local_caller(peer: str | None, headers: dict[str, str], local: bool) -> None:
    assert is_local_caller(peer, headers) is local
