"""ASGI app the launch module (app/webapp/serve.py) is proven against, as a real subprocess.

One route per behaviour a fleet app depends on surviving the switch to HTTP/2:
plain, gzip, a bearer gate, server-sent events held open on the client, a
websocket echo, the client address the proxy trust resolves, and a response the
client can abandon mid-send. The lifespan writes ``SERVE_TEST_MARK`` on shutdown
so a test can tell a graceful stop from a kill.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.websockets import WebSocket

from src.compression import StreamSafeGZipMiddleware

TOKEN = "fleet-test-token"
BIG = ("fleet web app payload " * 200).encode()
RELEASE = asyncio.Event()
STATS = {"hang_started": 0, "hang_ended": 0}


async def plain(request: Request) -> Response:
    return PlainTextResponse("ok")


async def big(request: Request) -> Response:
    return Response(BIG, media_type="text/html")


async def secure(request: Request) -> Response:
    return JSONResponse({"secret": True})


async def client(request: Request) -> Response:
    return JSONResponse({"host": request.client.host if request.client else None})


async def release(request: Request) -> Response:
    RELEASE.set()
    return PlainTextResponse("released")


async def stats(request: Request) -> Response:
    return JSONResponse(STATS)


async def sse(request: Request) -> Response:
    """Two events; the second leaves only after /release, so a buffering server shows."""

    async def events() -> AsyncIterator[bytes]:
        yield b"data: first\n\n"
        await asyncio.wait_for(RELEASE.wait(), timeout=20)
        yield b"data: second\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


class Hang:
    """An endless body that stops as soon as it sees the client go. A server that never
    wakes the send it is parked in never lets it see that, so the call never ends."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        STATS["hang_started"] += 1
        gone = asyncio.Event()

        async def watch_for_disconnect() -> None:
            while (await receive())["type"] != "http.disconnect":
                pass
            gone.set()

        watcher = asyncio.create_task(watch_for_disconnect())
        try:
            await send({"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/octet-stream")]})
            while not gone.is_set():
                await send({"type": "http.response.body", "body": b"x" * 65536, "more_body": True})
                await asyncio.sleep(0)
        finally:
            watcher.cancel()
            STATS["hang_ended"] += 1


async def echo(ws: WebSocket) -> None:
    await ws.accept()
    try:
        while True:
            await ws.send_text(f"echo:{await ws.receive_text()}")
    except Exception:
        return


class BearerGate:
    """Pure-ASGI bearer check on /secure, the shape the fleet's gates take."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] == "/secure":
            headers = dict(scope["headers"])
            if headers.get(b"authorization") != f"Bearer {TOKEN}".encode():
                await PlainTextResponse("no", status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


@asynccontextmanager
async def lifespan(_app: Starlette) -> AsyncIterator[None]:
    yield
    mark = os.environ.get("SERVE_TEST_MARK")
    if mark:
        Path(mark).write_text("lifespan-shutdown", encoding="utf-8")


app = Starlette(
    routes=[
        Route("/plain", plain),
        Route("/big", big),
        Route("/secure", secure),
        Route("/client", client),
        Route("/release", release),
        Route("/stats", stats),
        Route("/sse", sse),
        Route("/hang", Hang()),
        WebSocketRoute("/ws", echo),
    ],
    lifespan=lifespan,
)
app.add_middleware(BearerGate)
app.add_middleware(StreamSafeGZipMiddleware)
