"""Local preview of `site/` with the same URL rules as Cloudflare Pages.

`python -m http.server` cannot serve /about from about.html, so this stdlib server does:
an extensionless path maps to `<path>.html`, `/` to `index.html`, exact-match lines in
`site/_redirects` redirect, and a miss serves `404.html` with status 404.

It binds loopback by default. `--host` binds one other address instead, such as this
computer's Tailscale address, so a phone on the tailnet can open the preview while nothing
is reachable from the local network or the internet.

    .venv/Scripts/python.exe scripts/site_serve.py [--host 127.0.0.1] [--port 8130]

Vendor-verbatim (manifest key `site_serve`), stdlib-only; needs `site_routes.py` beside it.
"""

from __future__ import annotations

import argparse
import functools
import logging
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

# The URL rules live in the sibling `scripts/site_routes.py`; the repo root on the path finds it
# whether this runs as a script (also under `python -P`) or is imported as `scripts.<name>`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.site_routes import load_redirects, resolve_file  # noqa: E402

SITE_DIR = Path(__file__).resolve().parent.parent / "site"
log = logging.getLogger("serve")


class PreviewHandler(SimpleHTTPRequestHandler):
    """Serves `site/` with pretty URLs, `_redirects` and a 404 page."""

    redirects: dict[str, tuple[str, int]] = {}

    def do_GET(self) -> None:  # noqa: N802 - http.server's method name
        path = urlsplit(self.path).path
        rule = self.redirects.get(path.rstrip("/") or "/")
        if rule:
            self.send_response(rule[1])
            self.send_header("Location", rule[0])
            self.end_headers()
            return
        target = resolve_file(Path(self.directory), path)
        if target is None:
            self.send_page(Path(self.directory) / "404.html", 404)
            return
        self.send_page(target, 200)

    def do_HEAD(self) -> None:  # noqa: N802 - http.server's method name
        self.do_GET()

    def send_page(self, file: Path, status: int) -> None:
        """Send `file` with `status` and a content type guessed from its name."""
        body = file.read_bytes() if file.is_file() else b"Not found"
        self.send_response(status)
        ctype = self.guess_type(str(file))
        # Text is UTF-8 throughout; say so, as Cloudflare Pages does, so clients never guess Latin-1.
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - base-class signature
        log.debug(format, *args)


def make_server(site_dir: Path, host: str, port: int) -> ThreadingHTTPServer:
    """A preview server for `site_dir` bound to `host:port` (port 0 picks a free one)."""
    PreviewHandler.redirects = load_redirects(site_dir)
    handler = functools.partial(PreviewHandler, directory=str(site_dir))
    return ThreadingHTTPServer((host, port), handler)


def main() -> None:
    """Serve `site/` on one address until interrupted."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1", help="address to bind (default 127.0.0.1; a Tailscale address for a phone)")
    parser.add_argument("--port", type=int, default=8130, help="port (default 8130)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    server = make_server(SITE_DIR, args.host, args.port)
    log.info("✅ previewing %s at http://%s:%d/", SITE_DIR, args.host, server.server_address[1])
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("ℹ️ stopped")


if __name__ == "__main__":
    main()
