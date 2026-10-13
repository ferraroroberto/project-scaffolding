"""usage-log end to end (#349): the gallery's view switch and `data-track` tap
reach the real router and read back through `GET /api/usage/summary`.

The gallery is served here by a FastAPI app carrying the vendored router
(`src/usage_log.py`) over a throwaway database, not by the plain
`static_server` the other harnesses use: a static server cannot accept the
POST, which is exactly the silent-failure path the client must survive there.

The run also pins the privacy contract's network half: every request the page
makes stays on the app's own origin.
"""

from __future__ import annotations

import socket
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.staticfiles import StaticFiles
from playwright.sync_api import Browser, Page, Response

from src.usage_log import usage_router
from tests.e2e.conftest import STATIC_DIR

_BOOT_TIMEOUT_S = 10.0


@contextmanager
def _serve(app: FastAPI) -> Iterator[str]:
    """Run `app` on an ephemeral loopback port; yields its base URL."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    # Selector loop pinned, as at every uvicorn spawn point (CLAUDE.md,
    # "Windows event-loop pinning"); lifespan off -- the app has none.
    config = uvicorn.Config(app, loop="asyncio:SelectorEventLoop", lifespan="off",
                            log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + _BOOT_TIMEOUT_S
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError(f"usage-log test server did not start within {_BOOT_TIMEOUT_S}s")
        time.sleep(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


@pytest.fixture(scope="module")
def usage_app(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path]]:
    """Serve the static tree + the usage router on an ephemeral loopback port."""
    db = tmp_path_factory.mktemp("usage") / "usage.sqlite3"
    app = FastAPI()
    app.include_router(usage_router(db))
    app.mount("/", StaticFiles(directory=STATIC_DIR))
    with _serve(app) as base:
        yield base, db


@pytest.fixture
def token_app(tmp_path: Path) -> Iterator[tuple[str, list[str]]]:
    """The router behind a token check (the shape of an app whose API is
    bearer-gated for off-loopback callers); yields the base URL and every token
    the server accepted, in order. A request without a `tok-…` header is a 401."""
    accepted: list[str] = []

    def require_token(x_usage_token: str | None = Header(default=None)) -> None:
        if not x_usage_token or not x_usage_token.startswith("tok-"):
            raise HTTPException(status_code=401)
        accepted.append(x_usage_token)

    app = FastAPI()
    app.include_router(usage_router(tmp_path / "usage.sqlite3",
                                    dependencies=[Depends(require_token)]))
    app.mount("/", StaticFiles(directory=STATIC_DIR))
    with _serve(app) as base:
        yield base, accepted


# Counts navigator.sendBeacon calls without replacing it, so a test can tell
# which transport the page-hide send used.
_COUNT_BEACONS = """
window.__beacons = 0;
const realBeacon = navigator.sendBeacon.bind(navigator);
navigator.sendBeacon = (...args) => { window.__beacons += 1; return realBeacon(...args); };
"""


def _is_events_post(base: str, resp: Response) -> bool:
    return resp.url == f"{base}/api/usage/events" and resp.request.method == "POST"


def _open_with_headers(page: Page, base: str) -> None:
    """Start a logger whose `headers` function reads `window.token` per send."""
    page.add_init_script(_COUNT_BEACONS)
    page.goto(f"{base}/_vendored/usage-log/usage-log.js")
    page.evaluate("""async () => {
        const { initUsageLog } = await import('/_vendored/usage-log/usage-log.js');
        window.token = 'tok-1';
        window.usage = initUsageLog({ headers: () => ({ 'X-Usage-Token': window.token }) });
        window.usage.trackView('overview');
    }""")


def test_headers_option_reaches_the_normal_send(
    token_app: tuple[str, list[str]], page: Page
) -> None:
    base, accepted = token_app
    _open_with_headers(page, base)
    with page.expect_response(lambda r: _is_events_post(base, r)) as sent:
        page.evaluate("window.usage.flush()")
    assert sent.value.status == 200, sent.value.text()
    assert accepted == ["tok-1"]


def test_headers_option_reaches_the_page_hide_send_as_a_keepalive_fetch(
    token_app: tuple[str, list[str]], page: Page
) -> None:
    base, accepted = token_app
    _open_with_headers(page, base)
    # Rotated after init: a function is read per send, not once.
    page.evaluate("window.token = 'tok-2'")
    with page.expect_response(lambda r: _is_events_post(base, r)) as sent:
        page.evaluate("window.dispatchEvent(new Event('pagehide'))")
    assert sent.value.status == 200, sent.value.text()
    assert accepted == ["tok-2"]
    assert page.evaluate("window.__beacons") == 0


def test_without_headers_the_page_hide_send_is_still_a_beacon(
    token_app: tuple[str, list[str]], page: Page
) -> None:
    base, accepted = token_app
    page.add_init_script(_COUNT_BEACONS)
    page.goto(f"{base}/_vendored/usage-log/usage-log.js")
    page.evaluate("""async () => {
        const { initUsageLog } = await import('/_vendored/usage-log/usage-log.js');
        window.usage = initUsageLog();
        window.usage.trackView('overview');
        window.dispatchEvent(new Event('pagehide'));
    }""")
    assert page.evaluate("window.__beacons") == 1


def _drive(page: Page, base: str) -> list[str]:
    """Load the gallery, switch view, tap the tracked control, flush; returns
    every URL the page requested."""
    requested: list[str] = []
    page.on("request", lambda req: requested.append(req.url))
    page.goto(f"{base}/_vendored/demo.html")
    page.wait_for_selector("body[data-usage-ready='1']")
    page.click("#demoUsageViews [data-view='history']")
    page.click("#demoUsageTap")
    with page.expect_response(
        lambda r: r.url == f"{base}/api/usage/events" and r.request.method == "POST"
    ) as posted:
        page.evaluate("window.demoUsage.flush()")
    assert posted.value.status == 200, posted.value.text()
    assert posted.value.json() == {"accepted": 4, "rejected": 0}
    return requested


def test_view_switch_and_tracked_tap_reach_the_summary(
    usage_app: tuple[str, Path], page: Page, browser: Browser
) -> None:
    base, db = usage_app

    requested = _drive(page, base)
    off_origin = [u for u in requested if not u.startswith(base + "/") and not u.startswith("data:")]
    assert off_origin == [], f"the page requested another origin: {off_origin}"

    summary = page.request.get(f"{base}/api/usage/summary?days=1").json()
    assert summary["views"] == {"history": 1, "overview": 1}
    assert summary["controls"] == {"demo-refresh": 1}
    assert summary["sessions"] == 1
    assert summary["devices"] == {"desktop": 1}

    # The tap carries the view it happened on.
    conn = sqlite3.connect(db)
    try:
        taps = conn.execute("SELECT view_id, control_id FROM events WHERE kind = 'tap'").fetchall()
    finally:
        conn.close()
    assert taps == [("history", "demo-refresh")]

    # A phone visit is a separate session in the phone column.
    context = browser.new_context(viewport={"width": 390, "height": 844},
                                  has_touch=True, is_mobile=True)
    try:
        _drive(context.new_page(), base)
    finally:
        context.close()
    summary = page.request.get(f"{base}/api/usage/summary?days=1").json()
    assert summary["sessions"] == 2
    assert summary["devices"] == {"desktop": 1, "phone": 1}
    assert summary["views"] == {"history": 2, "overview": 2}
