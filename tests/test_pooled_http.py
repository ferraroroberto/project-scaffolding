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
