"""Tiny stdlib webapp the resource soak is proven against.

``python soak_app.py <mode>`` serves two poll routes on a free loopback port and
prints ``PORT=<n>``. ``clean`` answers and keeps nothing; ``threads`` parks a new
thread per request; ``handles`` opens a file per request and never closes it.
"""

from __future__ import annotations

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODE = sys.argv[1] if len(sys.argv) > 1 else "clean"
_PARKED = threading.Event()  # never set: a parked thread lives until the process dies
_OPEN_FILES: list[object] = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server's required name
        if self.path == "/missing":
            self.send_error(404)
            return
        if MODE == "threads":
            threading.Thread(target=_PARKED.wait, daemon=True).start()
        elif MODE == "handles":
            _OPEN_FILES.append(open(os.devnull, "rb"))  # noqa: SIM115 - the leak is the point
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    sys.stdout.write(f"PORT={server.server_address[1]}\n")
    sys.stdout.flush()
    server.serve_forever()
