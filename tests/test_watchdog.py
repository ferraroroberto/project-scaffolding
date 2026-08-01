"""Unit tests for the canonical tray self-heal primitives (app/tray/watchdog.py).

Hermetic and platform-agnostic: no sleeping (the retry helper takes an injectable
``sleep``), no threads for the edge-transition cases (``tick()`` is driven
directly), and the breadcrumb file is written under ``tmp_path``.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.tray.watchdog import (
    DEFAULT_STARTUP_RETRY_DELAYS_S,
    BreadcrumbLog,
    HealthWatchdog,
    retry_with_backoff,
)

# --------------------------------------------------------------- retry helper


def test_retry_returns_on_first_success() -> None:
    calls: list[int] = []
    slept: list[float] = []

    retry_with_backoff(lambda: calls.append(1), (5.0, 15.0), sleep=slept.append)

    assert len(calls) == 1
    assert slept == []  # a first-attempt success must never sleep


def test_retry_recovers_after_transient_failures() -> None:
    """The motivating case: the initial spawn loses a race, then wins."""
    attempts: list[int] = []
    failures: list[tuple[int, str]] = []
    slept: list[float] = []

    def flaky() -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise OSError(f"port busy (attempt {len(attempts)})")

    retry_with_backoff(
        flaky,
        (5.0, 15.0, 30.0),
        lambda n, exc: failures.append((n, str(exc))),
        sleep=slept.append,
    )

    assert len(attempts) == 3
    assert [n for n, _ in failures] == [1, 2]
    assert slept == [5.0, 15.0]  # delays consumed in order, none after success


def test_retry_reraises_after_exhausting_delays() -> None:
    attempts: list[int] = []
    slept: list[float] = []

    def always_fails() -> None:
        attempts.append(1)
        raise RuntimeError("still down")

    with pytest.raises(RuntimeError, match="still down"):
        retry_with_backoff(always_fails, (1.0, 2.0), sleep=slept.append)

    # len(delays) + 1 attempts total; the last failure re-raises, never sleeps.
    assert len(attempts) == 3
    assert slept == [1.0, 2.0]


def test_retry_reports_the_final_failed_attempt_before_raising() -> None:
    """The breadcrumb for the *fatal* attempt must be written, not swallowed."""
    seen: list[int] = []

    with pytest.raises(ValueError):
        retry_with_backoff(
            lambda: (_ for _ in ()).throw(ValueError("nope")),
            (0.1,),
            lambda n, _exc: seen.append(n),
            sleep=lambda _s: None,
        )

    assert seen == [1, 2]


def test_default_startup_delays_are_bounded_and_escalating() -> None:
    assert DEFAULT_STARTUP_RETRY_DELAYS_S == (5.0, 15.0, 30.0)
    assert list(DEFAULT_STARTUP_RETRY_DELAYS_S) == sorted(DEFAULT_STARTUP_RETRY_DELAYS_S)


# ------------------------------------------------------------ health watchdog


class _Recorder:
    def __init__(self) -> None:
        self.wedges: list[int] = []
        self.recoveries = 0

    def on_wedge(self, count: int) -> None:
        self.wedges.append(count)

    def on_recover(self) -> None:
        self.recoveries += 1


def test_wedge_fires_once_on_the_threshold_edge() -> None:
    rec = _Recorder()
    wd = HealthWatchdog(lambda: False, rec.on_wedge, rec.on_recover, failures_to_alert=3)

    for _ in range(6):
        assert wd.tick() is False

    assert rec.wedges == [3]  # edge-triggered: one alert, not one per tick
    assert rec.recoveries == 0


def test_intermittent_failures_below_threshold_never_alert() -> None:
    """A tray-menu restart (a tick or two of downtime) is not a wedge."""
    rec = _Recorder()
    results = iter([False, False, True, False, False, True])
    wd = HealthWatchdog(lambda: next(results), rec.on_wedge, rec.on_recover, failures_to_alert=3)

    for _ in range(6):
        wd.tick()

    assert rec.wedges == []
    assert rec.recoveries == 0  # no alert was raised, so nothing to recover from


def test_recovery_fires_once_and_rearms_the_edge() -> None:
    rec = _Recorder()
    state = {"ok": False}
    wd = HealthWatchdog(
        lambda: state["ok"], rec.on_wedge, rec.on_recover, failures_to_alert=2
    )

    wd.tick()
    wd.tick()
    assert rec.wedges == [2]

    state["ok"] = True
    assert wd.tick() is True
    wd.tick()
    assert rec.recoveries == 1  # only the first success after the alert

    state["ok"] = False
    wd.tick()
    wd.tick()
    assert rec.wedges == [2, 2]  # counter reset on recovery, so the edge is a fresh 2


def test_rearm_lets_a_failed_respawn_try_again_next_tick() -> None:
    """photo-ocr#110's addition: without rearm() a failed respawn goes silent forever."""
    rec = _Recorder()
    wd: HealthWatchdog

    def on_wedge(count: int) -> None:
        rec.on_wedge(count)
        wd.rearm()  # "I acted (respawn attempt); re-evaluate me next tick"

    wd = HealthWatchdog(lambda: False, on_wedge, rec.on_recover, failures_to_alert=2)

    for _ in range(4):
        wd.tick()

    assert rec.wedges == [2, 3, 4]  # re-armed each tick, counter keeps climbing


