"""The HTTP/2 launch module (`app/webapp/serve.py`), proven as the real process.

The unit half pins the config and the argument handling. The rest boots
``python -m app.webapp.serve`` against `tests/fixtures/serve_app.py` over a
throwaway TLS cert, for both servers, and drives it as a client would: ALPN,
gzip, the bearer gate, server-sent events that must leave before the stream
ends, a websocket, the proxy-header trust, a graceful stop, and an abandoned
HTTP/2 response that must not leak its ASGI call.
"""

from __future__ import annotations

import asyncio
import datetime
import ipaddress
import os
import signal
import socket
import ssl
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from wsproto import ConnectionType, WSConnection
from wsproto.events import AcceptConnection, Message, Request, TextMessage

from app.webapp import serve
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_APP = "tests.fixtures.serve_app:app"
TOKEN = "fleet-test-token"
SERVERS = [serve.HYPERCORN, serve.UVICORN]
BOOT_TIMEOUT_S = 20.0
BIG = ("fleet web app payload " * 200).encode()  # what /big serves


# ----------------------------------------------------------------- unit half


def test_hypercorn_config_offers_h2_only_with_tls() -> None:
    tls = serve.build_config("0.0.0.0", 8450, "c.pem", "k.pem", "info")
    assert tls.bind == ["0.0.0.0:8450"]
    assert tls.alpn_protocols == ["h2", "http/1.1"]
    assert tls.certfile == "c.pem" and tls.keyfile == "k.pem"
    assert tls.websocket_ping_interval == serve.WS_PING_INTERVAL_S
    assert tls.loglevel == "INFO"

    plain = serve.build_config("127.0.0.1", 8450)
    assert plain.certfile is None and plain.keyfile is None  # no TLS handshake, so no ALPN: HTTP/1.1


def test_uvicorn_fallback_config_keeps_tls_ping_and_leaves_proxy_trust_to_wrap_app() -> None:
    cfg = serve.build_uvicorn_config(object(), "127.0.0.1", 8450, "c.pem", "k.pem", "INFO")
    assert (cfg.ssl_certfile, cfg.ssl_keyfile) == ("c.pem", "k.pem")
    assert cfg.ws_ping_interval == serve.WS_PING_INTERVAL_S
    assert cfg.proxy_headers is False
    assert cfg.log_level == "info"


def test_load_attr_resolves_module_and_dotted_attr_and_rejects_a_bad_form() -> None:
    assert serve.load_attr("app.webapp.serve:selector_loop_factory") is serve.selector_loop_factory
    assert serve.load_attr("os:path.join") is os.path.join
    for bad in ("nocolon", ":attr", "mod:"):
        with pytest.raises(ValueError, match="package.module:attribute"):
            serve.load_attr(bad)


def test_selector_loop_factory_returns_an_instantiated_loop() -> None:
    import asyncio

    loop = serve.selector_loop_factory()
    try:
        assert isinstance(loop, asyncio.AbstractEventLoop)
        if sys.platform == "win32":
            assert isinstance(loop, asyncio.SelectorEventLoop)
    finally:
        loop.close()


def test_unknown_server_is_refused_before_anything_binds() -> None:
    with pytest.raises(ValueError, match="unknown server"):
        serve.run("127.0.0.1", 1, server="gunicorn")


def test_missing_hypercorn_is_a_distinct_error_naming_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise ImportError("No module named 'hypercorn'")

    monkeypatch.setattr(serve, "build_config", boom)
    with pytest.raises(RuntimeError, match=r"pip install -r requirements.txt.*--server uvicorn"):
        serve.run("127.0.0.1", 1, server=serve.HYPERCORN)


