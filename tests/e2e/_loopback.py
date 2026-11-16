"""Keep the e2e harness off the host's loopback ephemeral-port pool.

Every TCP connection the browser opens to a local server leaves a TIME_WAIT
entry on its (ephemeral port, server port) pair for minutes. Windows answers a
connect() that lands on such a pair with `net::ERR_ADDRESS_IN_USE` instead of
trying another port, so the more connections a run makes to one server, the
likelier the next page load fails — and a second lane gating on the same host
makes it worse. A fresh browser context per case starts with an empty HTTP
cache, so one gallery load alone cost ~43 connections to the harness server.

Two halves, both importable from a conftest:

* `serving(port, directory)` + `route_served_files(context)` — answer GETs for
  files the harness server would serve straight from disk, inside the browser
  context, so they open no socket at all. Anything else (a POST, a redirect, a
  404, a file that is not there) falls through to the real server, so its
  behaviour is unchanged.
* `pytest_runtest_makereport` + `pytest_terminal_summary` — a failure whose
  text carries `ERR_ADDRESS_IN_USE` is relabelled "PORT POOL EXHAUSTED" and
  listed in its own terminal-summary section, so the gate output names the
  host cause instead of a page failure.
"""

from __future__ import annotations

import mimetypes
import posixpath
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import pytest
from playwright.sync_api import BrowserContext, Request, Route

PORT_POOL_MARKER = "ERR_ADDRESS_IN_USE"
PORT_POOL_HEADLINE = (
    "PORT POOL EXHAUSTED — this is the host running out of loopback ephemeral ports "
    f"({PORT_POOL_MARKER}), not a page failure. Another gate or a recent run is holding "
    "ports in TIME_WAIT; wait a few minutes and re-run rather than debugging the page."
)

# Absolute directory each local harness server serves, keyed by its port.
_SERVED: dict[int, Path] = {}
# How the routed requests resolved this session: answered from disk, or let through to the socket.
STATS = {"from_disk": 0, "to_socket": 0}
_PORT_POOL_FAILURES: list[str] = []


@contextmanager
def serving(port: int, directory: Path) -> Iterator[None]:
    """Declare that the harness server on *port* serves *directory* for the enclosed block."""
    _SERVED[port] = directory.resolve()
    try:
        yield
    finally:
        _SERVED.pop(port, None)


def content_type(path: str) -> str:
    """The Content-Type `SimpleHTTPRequestHandler` would send for *path*."""
    ext = posixpath.splitext(path)[1]
    table = SimpleHTTPRequestHandler.extensions_map
    for key in (ext, ext.lower()):
        if key in table:
            return table[key]
    return mimetypes.guess_type(path)[0] or "application/octet-stream"


def resolve_served_file(url: str) -> Path | None:
    """The on-disk file a declared harness server would serve for *url*, else None."""
    parts = urlsplit(url)
    root = _SERVED.get(parts.port or -1)
    if root is None or parts.hostname not in ("127.0.0.1", "localhost"):
        return None
    candidate = (root / unquote(parts.path).lstrip("/\\")).resolve()
    if candidate.is_file() and candidate.is_relative_to(root):
        return candidate
    return None


def _handle(route: Route, request: Request) -> None:
    target = resolve_served_file(request.url) if request.method == "GET" else None
    if target is None:
        STATS["to_socket"] += 1
        route.fallback()
        return
    STATS["from_disk"] += 1
    route.fulfill(status=200, headers={"Content-Type": content_type(str(target))}, body=target.read_bytes())


def route_served_files(context: BrowserContext) -> None:
    """Answer declared harness servers' static GETs inside *context* without a socket."""
    context.route(lambda url: urlsplit(url).port in _SERVED, _handle)


def is_port_pool_failure(text: str) -> bool:
    return PORT_POOL_MARKER in text


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    """Relabel a report that failed on `ERR_ADDRESS_IN_USE` so its first line names the host."""
    report: Any = yield
    if report.failed and is_port_pool_failure(report.longreprtext):
        report.longrepr = f"{PORT_POOL_HEADLINE}\n\n{report.longreprtext}"
        _PORT_POOL_FAILURES.append(report.nodeid)
    return report


def pytest_terminal_summary(terminalreporter: Any) -> None:
    """Print the port-pool section, and how many requests were kept off the socket."""
    total = STATS["from_disk"] + STATS["to_socket"]
    if total:
        terminalreporter.write_line(
            f"loopback: {STATS['from_disk']} of {total} routed requests answered from disk, "
            f"{STATS['to_socket']} went to the socket"
        )
    if _PORT_POOL_FAILURES:
        terminalreporter.write_sep("=", "PORT POOL EXHAUSTED", red=True, bold=True)
        terminalreporter.write_line(PORT_POOL_HEADLINE)
        for nodeid in dict.fromkeys(_PORT_POOL_FAILURES):
            terminalreporter.write_line(f"  {nodeid}")
