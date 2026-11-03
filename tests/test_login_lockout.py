"""Tests for the vendored login lock-out (`src/login_lockout.py`).

Every test runs on a fake clock: nothing sleeps. The alert is proven with a
fake notifier that records what it was handed.
"""

from __future__ import annotations

import logging

import pytest

from src.login_lockout import LockoutAlert, LoginLockout, retry_after_header


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeNotifier:
    def __init__(self) -> None:
        self.alerts: list[LockoutAlert] = []

    def __call__(self, alert: LockoutAlert) -> None:
        self.alerts.append(alert)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def _fail(lockout: LoginLockout, key: str, times: int) -> list[float]:
    return [lockout.record_failure(key) for _ in range(times)]


# ------------------------------------------------------------------ the wait

def test_the_first_five_failures_are_free(clock: FakeClock) -> None:
    lockout = LoginLockout(clock=clock)
    assert _fail(lockout, "a", 5) == [0.0] * 5
    assert lockout.retry_after("a") == 0.0


def test_the_wait_doubles_from_two_seconds_to_the_cap(clock: FakeClock) -> None:
    lockout = LoginLockout(clock=clock)
    _fail(lockout, "a", 5)
    waits = []
    for _ in range(10):
        waits.append(lockout.record_failure("a"))
        assert lockout.retry_after("a") == waits[-1]
        clock.advance(waits[-1])  # the client waits it out before the next try
    assert waits == [2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0, 300.0, 300.0]


def test_the_wait_counts_down_and_then_lets_the_client_try(clock: FakeClock) -> None:
    lockout = LoginLockout(clock=clock)
    _fail(lockout, "a", 6)
    clock.advance(0.5)
    assert lockout.retry_after("a") == 1.5
    clock.advance(1.5)
    assert lockout.retry_after("a") == 0.0


@pytest.mark.parametrize(("seconds", "header"), [(1.5, "2"), (2.0, "2"), (0.01, "1"), (299.2, "300")])
def test_retry_after_header_rounds_up_to_whole_seconds(seconds: float, header: str) -> None:
    assert retry_after_header(seconds) == {"Retry-After": header}


def test_a_streak_is_forgotten_after_an_hour_with_no_failure(clock: FakeClock) -> None:
    lockout = LoginLockout(clock=clock)
    _fail(lockout, "a", 9)
    clock.advance(3599)
    assert lockout.record_failure("a") > 0, "a failure inside the hour keeps the streak"
    clock.advance(3600)
    assert lockout.retry_after("a") == 0.0
    assert _fail(lockout, "a", 5) == [0.0] * 5, "a forgotten streak starts over with its free attempts"


def test_a_correct_password_clears_the_streak(clock: FakeClock) -> None:
    lockout = LoginLockout(clock=clock)
    _fail(lockout, "a", 7)
    lockout.reset("a")
    assert lockout.retry_after("a") == 0.0
    assert _fail(lockout, "a", 5) == [0.0] * 5


def test_clients_are_counted_separately(clock: FakeClock) -> None:
    lockout = LoginLockout(clock=clock)
    _fail(lockout, "a", 6)
    assert lockout.retry_after("a") > 0
    assert lockout.retry_after("b") == 0.0
    assert lockout.record_failure("b") == 0.0


# ------------------------------------------------------------------ the table

def test_a_full_table_drops_forgotten_clients_first(clock: FakeClock) -> None:
    lockout = LoginLockout(clock=clock, max_clients=2)
    _fail(lockout, "old", 6)
    clock.advance(1800)
    _fail(lockout, "recent", 6)
    clock.advance(1800)  # "old" is now forgotten, "recent" is not
    _fail(lockout, "new", 1)
    assert list(lockout._streaks) == ["recent", "new"]
    assert lockout.record_failure("recent") > 0, "the surviving streak kept its count"


def test_a_full_table_with_nothing_forgotten_drops_the_oldest_and_stays_bounded(clock: FakeClock) -> None:
    lockout = LoginLockout(clock=clock, max_clients=3)
    for i in range(10):
        _fail(lockout, f"c{i}", 6)
        clock.advance(1)
    assert list(lockout._streaks) == ["c7", "c8", "c9"]


