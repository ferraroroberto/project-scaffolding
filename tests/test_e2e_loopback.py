"""Unit coverage for the e2e loopback helper: disk resolution and the port-pool report.

The browser half (a real context answering a GET from disk) is a case in
`tests/e2e/test_harness_helpers.py`; everything here is pure or runs a child
pytest, so it needs no browser.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW
from tests.e2e import _loopback

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def served(tmp_path: Path):  # noqa: ANN201 — yields the served root
    (tmp_path / "sub").mkdir()
    (tmp_path / "index.html").write_text("<p>hi</p>", encoding="utf-8")
    (tmp_path / "sub" / "app.js").write_text("export {};", encoding="utf-8")
    with _loopback.serving(51234, tmp_path):
        yield tmp_path


def test_a_declared_servers_existing_file_resolves_to_disk(served: Path) -> None:
    assert _loopback.resolve_served_file("http://127.0.0.1:51234/sub/app.js?v=3") == (served / "sub" / "app.js").resolve()


def test_url_escapes_are_decoded_before_the_lookup(served: Path) -> None:
    assert _loopback.resolve_served_file("http://127.0.0.1:51234/sub%2Fapp.js") == (served / "sub" / "app.js").resolve()


@pytest.mark.parametrize(
    "url",
    [
        pytest.param("http://127.0.0.1:51234/missing.html", id="absent-file"),
        pytest.param("http://127.0.0.1:51234/sub", id="directory-is-the-servers-redirect"),
        pytest.param("http://127.0.0.1:51234/", id="root-is-the-servers-index-or-listing"),
        pytest.param("http://127.0.0.1:51234/../conftest.py", id="dot-dot"),
        pytest.param("http://127.0.0.1:51234/%2e%2e/%2e%2e/etc/passwd", id="encoded-dot-dot"),
        pytest.param("http://127.0.0.1:51234/C:/Windows/win.ini", id="drive-letter"),
        pytest.param("http://127.0.0.1:51999/index.html", id="undeclared-port"),
        pytest.param("http://example.com:51234/index.html", id="foreign-host"),
        pytest.param("http://127.0.0.1/index.html", id="no-port"),
    ],
)
def test_everything_else_falls_through_to_the_real_server(served: Path, url: str) -> None:
    assert _loopback.resolve_served_file(url) is None


def test_a_server_that_stopped_serving_is_no_longer_resolved(tmp_path: Path) -> None:
    (tmp_path / "a.html").write_text("x", encoding="utf-8")
    with _loopback.serving(51235, tmp_path):
        assert _loopback.resolve_served_file("http://127.0.0.1:51235/a.html") is not None
    assert _loopback.resolve_served_file("http://127.0.0.1:51235/a.html") is None


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("a.js", "text/javascript"),
        ("a.mjs", "text/javascript"),
        ("a.css", "text/css"),
        ("a.html", "text/html"),
        ("a.svg", "image/svg+xml"),
        ("A.JS", "text/javascript"),
        ("a.unknownext", "application/octet-stream"),
    ],
)
def test_content_type_matches_what_the_stdlib_server_sends(name: str, expected: str) -> None:
    assert _loopback.content_type(name) == expected


def test_failure_text_naming_the_port_error_is_recognised() -> None:
    assert _loopback.is_port_pool_failure("Page.goto: net::ERR_ADDRESS_IN_USE at http://127.0.0.1:1/")
    assert not _loopback.is_port_pool_failure("Page.goto: net::ERR_CONNECTION_REFUSED at http://127.0.0.1:1/")


def test_a_port_error_failure_is_reported_as_port_pool_exhaustion(tmp_path: Path) -> None:
    """A child pytest: the failing test's report leads with the headline, and the summary lists its node."""
    (tmp_path / "conftest.py").write_text(
        "from tests.e2e._loopback import pytest_runtest_makereport, pytest_terminal_summary  # noqa: F401\n",
        encoding="utf-8",
    )
    (tmp_path / "test_child.py").write_text(
        "def test_port():\n    raise RuntimeError('Page.goto: net::ERR_ADDRESS_IN_USE at http://127.0.0.1:9/')\n\n"
        "def test_other():\n    raise RuntimeError('Page.goto: net::ERR_CONNECTION_REFUSED')\n",
        encoding="utf-8",
    )
    env = {"PYTHONPATH": str(REPO_ROOT), "PYTHONUTF8": "1", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--rootdir", str(tmp_path), str(tmp_path)],
        capture_output=True, text=True, cwd=tmp_path, env=env, timeout=120, check=False, creationflags=NO_WINDOW,
    )
    out = result.stdout
    assert result.returncode == 1, out
    assert out.count(_loopback.PORT_POOL_HEADLINE) == 2, "headline leads the failing report and the summary section"
    section = out.split("= PORT POOL EXHAUSTED =", 1)[1].split("\n=", 1)[0]
    assert "test_child.py::test_port" in section
    assert "test_other" not in section
