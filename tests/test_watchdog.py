"""Unit tests for the canonical tray self-heal primitives (app/tray/watchdog.py).

Hermetic and platform-agnostic: no sleeping (the retry helper takes an injectable
``sleep``), no threads for the edge-transition cases (``tick()`` is driven
directly), and the breadcrumb file is written under ``tmp_path``.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

import pytest

from app.tray.watchdog import (
    DEFAULT_STARTUP_RETRY_DELAYS_S,
    BreadcrumbLog,
    HealthWatchdog,
    RespawnGuard,
    RespawnOutcome,
    WatchState,
    next_watch_state,
    process_identity,
    retry_with_backoff,
    stop_process_tree,
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


def test_on_failing_fires_every_failed_probe_from_the_alert_onward() -> None:
    rec = _Recorder()
    failing: list[int] = []
    state = {"ok": False}
    wd = HealthWatchdog(
        lambda: state["ok"],
        rec.on_wedge,
        rec.on_recover,
        failures_to_alert=3,
        on_failing=failing.append,
    )

    for _ in range(5):
        wd.tick()
    assert rec.wedges == [3]
    assert failing == [3, 4, 5]  # silent below the threshold, then every failed tick

    state["ok"] = True
    wd.tick()
    wd.tick()
    assert failing == [3, 4, 5]  # a recovery stops it
    assert rec.recoveries == 1

    state["ok"] = False
    for _ in range(3):
        wd.tick()
    assert failing == [3, 4, 5, 3]  # the next alert starts a fresh count


def test_on_failing_is_skipped_when_on_wedge_rearms() -> None:
    failing: list[int] = []
    wd: HealthWatchdog

    def on_wedge(count: int) -> None:
        wd.rearm()

    wd = HealthWatchdog(
        lambda: False, on_wedge, lambda: None, failures_to_alert=2, on_failing=failing.append
    )

    for _ in range(4):
        wd.tick()

    assert failing == []  # a re-armed watchdog is not alerted, so nothing to report


def test_a_watchdog_without_on_failing_behaves_as_before() -> None:
    rec = _Recorder()
    wd = HealthWatchdog(lambda: False, rec.on_wedge, rec.on_recover, failures_to_alert=2)

    for _ in range(4):
        assert wd.tick() is False

    assert rec.wedges == [2]


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


def test_recovery_fires_after_a_failed_respawn_rearmed_the_watchdog() -> None:
    """The first passing probe after ``rearm()`` is a recovery: the owner got the wedge alert."""
    rec = _Recorder()
    results = iter([False, False, False, True, True])
    wd: HealthWatchdog

    def on_wedge(count: int) -> None:
        rec.on_wedge(count)
        wd.rearm()  # the respawn failed

    wd = HealthWatchdog(lambda: next(results), on_wedge, rec.on_recover, failures_to_alert=3)

    for _ in range(5):
        wd.tick()

    assert rec.wedges == [3]
    assert rec.recoveries == 1  # once: the second passing probe is already healthy


def test_state_property_follows_the_four_states() -> None:
    results = iter([True, False, False, False, True])
    wd: HealthWatchdog

    def on_wedge(_count: int) -> None:
        wd.rearm()

    wd = HealthWatchdog(lambda: next(results), on_wedge, lambda: None, failures_to_alert=3)
    assert wd.state is WatchState.HEALTHY

    seen = []
    for _ in range(5):
        wd.tick()
        seen.append(wd.state)

    assert seen == [
        WatchState.HEALTHY,
        WatchState.FAILING,
        WatchState.FAILING,
        WatchState.REARMED,  # the threshold tick fired on_wedge, which re-armed
        WatchState.HEALTHY,
    ]


def test_rearm_is_a_no_op_outside_the_wedged_state() -> None:
    wd = HealthWatchdog(lambda: False, lambda _c: None, lambda: None, failures_to_alert=3)

    wd.rearm()
    assert wd.state is WatchState.HEALTHY
    wd.tick()
    wd.rearm()
    assert wd.state is WatchState.FAILING


# One row per (state, probe result): the next state, and which callbacks fire.
# ``failures`` is the consecutive-failure count before the probe; the threshold is 3.
_H, _F, _W, _R = (
    WatchState.HEALTHY,
    WatchState.FAILING,
    WatchState.WEDGED,
    WatchState.REARMED,
)
_TRANSITION_TABLE = [
    # state, failures, ok, next state, next failures, wedge, recover, failing
    (_H, 0, True, _H, 0, False, False, False),
    (_H, 0, False, _F, 1, False, False, False),
    (_F, 1, True, _H, 0, False, False, False),
    (_F, 1, False, _F, 2, False, False, False),
    (_F, 2, False, _W, 3, True, False, True),
    (_W, 3, True, _H, 0, False, True, False),
    (_W, 3, False, _W, 4, False, False, True),
    (_R, 3, True, _H, 0, False, True, False),
    (_R, 3, False, _W, 4, True, False, True),
]


@pytest.mark.parametrize(
    ("state", "failures", "ok", "want_state", "want_failures", "wedge", "recover", "failing"),
    _TRANSITION_TABLE,
)
def test_transition_table(
    state: WatchState,
    failures: int,
    ok: bool,
    want_state: WatchState,
    want_failures: int,
    wedge: bool,
    recover: bool,
    failing: bool,
) -> None:
    step = next_watch_state(state, ok, failures, 3)

    assert step.state is want_state
    assert step.failures == want_failures
    assert (step.wedge, step.recover, step.failing) == (wedge, recover, failing)


@pytest.mark.parametrize(
    ("state", "failures"),
    [
        (WatchState.HEALTHY, 1),  # healthy with a failure on the books
        (WatchState.FAILING, 0),  # failing with none
        (WatchState.FAILING, 3),  # failing at the threshold is already wedged
        (WatchState.WEDGED, 2),  # wedged below the threshold
        (WatchState.REARMED, 0),  # re-armed with nothing to re-arm from
    ],
)
def test_an_impossible_state_and_count_pair_is_refused(state: WatchState, failures: int) -> None:
    # state-machine-proof: tray-watchdog
    with pytest.raises(ValueError, match="impossible"):
        next_watch_state(state, False, failures, 3)


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


# ------------------------------------------------------------- respawn guard


class _SlowBootWorld:
    """A fake clock and process table: each child binds ``bind_after_s`` after it spawns.

    Nothing reaps a child except an explicit stop, so a respawn that forgets
    the previous copy shows up as two live pids.
    """

    def __init__(self, bind_after_s: float, survives_stop: bool = False) -> None:
        self.now = 0.0
        self.bind_after_s = bind_after_s
        self.survives_stop = survives_stop
        self.alive: dict[int, int] = {}  # pid -> identity token
        self.spawned_at: dict[int, float] = {}
        self.stopped: list[int] = []
        self._next = 1000

    def clock(self) -> float:
        return self.now

    def identity(self, pid: int) -> int | None:
        return self.alive.get(pid)

    def stop_tree(self, pid: int) -> None:
        self.stopped.append(pid)
        if not self.survives_stop:
            self.alive.pop(pid, None)

    def spawn(self) -> int:
        self._next += 1
        self.alive[self._next] = self._next * 7
        self.spawned_at[self._next] = self.now
        return self._next

    def answering(self) -> bool:
        return any(self.now - self.spawned_at[p] >= self.bind_after_s for p in self.alive)


def _guard(world: _SlowBootWorld, log: list[str], window: float = 300.0) -> RespawnGuard:
    return RespawnGuard(
        log.append, window, identity=world.identity, stop_tree=world.stop_tree, clock=world.clock
    )


def test_a_slow_boot_never_leaves_more_than_one_webapp_alive() -> None:
    """The documented handler, routed through the guard, on a boot slower than the window."""
    world = _SlowBootWorld(bind_after_s=10_000.0)  # never answers inside the run
    log: list[str] = []
    guard = _guard(world, log)

    def on_wedge(count: int) -> None:
        if guard.is_starting():
            watchdog.rearm()
            return
        try:
            guard.respawn(world.spawn)
        finally:
            watchdog.rearm()

    watchdog = HealthWatchdog(world.answering, on_wedge, lambda: None)
    guard.respawn(world.spawn)  # the boot spawn
    peak = 1
    for _ in range(30):  # 30 minutes of failing probes at the default cadence
        world.now += 60.0
        watchdog.tick()
        peak = max(peak, len(world.alive))

    assert peak == 1
    assert world.stopped  # past the window the stale copy was reaped, not left behind


def test_a_second_spawn_is_refused_while_the_first_child_is_starting() -> None:
    world = _SlowBootWorld(bind_after_s=120.0)
    log: list[str] = []
    guard = _guard(world, log)
    first = guard.respawn(world.spawn)
    world.now += 299.0

    assert first is RespawnOutcome.SPAWNED
    assert guard.is_starting()
    assert guard.respawn(world.spawn) is RespawnOutcome.STARTING
    assert list(world.alive) == [guard.pid]
    assert world.stopped == []
    assert "still starting" in log[-1] and str(guard.pid) in log[-1]


def test_the_breadcrumb_names_the_pid_stopped_before_each_respawn() -> None:
    world = _SlowBootWorld(bind_after_s=10_000.0)
    log: list[str] = []
    guard = _guard(world, log, window=60.0)
    guard.respawn(world.spawn)
    old = guard.pid
    world.now += 61.0

    assert guard.respawn(world.spawn) is RespawnOutcome.SPAWNED
    stop_line = next(i for i, line in enumerate(log) if line.startswith("stopping"))
    assert f"pid {old}" in log[stop_line]
    assert f"pid {guard.pid}" in log[stop_line + 1]  # named before the new spawn is tracked
    assert world.stopped == [old] and list(world.alive) == [guard.pid]


def test_a_child_that_already_exited_is_named_and_replaced_at_once() -> None:
    world = _SlowBootWorld(bind_after_s=10_000.0)
    log: list[str] = []
    guard = _guard(world, log)
    guard.respawn(world.spawn)
    old = guard.pid
    world.alive.clear()  # crashed during import, well inside the window

    assert not guard.is_starting()
    assert guard.respawn(world.spawn) is RespawnOutcome.SPAWNED
    assert f"previous webapp pid {old} already exited" in log
    assert world.stopped == []


def test_a_child_that_survives_its_stop_blocks_the_spawn() -> None:
    world = _SlowBootWorld(bind_after_s=10_000.0, survives_stop=True)
    log: list[str] = []
    guard = _guard(world, log, window=60.0)
    guard.respawn(world.spawn)
    world.now += 61.0

    with pytest.raises(RuntimeError, match="survived its stop"):
        guard.respawn(world.spawn)
    assert len(world.alive) == 1


def test_a_reused_pid_reads_as_exited_and_is_never_stopped() -> None:
    world = _SlowBootWorld(bind_after_s=10_000.0)
    log: list[str] = []
    guard = _guard(world, log, window=60.0)
    guard.respawn(world.spawn)
    old = guard.pid
    assert old is not None
    world.alive[old] = -1  # the OS handed the pid to an unrelated process
    world.now += 61.0

    guard.respawn(world.spawn)
    assert world.stopped == []
    assert f"previous webapp pid {old} already exited" in log


def test_track_adopts_a_spawn_made_outside_the_guard() -> None:
    world = _SlowBootWorld(bind_after_s=10_000.0)
    log: list[str] = []
    guard = _guard(world, log)
    pid = world.spawn()  # e.g. a tray-menu restart

    guard.track(pid)
    assert guard.pid == pid and guard.is_starting()
    assert guard.respawn(world.spawn) is RespawnOutcome.STARTING


def test_process_identity_and_stop_process_tree_on_a_real_child() -> None:
    """A throwaway sleeping child: live identity, stopped, then gone."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        assert process_identity(child.pid) is not None
        stop_process_tree(child.pid)
        child.wait(timeout=30)
        assert process_identity(child.pid) is None
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=30)


def test_a_boot_slower_than_the_window_is_backed_off_until_it_answers() -> None:
    world = _SlowBootWorld(bind_after_s=500.0)  # slower than the 300 s base window
    log: list[str] = []
    guard = _guard(world, log)

    def on_wedge(count: int) -> None:
        if not guard.is_starting():
            guard.respawn(world.spawn)
        watchdog.rearm()

    watchdog = HealthWatchdog(world.answering, on_wedge, guard.mark_healthy)
    guard.respawn(world.spawn)
    for _ in range(30):
        world.now += 60.0
        watchdog.tick()
        assert len(world.alive) == 1

    assert world.answering()
    assert len(world.stopped) == 1  # cut once at 300 s, the 600 s window let it finish
    assert watchdog.state is WatchState.HEALTHY
