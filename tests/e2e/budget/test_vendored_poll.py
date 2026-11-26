"""The vendored `poll` helper keeps the request budget, and the probe catches a page that does not.

The probe page is answered by a Playwright route (it is not a file in the tree)
and imports the real `poll.js` from the static server. The API is a route too,
so every request is counted without a server.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import AbstractContextManager

import pytest
from playwright.sync_api import Page, Route

from tests.e2e._cases import cases
from tests.e2e.budget._request_budget import assert_request_budget, measure_request_budget, request_budget_problems

_PAGE = "/_vendored/poll/probe.html"

_STARTPOLL = "import { startPoll, singleFlight } from './poll.js';\n" \
             "const read = singleFlight(() => fetch('/api/board').then((r) => r.json()));\n" \
             "startPoll(read, 5000);"
# The pattern the ratchet's fixed-rate-poll rule bans: overlapping, and blind to a hidden tab.
_SETINTERVAL = "setInterval(() => fetch('/api/board'), 2000);"
_BUSY_ONLY = "import { startPoll } from './poll.js';\n" \
             "window.job = { running: false };\n" \
             "startPoll(() => fetch('/api/progress'), 1000, { activeWhile: () => window.job.running });"


# An EventSource the page opens at load, closes when hidden and reopens when visible.
_STREAM_CLOSES_ON_HIDE = (
    "let es = null;\n"
    "const open = () => { es = new EventSource('/api/events'); };\n"
    "const close = () => { if (es) es.close(); es = null; };\n"
    "open();\n"
    "document.addEventListener('visibilitychange', () => (document.hidden ? close() : open()));"
)
# The same stream, kept open while the page is hidden.
_STREAM_KEPT_WHILE_HIDDEN = "new EventSource('/api/events');"
# A stream the page opens late, in the visible minute.
_STREAM_OPENED_LATE = "setTimeout(() => new EventSource('/api/events'), 5000);"
# Two boot waves: the second starts when the first has answered.
_TWO_WAVE_BOOT = (
    "fetch('/api/who').then(() => Promise.all(['/api/tasks', '/api/today'].map((p) => fetch(p))));"
)


def _probe(page: Page, base_url: str, script: str) -> str:
    html = f"<!doctype html><html><body><script type=\"module\">{script}</script></body></html>"

    def answer_page(route: Route) -> None:
        route.fulfill(status=200, content_type="text/html", body=html)

    def answer_api(route: Route) -> None:
        route.fulfill(status=200, content_type="application/json", body="{}")

    def hold_stream(route: Route) -> None:
        # Never answered: the request stays out for as long as the page lives, like a real stream.
        pass

    page.route(f"**{_PAGE}", answer_page)
    page.route("**/api/**", answer_api)
    page.route("**/api/events", hold_stream)
    return f"{base_url}{_PAGE}"


def _keeps_the_budget(page: Page, base_url: str) -> None:
    reading = measure_request_budget(page, _probe(page, base_url, _STARTPOLL))
    assert_request_budget(reading, visible_max=12)
    assert sum(reading.visible.values()) >= 11, f"a 5 s poll reads about 12 times a minute: {reading.summary()}"
    assert reading.catch_up == {"/api/board": 1}, reading.summary()


def _catches_a_set_interval_poll(page: Page, base_url: str) -> None:
    reading = measure_request_budget(page, _probe(page, base_url, _SETINTERVAL))
    problems = request_budget_problems(reading, visible_max=12)
    assert any("while hidden" in p for p in problems), reading.summary()
    assert any("visible minute" in p for p in problems), reading.summary()


def _busy_only_poll_is_silent_when_idle(page: Page, base_url: str) -> None:
    reading = measure_request_budget(page, _probe(page, base_url, _BUSY_ONLY))
    assert not reading.visible and not reading.hidden and not reading.catch_up, reading.summary()


def _second_boot_wave_is_not_visible(page: Page, base_url: str) -> None:
    reading = measure_request_budget(page, _probe(page, base_url, _TWO_WAVE_BOOT))
    assert not reading.visible and not reading.hidden and not reading.catch_up, reading.summary()


_STREAMS = ("/api/events",)


def _measure_streaming(page: Page, base_url: str, script: str):
    return measure_request_budget(page, _probe(page, base_url, script), stream_paths=_STREAMS)


def _stream_is_measured_not_unknown(page: Page, base_url: str) -> None:
    reading = _measure_streaming(page, base_url, _STREAM_OPENED_LATE)
    assert reading.visible == {"/api/events": 1}, reading.summary()


def _stream_closed_on_hide_is_one_catch_up_read(page: Page, base_url: str) -> None:
    reading = _measure_streaming(page, base_url, _STREAM_CLOSES_ON_HIDE)
    assert_request_budget(reading, visible_max=12)
    assert not reading.visible, f"the stream opened at boot is not counted: {reading.summary()}"
    assert reading.catch_up == {"/api/events": 1}, reading.summary()


def _stream_kept_while_hidden_breaks_the_budget(page: Page, base_url: str) -> None:
    reading = _measure_streaming(page, base_url, _STREAM_KEPT_WHILE_HIDDEN)
    assert any("while hidden" in p for p in request_budget_problems(reading, visible_max=12)), reading.summary()


# A well-behaved poll quick enough to come due inside a short delay before the hide.
_QUICK_STARTPOLL = _STARTPOLL.replace("5000", "2000")
_HIDE_DELAY_MS = 2500


def _delay_the_hide(page: Page) -> None:
    """Stall the probe's hide call, as a loaded box does: real time passes with the page still visible."""
    evaluate = page.evaluate

    def delayed(expression: str, *args: object) -> object:
        if "__requestBudgetSetHidden(true)" in expression:
            page.wait_for_timeout(_HIDE_DELAY_MS)
        return evaluate(expression, *args)

    page.evaluate = delayed


