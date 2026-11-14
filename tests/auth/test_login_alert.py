"""Tests for the vendored login alert (`src/login_alert.py`).

The lock-out runs on a fake clock and the alert goes to a fake notifier, so
nothing sleeps and nothing reaches Telegram.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import pytest

from src.login_alert import (
    FAILED,
    SENT,
    UNCONFIGURED,
    alert_text,
    build_login_alert,
    deliver_alert,
)
from src.login_lockout import LockoutAlert, LoginLockout


class FakeNotifier:
    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[str] = []
        self._error = error

    def send_text(self, text: str) -> None:
        if self._error is not None:
            raise self._error
        self.sent.append(text)


def _inline(send: Callable[[], None]) -> None:
    send()


def test_three_wrong_passwords_send_one_alert() -> None:
    notifier = FakeNotifier()
    lockout = LoginLockout(
        on_alert=build_login_alert("demo-app", lambda: notifier, run=_inline),
        clock=lambda: 1000.0,
    )
    for _ in range(5):
        lockout.record_failure("203.0.113.7")
    assert notifier.sent == ["🚨 demo-app: 3 wrong passwords in a row from 203.0.113.7"]


def test_text_counts_alerts_the_cooldown_held_back() -> None:
    alert = LockoutAlert(key="198.51.100.2", failures=4, suppressed=2)
    assert alert_text("demo-app", alert) == (
        "🚨 demo-app: 4 wrong passwords in a row from 198.51.100.2 (+2 more held back)"
    )


def test_no_channel_reports_unconfigured_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    alert = LockoutAlert(key="203.0.113.7", failures=3, suppressed=0)
    with caplog.at_level(logging.WARNING, logger="src.login_alert"):
        assert deliver_alert("demo-app", alert, lambda: None) == UNCONFIGURED
    assert "unconfigured" in caplog.text
    assert "203.0.113.7" in caplog.text


def test_transport_error_is_failed_and_logs_only_its_type(caplog: pytest.LogCaptureFixture) -> None:
    alert = LockoutAlert(key="203.0.113.7", failures=3, suppressed=0)
    notifier = FakeNotifier(RuntimeError("https://api.example/botSECRET/sendMessage"))
    with caplog.at_level(logging.WARNING, logger="src.login_alert"):
        assert deliver_alert("demo-app", alert, lambda: notifier) == FAILED
    assert "RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text


def test_a_failing_config_read_is_failed_not_raised() -> None:
    def broken() -> FakeNotifier:
        raise OSError("config unreadable")

    alert = LockoutAlert(key="203.0.113.7", failures=3, suppressed=0)
    assert deliver_alert("demo-app", alert, broken) == FAILED


def test_sent_outcome() -> None:
    notifier = FakeNotifier()
    alert = LockoutAlert(key="203.0.113.7", failures=3, suppressed=0)
    assert deliver_alert("demo-app", alert, lambda: notifier) == SENT


def test_on_alert_hands_the_send_off_and_returns() -> None:
    queued: list[Callable[[], None]] = []
    calls: list[str] = []

    def source() -> FakeNotifier:
        calls.append("read")
        return FakeNotifier()

    on_alert = build_login_alert("demo-app", source, run=queued.append)
    on_alert(LockoutAlert(key="203.0.113.7", failures=3, suppressed=0))
    assert calls == [] and len(queued) == 1
    queued[0]()
    assert calls == ["read"]
