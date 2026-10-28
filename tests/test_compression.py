from __future__ import annotations

import asyncio
import zlib
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.compression import StreamSafeGZipMiddleware

BIG = ("fleet web app payload " * 200).encode()  # ~4 KB, compresses well
GZIP = {"Accept-Encoding": "gzip"}


def _client(routes: list[Route | Mount], **options: object) -> TestClient:
    app = Starlette(routes=routes)
    app.add_middleware(StreamSafeGZipMiddleware, **options)
    return TestClient(app)


def _serve(content_type: str, body: bytes = BIG, **headers: str):  # type: ignore[no-untyped-def]
    async def endpoint(request: Request) -> Response:
        return Response(body, media_type=content_type, headers=headers)

    return endpoint


# ------------------------------------------------------------ what compresses


@pytest.mark.parametrize(
    "content_type",
    [
        "text/html",
        "text/javascript",
        "text/css",
        "application/json",
        "image/svg+xml",
        "application/manifest+json",
    ],
)
def test_text_responses_compress_for_a_gzip_client(content_type: str) -> None:
    client = _client([Route("/r", _serve(content_type))])

    response = client.get("/r", headers=GZIP)

    assert response.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers["vary"]
    assert int(response.headers["content-length"]) < len(BIG)
    assert response.content == BIG  # httpx has already decoded it


def test_the_wire_bytes_are_one_gzip_member_of_the_original() -> None:
    sent: list[Message] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        await Response(BIG, media_type="text/html")(scope, receive, send)

    async def run() -> None:
        async def collect(message: Message) -> None:
            sent.append(message)

        async def receive() -> Message:
            return {"type": "http.request"}

        await StreamSafeGZipMiddleware(inner)(_http_scope(), receive, collect)

    asyncio.run(run())

    wire = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert zlib.decompress(wire, 31) == BIG
    start = next(m for m in sent if m["type"] == "http.response.start")
    assert dict(start["headers"])[b"content-length"] == str(len(wire)).encode()


@pytest.mark.parametrize("accept", ["", "identity", "br", "gzip;q=0", "gzip; q=0.0"])
def test_a_client_that_does_not_accept_gzip_gets_identity(accept: str) -> None:
    client = _client([Route("/r", _serve("text/html"))])

    response = client.get("/r", headers={"Accept-Encoding": accept})

    assert "content-encoding" not in response.headers
    assert response.content == BIG


def test_a_body_under_the_minimum_is_left_alone() -> None:
    client = _client([Route("/r", _serve("text/html", b"x" * 999))])

    response = client.get("/r", headers=GZIP)

    assert "content-encoding" not in response.headers


def test_the_minimum_size_and_level_are_overridable() -> None:
    client = _client([Route("/r", _serve("text/html", b"x" * 300))], minimum_size=100)

    assert _client_encoding(client, "/r") == "gzip"


def _client_encoding(client: TestClient, path: str) -> str | None:
    return client.get(path, headers=GZIP).headers.get("content-encoding")


# ----------------------------------------------------------- what never does


@pytest.mark.parametrize(
    "content_type",
    [
        "image/png",
        "image/jpeg",
        "image/webp",
        "video/mp4",
        "audio/mpeg",
        "font/woff2",
        "application/zip",
        "application/pdf",
        "multipart/x-mixed-replace; boundary=frame",
        "text/event-stream",
    ],
)
def test_streams_and_compressed_media_pass_through(content_type: str) -> None:
    client = _client([Route("/r", _serve(content_type))])

    response = client.get("/r", headers=GZIP)

    assert "content-encoding" not in response.headers
    assert response.content == BIG


def test_an_already_encoded_or_no_transform_response_is_not_touched() -> None:
    client = _client(
        [
            Route("/enc", _serve("text/html", **{"Content-Encoding": "br"})),
            Route("/nt", _serve("text/html", **{"Cache-Control": "no-transform"})),
        ]
    )

    assert _client_encoding(client, "/enc") == "br"
    assert _client_encoding(client, "/nt") is None


def test_bypass_paths_are_served_untouched_and_others_still_compress() -> None:
    client = _client(
        [
            Route("/api/cam/live", _serve("application/json")),
            Route("/api/other", _serve("application/json")),
        ],
        bypass_paths=("/api/cam/",),
    )

    assert _client_encoding(client, "/api/cam/live") is None
    assert _client_encoding(client, "/api/other") == "gzip"


