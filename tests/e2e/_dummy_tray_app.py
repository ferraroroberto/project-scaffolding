"""Throwaway dummy tray-owned service for test_tray_lifecycle_behavior.py.

Not a test itself -- a tiny stdlib HTTP(S) server shaped like every fleet PWA's
build-identity surface (CLAUDE.md "Webapp PWA required surfaces"): a
``/api/version`` endpoint reporting a ``git_sha`` captured once at process
startup, plus a ``/health`` endpoint. It exists so the e2e harness can drive
the REAL ``app/tray/tray_lifecycle.ps1`` through a real detect -> kill ->
reclaim -> start -> verify process lifecycle, exactly like a real app's
``launcher.py`` would be driven by a real ``tray.bat``.

Always launched as a subprocess (via ``Start-Process`` inside the helper),
never imported. The git_sha is read fresh from the working directory's git
HEAD at startup -- so a process started before a new commit keeps reporting
the old sha until it is actually killed and relaunched. That is the exact
signal the harness uses to prove `--restart` doesn't silently adopt a stale
build (project-scaffolding#144).
"""

from __future__ import annotations

import argparse
import json
import ssl
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0


def _git_head(cwd: str) -> str:
    """The git HEAD sha of ``cwd``, captured once -- same convention every
    fleet PWA uses for its build-identity footer (git rev-parse at module
    load, never re-read per request)."""
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=cwd,
        text=True,
        creationflags=_NO_WINDOW,
    ).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--https", action="store_true")
    parser.add_argument("--cert")
    parser.add_argument("--key")
    args = parser.parse_args()

    git_sha = _git_head(".")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:  # quiet -- no console anyway
            pass

        def do_GET(self) -> None:  # noqa: N802 -- stdlib-mandated name
            if self.path == "/api/version":
                body = json.dumps({"git_sha": git_sha}).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/health":
                self.send_response(200)
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    if args.https:
        if not args.cert or not args.key:
            raise SystemExit("--https requires --cert and --key")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=args.cert, keyfile=args.key)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)

    server.serve_forever()


if __name__ == "__main__":
    main()
