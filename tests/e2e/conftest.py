"""Session fixtures for the headless e2e regression suite.

`streamlit_app` defaults to a **disposable** instance: if the e2e port is
free it boots a fresh Streamlit against the current code on disk (see
`tests/_streamlit_lifecycle.py`); if the port is already occupied it
*refuses* rather than silently killing or adopting whatever's there — a bare
`pytest tests/e2e` must never touch a process it didn't start. Set
`STREAMLIT_E2E_LIVE=1` to explicitly permit reclaiming (kill + fresh
restart) an occupied port. See `CLAUDE.md` ("End-to-end UI testing" —
live-app isolation) and `project-scaffolding#191`; reference implementation:
`app-launcher`'s `LAUNCHER_E2E_LIVE` / `tests/e2e/conftest.py`.

`static_server` serves `app/webapp/static` over HTTP for the
vendored-component harnesses (their ESM imports don't run from `file://`).
`pytest-playwright` supplies the `page` fixture.

The webapp uses no TLS locally, so no `browser_context_args` override is
needed — unlike a self-signed-cert project, which would add
`ignore_https_errors` here.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from tests._streamlit_lifecycle import (
    STREAMLIT_E2E_PORT,
    ensure_fresh_streamlit,
    kill_streamlit_on_port,
    port_is_in_use,
)

STATIC_DIR = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static"

# Explicit bounded default for Playwright action + navigation waits (#61).
# Playwright's implicit 30 s stacks into opaque multi-minute hangs under
# pytest-timeout; 15 s fails fast with a TimeoutError that names the locator.
# Widen for slow CI runners via E2E_DEFAULT_TIMEOUT_MS without a code change.
_DEFAULT_TIMEOUT_MS = int(os.environ.get("E2E_DEFAULT_TIMEOUT_MS", "15000"))

# Opt-in to reclaiming an already-occupied e2e port (#191). Loudly named and
# opt-IN on purpose — the inverted opt-OUT shape (forgetting a flag silently
# adopts a live app) is exactly the footgun this convention exists to avoid.
_E2E_LIVE_ENV = "STREAMLIT_E2E_LIVE"


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:  # noqa: D102 — silence per-request stderr noise
        pass


@pytest.fixture(scope="session")
def streamlit_app() -> Iterator[str]:
    """Boot a disposable Streamlit for the whole pytest session; kill it after.

    Refuses (does not kill or adopt) an occupied e2e port unless
    `STREAMLIT_E2E_LIVE=1` explicitly opts in to reclaiming it (#191).
    """
    live_opt_in = os.environ.get(_E2E_LIVE_ENV) == "1"
    if port_is_in_use(STREAMLIT_E2E_PORT) and not live_opt_in:
        pytest.exit(
            f"Refusing to touch the process already listening on "
            f":{STREAMLIT_E2E_PORT} - a bare e2e run must not silently kill "
            f"or adopt it. Set {_E2E_LIVE_ENV}=1 to explicitly allow "
            "reclaiming this port (kill + fresh restart), or free the port "
            "yourself first.",
            returncode=2,
        )
    if live_opt_in:
        print(f"[e2e] {_E2E_LIVE_ENV}=1 - reclaiming :{STREAMLIT_E2E_PORT}")
    else:
        print(f"[e2e] booting disposable Streamlit on :{STREAMLIT_E2E_PORT}")
    base_url = ensure_fresh_streamlit(STREAMLIT_E2E_PORT)
    try:
        yield base_url
    finally:
        kill_streamlit_on_port(STREAMLIT_E2E_PORT)


@contextmanager
def serve_directory(directory: Path) -> Iterator[str]:
    """Serve *directory* over loopback HTTP on an ephemeral port.

    Shared by `static_server` and any test module that needs its own tree
    served (e.g. the geometry-helper fixtures under `tests/e2e/_fixtures/`).
    """
    handler = partial(_QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def static_server() -> Iterator[str]:
    """Serve app/webapp/static over HTTP on an ephemeral port for the session."""
    with serve_directory(STATIC_DIR) as base_url:
        yield base_url


@pytest.fixture(autouse=True)
def _bound_default_timeouts(page) -> None:
    """Cap every Playwright action + navigation wait to _DEFAULT_TIMEOUT_MS (#61).

    Applied on the page (not context) because this scaffold's tests take the
    pytest-playwright page fixture directly — no custom context.new_page() path.
    """
    page.set_default_timeout(_DEFAULT_TIMEOUT_MS)
    page.set_default_navigation_timeout(_DEFAULT_TIMEOUT_MS)
