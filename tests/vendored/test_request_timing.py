"""The vendored request-timing middleware: queue/worker split, Server-Timing, slow and budget lines.

Every timing here comes from an injected clock or a held thread, never from wall time,
so a slow machine cannot turn a pass into a fail.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any

import pytest

from src import request_timing as rt


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _scope(path: str, method: str = "GET", query: bytes = b"", kind: str = "http") -> dict[str, Any]:
    return {"type": kind, "method": method, "path": path, "query_string": query}


def _drive(middleware: rt.RequestTimingMiddleware, scope: dict[str, Any]) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b""}

    async def send(message: Any) -> None:
        sent.append(dict(message))

    asyncio.run(middleware(scope, receive, send))
    return sent


def _app_taking(clock: FakeClock, seconds: float, status: int = 200) -> rt.ASGIApp:
    """An ASGI app whose handler 'takes' `seconds` on the fake clock."""

    async def app(scope: Any, receive: Any, send: Any) -> None:
        clock.now += seconds
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": b"{}"})

    return app


BOARD = rt.BudgetClass("board", "GET", lambda p, q: p == "/api/board", rt.Budget(0.5, 1.5))


def _middleware(clock: FakeClock, seconds: float, **kwargs: Any) -> rt.RequestTimingMiddleware:
    return rt.RequestTimingMiddleware(_app_taking(clock, seconds), clock=clock, **kwargs)


def _header(sent: list[dict[str, Any]], name: bytes) -> Any:
    start = next(m for m in sent if m["type"] == "http.response.start")
    return next((v for k, v in start["headers"] if k == name), None)


def test_an_api_response_carries_server_timing_with_the_total_from_the_clock() -> None:
    clock = FakeClock()
    sent = _drive(_middleware(clock, 0.25), _scope("/api/board"))
    value = _header(sent, b"server-timing").decode()
    assert 'queue;dur=0.0;desc="none"' in value
    assert "app;dur=250.0" in value


def test_a_path_outside_the_timed_prefix_gets_no_header() -> None:
    clock = FakeClock()
    assert _header(_drive(_middleware(clock, 0.1), _scope("/static/app.js")), b"server-timing") is None


def test_a_websocket_scope_passes_straight_through() -> None:
    seen: list[str] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen.append(scope["type"])

    middleware = rt.RequestTimingMiddleware(app)
    _drive(middleware, _scope("/ws", kind="websocket"))
    assert seen == ["websocket"]
    assert middleware.stats.snapshot(60)["max_inflight"] == 0


@pytest.mark.parametrize(("seconds", "verdict", "line"), [
    (0.4, "ok", None),
    (1.0, "over", "over budget"),
    (2.0, "breach", "budget breach"),
])
def test_a_declared_class_is_judged_against_its_budget(
    seconds: float, verdict: str, line: Any, caplog: pytest.LogCaptureFixture
) -> None:
    clock = FakeClock()
    middleware = _middleware(clock, seconds, classes=[BOARD])
    with caplog.at_level(logging.WARNING, logger="request_timing"):
        _drive(middleware, _scope("/api/board"))
    assert middleware.stats.snapshot(60)["verdicts"] == {"board": {**{"ok": 0, "over": 0, "breach": 0}, verdict: 1}}
    if line is None:
        assert not caplog.records
    else:
        assert line in caplog.text and "(board)" in caplog.text


def test_a_live_override_moves_the_limit_and_a_bad_one_cannot_switch_it_off() -> None:
    clock = FakeClock()
    overrides: dict[str, Any] = {"board": [1.2, 3.0]}
    middleware = _middleware(clock, 1.0, classes=[BOARD], budget_overrides=lambda: overrides)
    _drive(middleware, _scope("/api/board"))
    assert middleware.stats.snapshot(60)["verdicts"]["board"]["ok"] == 1
    overrides["board"] = [0, -1]  # invalid: the declared default stands
    _drive(middleware, _scope("/api/board"))
    assert middleware.stats.snapshot(60)["verdicts"]["board"]["over"] == 1


def test_a_slow_request_logs_where_its_time_went(caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock()
    with caplog.at_level(logging.WARNING, logger="request_timing"):
        _drive(_middleware(clock, 4.0, slow_s=3.0), _scope("/api/thing"))
    assert "slow request: GET /api/thing → 200 in 4.0s" in caplog.text
    assert "total_ms=4000 pool=none" in caplog.text


def test_the_in_flight_warning_names_the_oldest_and_is_rate_limited(caplog: pytest.LogCaptureFixture) -> None:
    clock = FakeClock()
    middleware = rt.RequestTimingMiddleware(_app_taking(clock, 0), clock=clock, inflight_warn=1)
    middleware._inflight = {-1: ("GET", "/api/old", clock.now - 9), -2: ("GET", "/api/new", clock.now)}
    with caplog.at_level(logging.WARNING, logger="request_timing"):
        _drive(middleware, _scope("/api/third"))
        _drive(middleware, _scope("/api/fourth"))
    lines = [r.getMessage() for r in caplog.records if "in flight" in r.getMessage()]
    assert len(lines) == 1 and "oldest: GET /api/old, 9.0s old" in lines[0]


def test_a_timed_pool_splits_queue_from_worker_time() -> None:
    """One worker held busy: the second call's wait is queue, its own run is worker."""
    pool = rt.TimedExecutor("hot-poll", 1)
    gate = threading.Event()
    timing = rt.RequestTiming()
    token = rt.current.set(timing)
    try:
        blocker = pool.submit(gate.wait)
        second = pool.submit(lambda: None)
        threading.Timer(0.05, gate.set).start()
        blocker.result(5)
        second.result(5)
    finally:
        rt.current.reset(token)
        pool.shutdown()
    assert timing.calls == 2 and timing.pool == "hot-poll"
    assert timing.queue_s >= 0.04, "the second call waited behind the held worker"


def test_a_submit_outside_any_request_is_not_charged() -> None:
    pool = rt.TimedExecutor("bg", 1)
    try:
        assert pool.submit(lambda: 7).result(5) == 7
    finally:
        pool.shutdown()
    assert rt.current.get() is None


def test_the_default_executor_is_a_timed_pool_named_default() -> None:
    pool = rt.default_executor()
    try:
        assert pool.pool_name == rt.DEFAULT_POOL
    finally:
        pool.shutdown()


def test_peaks_age_out_of_the_window() -> None:
    clock = FakeClock()
    stats = rt.RequestStats(clock)
    stats.entered(5)
    clock.now += 120
    stats.entered(1)
    assert stats.max_inflight(60) == 1
    assert stats.max_inflight(300) == 5