def test_h2_stream_release_closes_unsent_buffers_on_closed_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio
    from types import SimpleNamespace

    from hypercorn.events import Closed, RawData
    from hypercorn.protocol.h2 import H2Protocol

    seen: list[object] = []

    async def fake_handle(self: object, event: object) -> None:
        seen.append(event)

    class Buffer:
        closed = False

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(H2Protocol, "handle", fake_handle)  # restored after the test
    serve.release_h2_streams_on_disconnect()
    patched = H2Protocol.handle
    serve.release_h2_streams_on_disconnect()
    assert H2Protocol.handle is patched  # a second call never wraps the wrapper

    stub = SimpleNamespace(stream_buffers={1: Buffer(), 3: Buffer()})
    asyncio.run(H2Protocol.handle(stub, RawData(data=b"")))  # type: ignore[arg-type]
    assert not any(b.closed for b in stub.stream_buffers.values())
    asyncio.run(H2Protocol.handle(stub, Closed()))  # type: ignore[arg-type]
    assert all(b.closed for b in stub.stream_buffers.values())
    assert len(seen) == 2  # the original handler still ran for both events


def test_wrap_app_trusts_forwarded_for_from_loopback_only() -> None:
    wrapped = serve.wrap_app(object())
    assert wrapped.trusted_hosts is not None
    assert "127.0.0.1" in wrapped.trusted_hosts
    assert "0.0.0.0" not in wrapped.trusted_hosts


