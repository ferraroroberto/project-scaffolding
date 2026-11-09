"""Unit tests for the vendored Telegram notifier (src/notify/).

Offline by construction: no real token, chat, or network — ``urlopen`` is
monkeypatched. Covers the importable contract every consuming app relies on,
mirroring the byte-for-byte guarantee of the tray's vendored primitives.
"""

from __future__ import annotations

import json
import urllib.error
from contextlib import contextmanager
from typing import Any

import pytest

from src.notify import (
    NotifierError,
    TelegramConfig,
    TelegramNotifier,
    build_notifier,
)
from src.notify import telegram as telegram_mod


def test_build_notifier_branches() -> None:
    assert build_notifier("none", TelegramConfig("", "")) is None
    assert isinstance(
        build_notifier("telegram", TelegramConfig("t", "c")), TelegramNotifier
    )
    with pytest.raises(ValueError):
        build_notifier("carrier-pigeon", TelegramConfig("t", "c"))


def test_telegram_requires_credentials() -> None:
    with pytest.raises(NotifierError):
        TelegramNotifier("", "")
    with pytest.raises(NotifierError):
        TelegramNotifier("token", "")


@contextmanager
def _fake_response(payload: dict[str, Any]):
    class _Resp:
        def read(self) -> bytes:
            return json.dumps(payload).encode("utf-8")

    yield _Resp()


def test_send_text_success(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_urlopen(request: Any, timeout: int = 0):  # noqa: ANN401
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _fake_response({"ok": True})

    monkeypatch.setattr(telegram_mod.urllib.request, "urlopen", fake_urlopen)
    TelegramNotifier("TOKEN", "CHAT").send_text("alarm triggered")

    assert "botTOKEN/sendMessage" in captured["url"]
    assert captured["body"]["chat_id"] == "CHAT"
    assert captured["body"]["text"] == "alarm triggered"


def test_send_text_rejected_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: int = 0):  # noqa: ANN401
        return _fake_response({"ok": False, "description": "chat not found"})

    monkeypatch.setattr(telegram_mod.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(NotifierError, match="chat not found"):
        TelegramNotifier("TOKEN", "CHAT").send_text("hi")


def test_send_text_transport_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: Any, timeout: int = 0):  # noqa: ANN401
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(telegram_mod.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(NotifierError, match="Telegram request failed"):
        TelegramNotifier("TOKEN", "CHAT").send_text("hi")


def test_send_text_non_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    @contextmanager
    def _bad_response():
        class _Resp:
            def read(self) -> bytes:
                return b"<html>502 Bad Gateway</html>"

        yield _Resp()

    def fake_urlopen(request: Any, timeout: int = 0):  # noqa: ANN401
        return _bad_response()

    monkeypatch.setattr(telegram_mod.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(NotifierError, match="non-JSON"):
        TelegramNotifier("TOKEN", "CHAT").send_text("hi")


def _raising_urlopen(exc: BaseException):
    def fake_urlopen(request: Any, timeout: int = 0):  # noqa: ANN401
        raise exc

    return fake_urlopen


def test_send_text_timeout_raises_notifier_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A timeout while waiting for the response escapes urllib as a bare
    # TimeoutError (an OSError, not a URLError).
    monkeypatch.setattr(
        telegram_mod.urllib.request, "urlopen", _raising_urlopen(TimeoutError("timed out"))
    )
    with pytest.raises(NotifierError, match="Telegram request failed"):
        TelegramNotifier("TOKEN", "CHAT").send_text("hi")


def test_send_text_non_utf8_body_raises_notifier_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def _bad_response():
        class _Resp:
            def read(self) -> bytes:
                return b"\xff\xfe not utf-8"

        yield _Resp()

    monkeypatch.setattr(
        telegram_mod.urllib.request, "urlopen", lambda request, timeout=0: _bad_response()
    )
    with pytest.raises(NotifierError, match="non-JSON"):
        TelegramNotifier("TOKEN", "CHAT").send_text("hi")


def test_send_text_non_object_json_raises_notifier_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        telegram_mod.urllib.request,
        "urlopen",
        lambda request, timeout=0: _fake_response(["not", "an", "object"]),  # type: ignore[arg-type]
    )
    with pytest.raises(NotifierError, match="non-object"):
        TelegramNotifier("TOKEN", "CHAT").send_text("hi")


def _capture_texts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    texts: list[str] = []

    def fake_urlopen(request: Any, timeout: int = 0):  # noqa: ANN401
        texts.append(json.loads(request.data.decode("utf-8"))["text"])
        return _fake_response({"ok": True})

    monkeypatch.setattr(telegram_mod.urllib.request, "urlopen", fake_urlopen)
    return texts


def test_send_text_at_limit_is_one_call(monkeypatch: pytest.MonkeyPatch) -> None:
    texts = _capture_texts(monkeypatch)
    TelegramNotifier("TOKEN", "CHAT").send_text("x" * 4096)
    assert texts == ["x" * 4096]


def test_send_text_over_limit_chunks_without_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    texts = _capture_texts(monkeypatch)
    # 1200 lines of 9 chars + newline: about 12000 characters, so several chunks.
    message = "".join(f"line {i:04d}\n" for i in range(1200))
    TelegramNotifier("TOKEN", "CHAT").send_text(message)

    assert len(texts) > 1
    assert all(len(piece) <= 4096 for piece in texts)
    assert "".join(texts) == message
    # Every cut lands on a line boundary because every line fits.
    assert all(piece.endswith("\n") for piece in texts)


def test_send_text_hard_cuts_a_line_longer_than_the_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    texts = _capture_texts(monkeypatch)
    message = "y" * 10000
    TelegramNotifier("TOKEN", "CHAT").send_text(message)

    assert [len(piece) for piece in texts] == [4096, 4096, 1808]
    assert "".join(texts) == message


def test_send_text_stops_at_the_first_rejected_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0

    def fake_urlopen(request: Any, timeout: int = 0):  # noqa: ANN401
        nonlocal calls
        calls += 1
        return _fake_response({"ok": False, "description": "chat not found"})

    monkeypatch.setattr(telegram_mod.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(NotifierError, match="chat not found"):
        TelegramNotifier("TOKEN", "CHAT").send_text("z" * 9000)
    assert calls == 1