def _visible_read_before_the_hide_is_not_hidden(page: Page, base_url: str) -> None:
    _delay_the_hide(page)
    reading = measure_request_budget(page, _probe(page, base_url, _QUICK_STARTPOLL))
    assert not reading.hidden, reading.summary()


# One flush as the page hides, then the same path again from a timer while hidden.
_FLUSHES_ON_HIDE = (
    "const flush = () => fetch('/api/usage/events', { method: 'POST' });\n"
    "document.addEventListener('visibilitychange', () => {\n"
    "  if (document.hidden) { flush(); setTimeout(flush, 5000); }\n"
    "});"
)


def _a_named_flush_is_allowed_once(page: Page, base_url: str) -> None:
    path = "/api/usage/events"
    reading = measure_request_budget(page, _probe(page, base_url, _FLUSHES_ON_HIDE), hidden_flushes=(path,))
    assert reading.flushed == {path: 1}, reading.summary()
    assert reading.hidden == {path: 1}, f"the repeat is a hidden request: {reading.summary()}"


def _assert_timers_run_on_a_second_page(page: Page, base_url: str) -> None:
    """A page opened later in the probed context still gets its `setTimeout` calls."""
    second = page.context.new_page()
    second.goto(_probe(second, base_url, ""))
    second.evaluate("() => { window.fired = false; setTimeout(() => { window.fired = true; }, 50); }")
    # Waited for from the driver: every in-page wait runs on the clock under test.
    deadline = time.monotonic() + 5
    while not second.evaluate("window.fired") and time.monotonic() < deadline:
        second.wait_for_timeout(50)
    assert second.evaluate("window.fired"), "the probe left the context's clock stopped"


def _the_clock_runs_after_a_reading(page: Page, base_url: str) -> None:
    measure_request_budget(page, _probe(page, base_url, _STARTPOLL), minute_ms=2_000)
    _assert_timers_run_on_a_second_page(page, base_url)


def _the_clock_runs_after_a_failed_reading(page: Page, base_url: str) -> None:
    evaluate = page.evaluate

    def broken(expression: str, *args: object) -> object:
        if "__requestBudgetSetHidden(true)" in expression:
            raise RuntimeError("the hide failed")
        return evaluate(expression, *args)

    page.evaluate = broken
    with pytest.raises(RuntimeError, match="the hide failed"):
        measure_request_budget(page, _probe(page, base_url, _STARTPOLL), minute_ms=2_000)
    _assert_timers_run_on_a_second_page(page, base_url)


_CHECKS = (
    ("a reading leaves the context's clock running", _the_clock_runs_after_a_reading),
    ("a failed reading leaves the context's clock running", _the_clock_runs_after_a_failed_reading),
    ("a named flush is allowed once", _a_named_flush_is_allowed_once),
    ("a poll due before the hide is not a hidden request", _visible_read_before_the_hide_is_not_hidden),
    ("a stream is measured, not unknown", _stream_is_measured_not_unknown),
    ("a stream closed on hide is one catch-up read", _stream_closed_on_hide_is_one_catch_up_read),
    ("a stream kept while hidden breaks the budget", _stream_kept_while_hidden_breaks_the_budget),
    ("startPoll keeps the budget", _keeps_the_budget),
    ("a setInterval poll breaks it", _catches_a_set_interval_poll),
    ("a busy-only poll reads nothing while idle", _busy_only_poll_is_silent_when_idle),
    ("a two-wave boot is not the visible minute", _second_boot_wave_is_not_visible),
)


def test_poll_helper_keeps_the_request_budget(
    new_page: Callable[..., AbstractContextManager[Page]], static_server: str
) -> None:
    with cases() as c:
        for name, check in _CHECKS:
            with c.case(name), new_page() as page:
                check(page, static_server)
