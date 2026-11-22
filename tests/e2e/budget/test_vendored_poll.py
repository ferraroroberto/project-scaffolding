"""The vendored `poll` helper keeps the request budget, and the probe catches a page that does not.

The probe page is answered by a Playwright route (it is not a file in the tree)
and imports the real `poll.js` from the static server. The API is a route too,
so every request is counted without a server.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

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


def _probe(page: Page, base_url: str, script: str) -> str:
    html = f"<!doctype html><html><body><script type=\"module\">{script}</script></body></html>"

    def answer_page(route: Route) -> None:
        route.fulfill(status=200, content_type="text/html", body=html)

    def answer_api(route: Route) -> None:
        route.fulfill(status=200, content_type="application/json", body="{}")

    page.route(f"**{_PAGE}", answer_page)
    page.route("**/api/**", answer_api)
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


_CHECKS = (
    ("startPoll keeps the budget", _keeps_the_budget),
    ("a setInterval poll breaks it", _catches_a_set_interval_poll),
    ("a busy-only poll reads nothing while idle", _busy_only_poll_is_silent_when_idle),
)


def test_poll_helper_keeps_the_request_budget(
    new_page: Callable[..., AbstractContextManager[Page]], static_server: str
) -> None:
    with cases() as c:
        for name, check in _CHECKS:
            with c.case(name), new_page() as page:
                check(page, static_server)
