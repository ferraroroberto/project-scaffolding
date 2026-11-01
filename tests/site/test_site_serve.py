"""The preview server answers like the static host: pretty URLs, redirects, a 404 page, UTF-8 text."""

from __future__ import annotations

import http.client
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from scripts import site_serve


@pytest.fixture
def server(tmp_path: Path) -> Iterator[int]:
    for rel, text in {"index.html": "home", "about.html": "about", "404.html": "gone", "css/a.css": "a{}",
                      "_redirects": "/old /about 301\n"}.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    srv = site_serve.make_server(tmp_path, "127.0.0.1", 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield srv.server_address[1]
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)


def fetch(port: int, path: str, method: str = "GET") -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request(method, path)
        resp = conn.getresponse()
        return resp.status, dict(resp.getheaders()), resp.read()
    finally:
        conn.close()


def test_pretty_urls_redirects_and_404(server: int) -> None:
    assert fetch(server, "/")[::2] == (200, b"home")
    status, headers, body = fetch(server, "/about")
    assert (status, body) == (200, b"about")
    assert headers["Content-Type"] == "text/html; charset=utf-8"
    status, headers, _ = fetch(server, "/old/")
    assert (status, headers["Location"]) == (301, "/about")
    assert fetch(server, "/nowhere")[::2] == (404, b"gone")
    assert fetch(server, "/css/a.css")[1]["Content-Type"] == "text/css; charset=utf-8"


def test_head_sends_headers_without_a_body(server: int) -> None:
    status, headers, body = fetch(server, "/about", "HEAD")
    assert (status, headers["Content-Length"], body) == (200, "5", b"")
