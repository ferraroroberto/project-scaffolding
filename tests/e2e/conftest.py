"""Session fixtures for the headless e2e regression suite.

`streamlit_app` defaults to a **disposable** instance: if the e2e port is
free it boots a fresh Streamlit against the current code on disk (see
`tests/_streamlit_lifecycle.py`); if the port is already occupied it
*refuses* rather than silently killing or adopting whatever's there — a bare
`pytest tests/e2e` must never touch a process it didn't start. Set
`STREAMLIT_E2E_LIVE=1` to explicitly permit reclaiming (kill + fresh
restart) an occupied port. The check-refuse-log policy itself is the
vendor-verbatim `_e2e_live_guard.py` (issue #191/#194); this fixture owns
only the Streamlit-specific boot/teardown around it. See `CLAUDE.md` ("End-to-
end UI testing" — live-app isolation); reference implementation: `app-
launcher`'s `LAUNCHER_E2E_LIVE` / `tests/e2e/conftest.py`.

`static_server` serves `app/webapp/static` over HTTP for the
vendored-component harnesses (their ESM imports don't run from `file://`).
`pytest-playwright` supplies the `page` fixture.

`playwright` overrides pytest-playwright's own session fixture for one reason:
to start the Node driver from a neutral working directory, so nothing it
spawns can pin this checkout (`_neutral_driver_cwd`, #236).

`pytest_sessionfinish` runs the leaked-browser-helper sweep
(`_browser_sweep.py`, #203) once the whole session — fixtures included — is
torn down, so a run that left a WebKit helper behind cleans up after itself
instead of accumulating orphans that later block `git worktree remove`.

The webapp uses no TLS locally, so no `browser_context_args` override is
needed — unlike a self-signed-cert project, which would add
`ignore_https_errors` here.
"""

from __future__ import annotations

import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from playwright.sync_api import Playwright, sync_playwright

from tests._streamlit_lifecycle import (
    STREAMLIT_E2E_PORT,
    ensure_fresh_streamlit,
    kill_streamlit_on_port,
)
from tests.e2e._browser_sweep import sweep_browser_helpers
from tests.e2e._e2e_live_guard import require_disposable_instance

REPO_ROOT = Path(__file__).resolve().parents[2]
STATIC_DIR = REPO_ROOT / "app" / "webapp" / "static"

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
    `STREAMLIT_E2E_LIVE=1` explicitly opts in to reclaiming it (#191/#194).
    """
    require_disposable_instance(STREAMLIT_E2E_PORT, _E2E_LIVE_ENV)
    base_url = ensure_fresh_streamlit(STREAMLIT_E2E_PORT)
    try:
        yield base_url
    finally:
        kill_streamlit_on_port(STREAMLIT_E2E_PORT)


@contextmanager
def _neutral_driver_cwd() -> Iterator[str]:
    """Run the enclosed block with this process's cwd outside the checkout (#236).

    Everything Playwright spawns inherits a working directory: the Node driver
    takes this process's (`playwright/_impl/_transport.py` passes no `cwd`),
    each browser takes the driver's, and each helper — `WebKitWebProcess`,
    `WebKitGPUProcess`, `WebKitNetworkProcess` — takes the browser's. Run the
    suite from `<repo>-wt-<N>` and that whole tree roots itself in the
    worktree, and **Windows will not delete a directory that is a live
    process's cwd**.

    That would be self-clearing if the helpers ever exited. They do not always:
    a helper killed with its browser (a teardown watchdog's `taskkill /F /T`,
    a hard host kill) can wedge *inside* termination — `ExitStatus` set, so
    `taskkill` answers "no running instance", yet a thread still alive and the
    cwd handle still held. Nothing can reap it, so the directory it pins is
    pinned for good; six empty, undeletable worktrees accumulated on the fleet
    host that way (`home-automation#681`).

    So don't fight the wedge — make it harmless. With the driver started from
    `%TEMP%` no helper ever roots in the checkout, and a wedged one pins a
    directory nobody wants to delete. `gettempdir()` deliberately, **not**
    `mkdtemp()`: a per-run temp directory would become unremovable by the exact
    mechanism this exists to avoid.

    Only the driver's *spawn* needs the neutral cwd — the driver's own working
    directory is fixed at spawn and is what every later `launch()` inherits —
    so this restores the caller's cwd immediately and pytest carries on from
    the checkout as before. `tests/e2e/test_helper_cwd_isolation.py` pins it.
    """
    original = os.getcwd()
    neutral = tempfile.gettempdir()
    os.chdir(neutral)
    try:
        yield neutral
    finally:
        os.chdir(original)


@pytest.fixture(scope="session")
def playwright() -> Iterator[Playwright]:
    """pytest-playwright's session driver, started from a neutral cwd (#236).

    Same fixture name as pytest-playwright's own, so the override is picked up
    automatically without changing a single test. The *only* difference is
    `_neutral_driver_cwd` around the spawn: this repo's e2e suite regularly
    runs from a linked worktree, and a driver started there roots every browser
    and helper it spawns in a directory the run is expected to delete afterwards.
    """
    with _neutral_driver_cwd():
        pw = sync_playwright().start()
    try:
        yield pw
    finally:
        pw.stop()


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


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Sweep browser helpers this run orphaned inside *this* checkout (#203).

    A session hook, not a fixture finalizer: it must run after *every* fixture
    — including pytest-playwright's own session-scoped `browser` — has already
    torn down, or the sweep would be looking at a browser that is still
    legitimately running. Advisory by design: it reports and never changes
    `exitstatus`, because neither an unkillable already-exited zombie nor a
    helper wedged inside termination is a test failure (see `_browser_sweep`
    for why both exist).

    A wedge rooted in *this* checkout is still printed by name: it is the one
    residue nothing can reap, so `git worktree remove` will fail as "busy"
    afterwards and the reader needs to know why (#236). `_neutral_driver_cwd`
    above is what stops this run from creating one.
    """
    result = sweep_browser_helpers(REPO_ROOT)
    print(f"\n{result.summary()}")
    for entry in result.killed:
        print(f"  reclaimed leaked helper: {entry}")
    for entry in result.pinning_scope:
        print(f"  UNREAPABLE, pins this checkout: {entry}")


@pytest.fixture(autouse=True)
def _bound_default_timeouts(page) -> None:
    """Cap every Playwright action + navigation wait to _DEFAULT_TIMEOUT_MS (#61).

    Applied on the page (not context) because this scaffold's tests take the
    pytest-playwright page fixture directly — no custom context.new_page() path.
    """
    page.set_default_timeout(_DEFAULT_TIMEOUT_MS)
    page.set_default_navigation_timeout(_DEFAULT_TIMEOUT_MS)