def test_a_new_failure_makes_a_client_the_newest(clock: FakeClock) -> None:
    lockout = LoginLockout(clock=clock, max_clients=2)
    _fail(lockout, "a", 1)
    _fail(lockout, "b", 1)
    _fail(lockout, "a", 1)
    _fail(lockout, "c", 1)
    assert list(lockout._streaks) == ["a", "c"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"free_attempts": -1},
        {"alert_after": 0},
        {"max_clients": 0},
        {"base_delay": 0.0},
        {"base_delay": 10.0, "max_delay": 5.0},
        {"max_delay": 7200.0},
        {"alert_cooldown": -1.0},
    ],
)
def test_a_nonsense_policy_is_refused(kwargs: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        LoginLockout(**kwargs)  # type: ignore[arg-type]


# ------------------------------------------------------------------ the log

def test_the_lock_log_line_names_no_client_or_password(clock: FakeClock, caplog: pytest.LogCaptureFixture) -> None:
    lockout = LoginLockout(clock=clock, on_alert=FakeNotifier())
    with caplog.at_level(logging.INFO, logger="src.login_lockout"):
        _fail(lockout, "203.0.113.7", 6)
    lines = [r.getMessage() for r in caplog.records]
    assert "🔒 login locked for 2 s after 6 failures" in lines
    assert all("203.0.113.7" not in line for line in lines)


# ------------------------------------------------------------------ the alert

def test_three_consecutive_failures_raise_one_alert_for_the_streak(clock: FakeClock) -> None:
    notifier = FakeNotifier()
    lockout = LoginLockout(clock=clock, on_alert=notifier)
    _fail(lockout, "203.0.113.7", 2)
    assert notifier.alerts == []
    _fail(lockout, "203.0.113.7", 1)
    assert notifier.alerts == [LockoutAlert("203.0.113.7", 3, 0)]
    for _ in range(10):  # the rest of the streak, waits included, adds no alert
        clock.advance(lockout.record_failure("203.0.113.7"))
    assert len(notifier.alerts) == 1


def test_a_success_ends_the_streak_so_the_next_streak_alerts_again(clock: FakeClock) -> None:
    notifier = FakeNotifier()
    lockout = LoginLockout(clock=clock, on_alert=notifier, alert_cooldown=0)
    _fail(lockout, "a", 3)
    lockout.reset("a")
    _fail(lockout, "a", 2)
    assert len(notifier.alerts) == 1, "two failures after a success are not three in a row"
    _fail(lockout, "a", 1)
    assert len(notifier.alerts) == 2


def test_a_forgotten_streak_alerts_again_when_it_restarts(clock: FakeClock) -> None:
    notifier = FakeNotifier()
    lockout = LoginLockout(clock=clock, on_alert=notifier)
    _fail(lockout, "a", 3)
    clock.advance(3600)
    _fail(lockout, "a", 3)
    assert [a.failures for a in notifier.alerts] == [3, 3]


def test_the_cooldown_holds_back_alerts_and_counts_them_into_the_next(clock: FakeClock) -> None:
    notifier = FakeNotifier()
    lockout = LoginLockout(clock=clock, on_alert=notifier, alert_cooldown=300)
    _fail(lockout, "a", 3)
    for key in ("b", "c", "d"):  # an address-rotating attack inside the cooldown
        _fail(lockout, key, 3)
    assert [a.key for a in notifier.alerts] == ["a"]
    clock.advance(300)
    _fail(lockout, "e", 3)
    assert notifier.alerts[-1] == LockoutAlert("e", 3, 3)
    clock.advance(300)
    _fail(lockout, "f", 3)
    assert notifier.alerts[-1].suppressed == 0


def test_the_alert_carries_no_password_or_token_fields() -> None:
    assert set(LockoutAlert.__dataclass_fields__) == {"key", "failures", "suppressed"}


def test_a_failing_alert_callback_never_breaks_the_login(clock: FakeClock, caplog: pytest.LogCaptureFixture) -> None:
    def broken(alert: LockoutAlert) -> None:
        raise RuntimeError("secret-bot-token in a URL")

    lockout = LoginLockout(clock=clock, on_alert=broken)
    with caplog.at_level(logging.WARNING, logger="src.login_lockout"):
        assert _fail(lockout, "a", 3) == [0.0] * 3
    assert [r.getMessage() for r in caplog.records] == ["⚠️ login alert callback failed: RuntimeError"]


def test_no_callback_means_no_alert_bookkeeping(clock: FakeClock, caplog: pytest.LogCaptureFixture) -> None:
    lockout = LoginLockout(clock=clock)
    with caplog.at_level(logging.INFO, logger="src.login_lockout"):
        _fail(lockout, "a", 4)
    assert caplog.records == []