def test_a_raising_probe_counts_as_a_failure() -> None:
    rec = _Recorder()

    def probe() -> bool:
        raise ConnectionError("connection refused")

    wd = HealthWatchdog(probe, rec.on_wedge, rec.on_recover, failures_to_alert=2)

    assert wd.tick() is False
    assert wd.tick() is False
    assert rec.wedges == [2]


def test_run_polls_until_stopped_and_probes_after_the_first_interval() -> None:
    rec = _Recorder()
    ticks: list[int] = []
    stop = threading.Event()

    def probe() -> bool:
        ticks.append(1)
        if len(ticks) >= 3:
            stop.set()
        return True

    wd = HealthWatchdog(probe, rec.on_wedge, rec.on_recover)
    wd.run(stop, interval_s=0.01)

    assert len(ticks) == 3


def test_run_returns_immediately_if_already_stopped() -> None:
    rec = _Recorder()
    ticks: list[int] = []
    stop = threading.Event()
    stop.set()

    wd = HealthWatchdog(lambda: ticks.append(1) is None, rec.on_wedge, rec.on_recover)
    wd.run(stop, interval_s=60.0)

    assert ticks == []


# --------------------------------------------------------------- breadcrumbs


def test_breadcrumb_appends_timestamped_lines_creating_the_directory(tmp_path: Path) -> None:
    log = BreadcrumbLog(tmp_path / "webapp" / "watchdog.log")

    log.write("webapp start attempt 1 failed: port busy")
    log("webapp respawned successfully")  # __call__ alias

    lines = log.path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("webapp start attempt 1 failed: port busy")
    assert lines[1].endswith("webapp respawned successfully")
    # ISO-second stamp: "YYYY-MM-DDTHH:MM:SS "
    assert lines[0][10] == "T" and lines[0][19] == " "


def test_breadcrumb_write_never_raises_on_an_unwritable_path(tmp_path: Path) -> None:
    # A file where the parent directory needs to be — mkdir + open both fail.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")

    BreadcrumbLog(blocker / "watchdog.log").write("must not raise")


def test_breadcrumb_rotates_once_past_the_size_cap(tmp_path: Path) -> None:
    log = BreadcrumbLog(tmp_path / "watchdog.log", max_bytes=200)

    for i in range(40):
        log.write(f"event {i} with enough text to push past the cap")

    rotated = tmp_path / "watchdog.log.1"
    assert rotated.exists()
    assert log.path.stat().st_size < 200 * 2  # the live file was actually reset


def test_breadcrumb_rotation_can_be_disabled(tmp_path: Path) -> None:
    log = BreadcrumbLog(tmp_path / "watchdog.log", max_bytes=0)

    for i in range(40):
        log.write(f"event {i} with enough text to push past any cap")

    assert not (tmp_path / "watchdog.log.1").exists()
