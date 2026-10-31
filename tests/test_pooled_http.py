from __future__ import annotations

import pytest
import requests

from src import pooled_http


def test_build_session_mounts_adapter_sized_to_request() -> None:
    session = pooled_http.build_session(pool_size=7)

    adapter = session.get_adapter("http://example.invalid")

    assert isinstance(adapter, pooled_http.HTTPAdapter)
    assert adapter._pool_maxsize == 7
    assert adapter._pool_connections == 7


def test_pooled_request_dispatches_through_the_given_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    class _Resp:
        pass

    def fake_request(method: str, url: str, timeout: float | None = None, **kwargs: object) -> object:
        calls.append((method, url))
        return _Resp()

    session = pooled_http.build_session()
    monkeypatch.setattr(session, "request", fake_request)

    resp = pooled_http.pooled_request("GET", "http://x/y", timeout=2.0, session=session)

    assert isinstance(resp, _Resp)
    assert calls == [("GET", "http://x/y")]


def test_pooled_request_uses_module_default_session_when_unspecified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    class _Resp:
        pass

    def fake_request(method: str, url: str, timeout: float | None = None, **kwargs: object) -> object:
        calls.append((method, url))
        return _Resp()

    monkeypatch.setattr(pooled_http.SESSION, "request", fake_request)

    resp = pooled_http.pooled_request("GET", "http://x/y", timeout=2.0)

    assert isinstance(resp, _Resp)
    assert calls == [("GET", "http://x/y")]


def test_pooled_request_retries_once_on_dropped_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = {"n": 0}

    class _Resp:
        pass

    def flaky_request(method: str, url: str, timeout: float | None = None, **kwargs: object) -> object:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise requests.exceptions.ConnectionError("stale pooled socket")
        return _Resp()

    session = pooled_http.build_session()
    monkeypatch.setattr(session, "request", flaky_request)

    resp = pooled_http.pooled_request("GET", "http://x/y", timeout=2.0, session=session)

    assert isinstance(resp, _Resp)
    assert attempts["n"] == 2


def test_pooled_request_gives_up_after_second_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def always_fails(method: str, url: str, timeout: float | None = None, **kwargs: object) -> object:
        raise requests.exceptions.ConnectionError("still down")

    session = pooled_http.build_session()
    monkeypatch.setattr(session, "request", always_fails)

    with pytest.raises(requests.exceptions.ConnectionError):
        pooled_http.pooled_request("GET", "http://x/y", timeout=2.0, session=session)


def _failing_session(monkeypatch: pytest.MonkeyPatch, error: Exception) -> tuple[requests.Session, list[str]]:
    calls: list[str] = []

    def failing_request(method: str, url: str, timeout: float | None = None, **kwargs: object) -> object:
        calls.append(method)
        raise error

    session = pooled_http.build_session()
    monkeypatch.setattr(session, "request", failing_request)
    return session, calls


@pytest.mark.parametrize("method", ["POST", "PATCH", "post"])
def test_a_non_idempotent_method_is_never_resent(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    # RemoteDisconnected after the handler ran is wrapped into the same ConnectionError.
    session, calls = _failing_session(monkeypatch, requests.exceptions.ConnectionError("RemoteDisconnected"))

    with pytest.raises(requests.exceptions.ConnectionError):
        pooled_http.pooled_request(method, "http://x/y", timeout=2.0, session=session)

    assert len(calls) == 1


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "PUT", "DELETE", "get"])
def test_an_idempotent_method_is_resent_once(monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    session, calls = _failing_session(monkeypatch, requests.exceptions.ConnectionError("still down"))

    with pytest.raises(requests.exceptions.ConnectionError):
        pooled_http.pooled_request(method, "http://x/y", timeout=2.0, session=session)

    assert len(calls) == 2


def test_a_connect_timeout_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    session, calls = _failing_session(monkeypatch, requests.exceptions.ConnectTimeout("offline"))

    with pytest.raises(requests.exceptions.ConnectTimeout):
        pooled_http.pooled_request("GET", "http://x/y", timeout=2.0, session=session)

    assert len(calls) == 1