def test_a_websocket_scope_reaches_the_app_unwrapped() -> None:
    seen: list[tuple[Scope, Send]] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        seen.append((scope, send))

    async def noop_send(message: Message) -> None:
        raise AssertionError("nothing should be sent")

    async def noop_receive() -> Message:
        raise AssertionError("nothing should be read")

    scope: Scope = {"type": "websocket", "path": "/ws", "headers": []}
    asyncio.run(StreamSafeGZipMiddleware(inner)(scope, noop_receive, noop_send))

    assert seen == [(scope, noop_send)]


def test_a_pathsend_response_is_forwarded_as_sent() -> None:
    sent: list[Message] = []

    async def inner(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"text/html")],
            }
        )
        await send({"type": "http.response.pathsend", "path": "/x"})

    asyncio.run(_drive(StreamSafeGZipMiddleware(inner), sent))

    assert [m["type"] for m in sent] == ["http.response.start", "http.response.pathsend"]
    assert b"content-encoding" not in dict(sent[0]["headers"])


# -------------------------------------------------------- 304 revalidation


def test_a_304_revalidation_still_works_through_the_middleware(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("console.log('fleet');\n" * 200, encoding="utf-8")
    client = _client([Mount("/static", StaticFiles(directory=tmp_path))])

    first = client.get("/static/app.js", headers=GZIP)
    revalidated = client.get(
        "/static/app.js", headers={**GZIP, "If-None-Match": first.headers["etag"]}
    )

    assert first.status_code == 200
    assert first.headers["content-encoding"] == "gzip"
    assert revalidated.status_code == 304
    assert revalidated.content == b""
    assert "content-encoding" not in revalidated.headers
    assert revalidated.headers["etag"] == first.headers["etag"]


# ---------------------------------------------------- streaming immediacy


@pytest.mark.parametrize(
    "content_type",
    [
        "text/event-stream",
        "multipart/x-mixed-replace; boundary=frame",
        "application/x-ndjson",
    ],
)
def test_each_streamed_chunk_is_delivered_before_the_next_is_produced(
    content_type: str,
) -> None:
    """The app yields chunk 2 only after chunk 1 left the middleware.

    A compressor that buffers small writes (Starlette's ``GZipMiddleware`` on
    ``multipart/x-mixed-replace``) never releases chunk 1, so the gate times out.
    """
    first_chunk = b"data: tick 1\n\n"

    async def run() -> list[bytes]:
        released = asyncio.Event()
        wire: list[bytes] = []

        async def endpoint_app(scope: Scope, receive: Receive, send: Send) -> None:
            async def chunks():  # type: ignore[no-untyped-def]
                yield first_chunk
                await asyncio.wait_for(released.wait(), timeout=2)
                yield b"data: tick 2\n\n"

            await StreamingResponse(chunks(), media_type=content_type)(
                scope, receive, send
            )

        async def collect(message: Message) -> None:
            if message["type"] != "http.response.body":
                return
            body = message.get("body", b"")
            if body:
                wire.append(body)
            if _decoded(wire).startswith(first_chunk):
                released.set()

        async def receive() -> Message:
            # StreamingResponse polls this for a disconnect; returning at once
            # would spin it and starve the producer.
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        await StreamSafeGZipMiddleware(endpoint_app)(_http_scope(), receive, collect)
        return wire

    wire = asyncio.run(run())

    assert _decoded(wire) == first_chunk + b"data: tick 2\n\n"


def _decoded(wire: list[bytes]) -> bytes:
    """The bytes a client could read so far, gzip or not."""
    joined = b"".join(wire)
    if joined[:2] == b"\x1f\x8b":
        return zlib.decompressobj(31).decompress(joined)
    return joined


# ------------------------------------------------------------------ helpers


def _http_scope() -> Scope:
    return {
        "type": "http",
        "method": "GET",
        "path": "/r",
        "headers": [(b"accept-encoding", b"gzip")],
    }


async def _drive(app: ASGIApp, sent: list[Message]) -> None:
    async def receive() -> Message:
        return {"type": "http.request"}

    async def collect(message: Message) -> None:
        sent.append(message)

    await app(_http_scope(), receive, collect)