async def _unanswered_h2_requests(total: int, batch: int) -> list[int]:
    """Serve over h2c with the launch config and send ``total`` requests on one
    connection, ``batch`` in flight at a time; the streams that never got an answer."""
    import h2.config
    import h2.connection
    import h2.events
    from hypercorn.asyncio import serve as hypercorn_serve

    async def app(scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    port = _free_port()
    stop = asyncio.Event()
    server = asyncio.create_task(
        hypercorn_serve(app, serve.build_config("127.0.0.1", port), shutdown_trigger=stop.wait)
    )
    try:
        for _ in range(100):
            try:
                reader, writer = await asyncio.open_connection("127.0.0.1", port)
                break
            except OSError:
                await asyncio.sleep(0.05)
        else:
            raise AssertionError("hypercorn never listened")
        conn = h2.connection.H2Connection(h2.config.H2Configuration(client_side=True))
        conn.initiate_connection()
        sent = 0
        while sent < total:
            pending: set[int] = set()
            for _ in range(min(batch, total - sent)):
                stream_id = conn.get_next_available_stream_id()
                conn.send_headers(
                    stream_id,
                    [(":method", "GET"), (":path", f"/{sent}"), (":scheme", "http"), (":authority", "t")],
                    end_stream=True,
                )
                pending.add(stream_id)
                sent += 1
            writer.write(conn.data_to_send())
            await writer.drain()
            while pending:
                try:
                    # A healthy answer takes milliseconds; the stall is the 5 s keep-alive.
                    data = await asyncio.wait_for(reader.read(65_536), 2)
                except TimeoutError:
                    return sorted(pending)
                if not data:
                    return sorted(pending)
                for event in conn.receive_data(data):
                    if isinstance(event, h2.events.StreamEnded):
                        pending.discard(event.stream_id)
                writer.write(conn.data_to_send())
        writer.close()
        return []
    finally:
        stop.set()
        server.cancel()
        try:
            await server
        except BaseException:
            pass


def test_every_request_on_a_long_lived_h2_connection_is_answered() -> None:
    """A page opened late in a browser session shares the connection every earlier page
    booted over. Past hypercorn's default per-connection request cap, the requests in
    flight must still be answered at once, not left for the keep-alive timer to drop."""
    from hypercorn.config import Config

    total = Config.keep_alive_max_requests + 200
    assert asyncio.run(_unanswered_h2_requests(total, batch=20)) == []


# ------------------------------------------------------------ process half


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def tls_files(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """A throwaway self-signed leaf for 127.0.0.1; the test client trusts exactly it."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .sign(key, hashes.SHA256())
    )
    folder = tmp_path_factory.mktemp("tls")
    cert_path, key_path = folder / "cert.pem", folder / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


class Booted:
    def __init__(self, server: str, proc: subprocess.Popen[bytes], port: int, cert: Path | None, log: Path) -> None:
        self.server, self.proc, self.port, self.cert, self.log = server, proc, port, cert, log

    @property
    def speaks_h2(self) -> bool:
        return self.server == serve.HYPERCORN and self.cert is not None

    @property
    def scheme(self) -> str:
        return "https" if self.cert else "http"

    def context(self, alpn: list[str]) -> ssl.SSLContext:
        assert self.cert is not None
        ctx = ssl.create_default_context(cafile=str(self.cert))
        ctx.set_alpn_protocols(alpn)
        return ctx

    def client(self, http2: bool) -> httpx.Client:
        verify: Any = self.context(["h2", "http/1.1"] if http2 else ["http/1.1"]) if self.cert else True
        return httpx.Client(
            base_url=f"{self.scheme}://127.0.0.1:{self.port}",
            http2=http2 and self.cert is not None,
            verify=verify,
            timeout=10,
        )

    def negotiated_alpn(self) -> str | None:
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as raw:
            with self.context(["h2", "http/1.1"]).wrap_socket(raw, server_hostname="127.0.0.1") as tls:
                return tls.selected_alpn_protocol()


@contextmanager
def boot(
    server: str, cert_files: tuple[Path, Path] | None, tmp_path: Path, own_console: bool = False, **env: str
) -> Iterator[Booted]:
    port = _free_port()
    log = tmp_path / f"serve-{server}-{port}.log"
    cmd = [
        sys.executable, "-m", "app.webapp.serve",
        "--host", "127.0.0.1", "--port", str(port),
        "--app", FIXTURE_APP, "--server", server, "--log-level", "info",
    ]  # fmt: skip
    if cert_files:
        cmd += ["--ssl-certfile", str(cert_files[0]), "--ssl-keyfile", str(cert_files[1])]
    flags = NO_WINDOW | (subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0)
    if own_console and sys.platform == "win32":
        # no-window-exempt: CTRL_BREAK_EVENT is only delivered inside a console, so this one
        # test child keeps the (invisible, test-run) console the group event travels through.
        flags = subprocess.CREATE_NEW_PROCESS_GROUP
    with log.open("wb") as sink:
        proc = subprocess.Popen(
            cmd,
            cwd=REPO_ROOT,
            stdout=sink,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUTF8": "1", "PYTHONUNBUFFERED": "1", **env},
            creationflags=flags,
        )
        booted = Booted(server, proc, port, cert_files[0] if cert_files else None, log)
        try:
            _wait_ready(booted)
            yield booted
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=10)


def _wait_ready(booted: Booted) -> None:
    deadline = time.monotonic() + BOOT_TIMEOUT_S
    while time.monotonic() < deadline:
        if booted.proc.poll() is not None:
            pytest.fail(f"server exited early ({booted.proc.returncode}):\n{booted.log.read_text('utf-8', 'replace')}")
        try:
            with booted.client(http2=False) as c:
                if c.get("/plain").status_code == 200:
                    return
        except httpx.HTTPError:
            time.sleep(0.2)
    pytest.fail(f"server never answered:\n{booted.log.read_text('utf-8', 'replace')}")


@pytest.fixture(scope="module", params=SERVERS)
def live(request: pytest.FixtureRequest, tls_files: tuple[Path, Path], tmp_path_factory: pytest.TempPathFactory) -> Iterator[Booted]:
    with boot(request.param, tls_files, tmp_path_factory.mktemp("run")) as booted:
        yield booted


def test_alpn_negotiates_h2_on_hypercorn_and_http11_on_the_fallback(live: Booted) -> None:
    assert live.negotiated_alpn() == ("h2" if live.speaks_h2 else None)
    with live.client(http2=True) as c:
        response = c.get("/plain")
    assert response.text == "ok"
    assert response.http_version == ("HTTP/2" if live.speaks_h2 else "HTTP/1.1")


def test_gzip_survives_either_protocol(live: Booted) -> None:
    with live.client(http2=True) as c:
        response = c.get("/big", headers={"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert response.content == BIG


def test_bearer_gate_still_answers_401_then_200(live: Booted) -> None:
    with live.client(http2=True) as c:
        assert c.get("/secure").status_code == 401
        assert c.get("/secure", headers={"Authorization": "Bearer wrong"}).status_code == 401
        ok = c.get("/secure", headers={"Authorization": f"Bearer {TOKEN}"})
    assert ok.status_code == 200 and ok.json() == {"secret": True}


def test_sse_event_arrives_before_the_stream_ends(live: Booted) -> None:
    """The second event leaves the app only after /release, so a server that buffers the
    first one until the stream ends never delivers it and the read times out."""
    with live.client(http2=True) as c:
        with c.stream("GET", "/sse") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            assert "content-encoding" not in response.headers
            chunks = response.iter_text()
            assert "first" in next(chunks)
            assert c.get("/release").text == "released"
            assert "second" in "".join(chunks)


def test_proxy_header_is_believed_from_loopback_only(live: Booted) -> None:
    with live.client(http2=True) as c:
        assert c.get("/client").json() == {"host": "127.0.0.1"}
        forwarded = c.get("/client", headers={"X-Forwarded-For": "203.0.113.9"})
    assert forwarded.json() == {"host": "203.0.113.9"}  # the peer is loopback, so it may say so


def test_websocket_echoes_over_tls(live: Booted) -> None:
    ws = WSConnection(ConnectionType.CLIENT)
    with socket.create_connection(("127.0.0.1", live.port), timeout=10) as raw:
        with live.context(["http/1.1"]).wrap_socket(raw, server_hostname="127.0.0.1") as tls:
            tls.sendall(ws.send(Request(host=f"127.0.0.1:{live.port}", target="/ws")))
            seen: list[object] = []
            sent = False
            while not any(isinstance(e, TextMessage) for e in seen):
                data = tls.recv(4096)
                assert data, f"socket closed before an echo: {seen}"
                ws.receive_data(data)
                seen.extend(ws.events())
                if not sent and any(isinstance(e, AcceptConnection) for e in seen):
                    tls.sendall(ws.send(Message(data="hello")))  # only valid once the handshake completed
                    sent = True
    assert any(isinstance(e, AcceptConnection) for e in seen)
    assert [e.data for e in seen if isinstance(e, TextMessage)] == ["echo:hello"]


def test_graceful_signal_runs_the_lifespan_shutdown(
    tls_files: tuple[Path, Path], tmp_path: Path
) -> None:
    for server in SERVERS:
        mark = tmp_path / f"mark-{server}.txt"
        with boot(server, tls_files, tmp_path, own_console=True, SERVE_TEST_MARK=str(mark)) as booted:
            booted.proc.send_signal(signal.CTRL_BREAK_EVENT if sys.platform == "win32" else signal.SIGTERM)
            booted.proc.wait(timeout=15)
        assert mark.read_text("utf-8") == "lifespan-shutdown", f"{server}: no graceful shutdown"


def test_plain_http_still_serves_without_tls(tmp_path: Path) -> None:
    with boot(serve.HYPERCORN, None, tmp_path) as booted:
        with booted.client(http2=False) as c:
            response = c.get("/plain")
    assert response.http_version == "HTTP/1.1" and response.text == "ok"


def test_hypercorn_releases_a_response_its_h2_client_abandoned(
    tls_files: tuple[Path, Path], tmp_path: Path
) -> None:
    """A client that drops mid-send must not leave the endless response's ASGI call running.

    A guard on the behaviour end to end. The release patch's own logic is pinned by the
    stub test above: hypercorn 0.18 ended this call on its own in the client shapes tried
    here (clean close, socket reset), so this does not by itself show the patch is needed."""
    with boot(serve.HYPERCORN, tls_files, tmp_path) as booted:
        victim = booted.client(http2=True)
        response = victim.send(victim.build_request("GET", "/hang"), stream=True)
        assert response.http_version == "HTTP/2"
        next(response.iter_raw())
        victim.close()  # the connection drops with the response mid-send
        with booted.client(http2=True) as watcher:
            deadline = time.monotonic() + 10
            stats: dict[str, int] = {}
            while time.monotonic() < deadline:
                stats = watcher.get("/stats").json()
                if stats["hang_ended"] >= 1:
                    break
                time.sleep(0.2)
    assert stats["hang_started"] == 1
    assert stats["hang_ended"] == 1, f"abandoned stream leaked its ASGI call: {stats}"
