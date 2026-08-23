"""Unit + integration coverage for the leaked-browser-helper sweep (#203).

The classification core is pure, so most of this drives `classify()` with
synthetic process rows. The two integration tests prove the parts that only
the OS can answer: that `enumerate_browser_helpers()` reads the real process
table without raising, and that a nominated process really is tree-killed.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from tests.e2e import _browser_sweep as sweep

WINDOWS_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="Windows-only sweep")


def _helper(
    *,
    pid: int = 4242,
    ppid: int = 111,
    name: str = "WebKitNetworkProcess.exe",
    state: str = sweep.STATE_RUNNING,
    parent_alive: bool = False,
    cwd: str | None = r"E:\automation\demo-wt-1",
) -> sweep.HelperProcess:
    """A running, orphaned, in-scope helper — the kill-nominated baseline."""
    return sweep.HelperProcess(
        pid=pid, ppid=ppid, name=name, state=state, parent_alive=parent_alive, cwd=cwd
    )


SCOPE = Path(r"E:\automation\demo-wt-1")


def test_running_orphan_in_scope_is_nominated_for_the_kill() -> None:
    assert sweep.classify(_helper(), SCOPE) == sweep.VERDICT_KILLED


def test_helper_in_a_subdirectory_of_the_scope_is_in_scope() -> None:
    assert sweep.classify(_helper(cwd=r"E:\automation\demo-wt-1\tests"), SCOPE) == (
        sweep.VERDICT_KILLED
    )


def test_already_exited_helper_is_a_zombie_never_a_kill() -> None:
    """An exited-but-handle-held process is unkillable, not a leak (#203)."""
    assert sweep.classify(_helper(state=sweep.STATE_EXITED), SCOPE) == sweep.VERDICT_ZOMBIE


def test_zombie_wins_over_every_other_signal() -> None:
    entry = _helper(state=sweep.STATE_EXITED, parent_alive=True, cwd=None)
    assert sweep.classify(entry, SCOPE) == sweep.VERDICT_ZOMBIE


# --------------------------------------------------------------------------- #
# #236: a process wedged inside termination is NOT a zombie. It reports a clean
# exit code, cannot be killed, and still holds its cwd — the one state that
# pins a directory, and the one the old `exited -> zombie` shortcut swallowed
# before cwd was ever consulted.
# --------------------------------------------------------------------------- #


def test_exit_code_with_a_recorded_exit_time_is_a_real_exit() -> None:
    assert sweep.liveness(0, 132_000_000_000_000_000) == sweep.STATE_EXITED


def test_exit_code_without_an_exit_time_is_wedged_not_exited() -> None:
    """The measured 39-helper case: Win32 says gone, the kernel never stamped it."""
    assert sweep.liveness(0, 0) == sweep.STATE_WEDGED


def test_still_active_is_running_whatever_the_exit_time_reads() -> None:
    assert sweep.liveness(sweep._STILL_ACTIVE, 0) == sweep.STATE_RUNNING


@pytest.mark.parametrize(
    ("exit_code", "exit_time"),
    [(None, None), (None, 0), (0, None)],
    ids=["no-handle", "no-exit-code", "unreadable-times"],
)
def test_an_unestablished_liveness_is_unknown_never_a_guess(
    exit_code: int | None, exit_time: int | None
) -> None:
    assert sweep.liveness(exit_code, exit_time) == sweep.STATE_UNKNOWN


def test_wedged_helper_in_scope_is_reported_as_pinning_it() -> None:
    """The leak the sweep exists to catch, and used to classify as harmless."""
    entry = _helper(state=sweep.STATE_WEDGED)
    assert sweep.classify(entry, SCOPE) == sweep.VERDICT_WEDGED_PINNING


def test_wedged_helper_elsewhere_is_reported_but_not_against_this_scope() -> None:
    entry = _helper(state=sweep.STATE_WEDGED, cwd=r"C:\Users\demo\AppData\Local\Temp")
    assert sweep.classify(entry, SCOPE) == sweep.VERDICT_WEDGED_ELSEWHERE


def test_wedged_helper_with_an_unreadable_cwd_is_its_own_unknown() -> None:
    entry = _helper(state=sweep.STATE_WEDGED, cwd=None)
    assert sweep.classify(entry, SCOPE) == sweep.VERDICT_WEDGED_CWD_UNKNOWN


def test_unknown_liveness_is_never_folded_into_zombie_or_a_kill() -> None:
    entry = _helper(state=sweep.STATE_UNKNOWN)
    assert sweep.classify(entry, SCOPE) == sweep.VERDICT_STATE_UNKNOWN


def test_a_wedged_helper_is_never_nominated_for_a_kill() -> None:
    """Nothing can reap a wedge; a sweep that tries reports a phantom success."""
    result = sweep.sweep_browser_helpers(
        SCOPE, processes=[_helper(state=sweep.STATE_WEDGED)]
    )
    assert result.killed == ()
    assert len(result.pinning_scope) == 1


def test_summary_shouts_when_a_wedge_pins_the_scope() -> None:
    """The gate stays green, but the reader must be told why removal will fail."""
    result = sweep.sweep_browser_helpers(
        SCOPE, dry_run=True, processes=[_helper(state=sweep.STATE_WEDGED)]
    )
    summary = result.summary()
    assert "wedged:pins-scope=1" in summary
    assert "PIN this scope" in summary
    assert len(result.wedged) == 1


def test_main_exits_nonzero_when_the_scope_is_pinned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`main` is a `git worktree remove` preflight — a pin means it will fail."""
    monkeypatch.setattr(
        sweep,
        "enumerate_browser_helpers",
        lambda *a, **k: [_helper(state=sweep.STATE_WEDGED)],
    )
    monkeypatch.setattr(sweep.sys, "platform", "win32")
    assert sweep.main([str(SCOPE), "--dry-run"]) == 1
    assert sweep.main([r"E:\automation\demo-wt-2", "--dry-run"]) == 0


def test_live_parent_is_never_killed() -> None:
    """A live parent means an in-flight session — someone else's browser."""
    assert sweep.classify(_helper(parent_alive=True), SCOPE) == sweep.VERDICT_PARENT_ALIVE


def test_unreadable_cwd_reports_unknown_rather_than_killing() -> None:
    assert sweep.classify(_helper(cwd=None), SCOPE) == sweep.VERDICT_CWD_UNKNOWN


def test_sibling_checkout_is_out_of_scope() -> None:
    """A sibling worktree must never be swept by this run's scope."""
    assert sweep.classify(_helper(cwd=r"E:\automation\demo-wt-2"), SCOPE) == (
        sweep.VERDICT_OUT_OF_SCOPE
    )


def test_prefix_lookalike_path_is_out_of_scope() -> None:
    """`demo-wt-11` shares a string prefix with `demo-wt-1` but is a different tree."""
    assert sweep.classify(_helper(cwd=r"E:\automation\demo-wt-11"), SCOPE) == (
        sweep.VERDICT_OUT_OF_SCOPE
    )


def test_path_is_within_rejects_empty_and_none() -> None:
    assert sweep.path_is_within(None, SCOPE) is False
    assert sweep.path_is_within("", SCOPE) is False


def test_dry_run_classifies_without_killing() -> None:
    result = sweep.sweep_browser_helpers(SCOPE, dry_run=True, processes=[_helper()])
    assert [entry.verdict for entry in result.entries] == [sweep.VERDICT_KILLED]
    assert result.supported is True


def test_summary_reports_a_verdict_breakdown() -> None:
    result = sweep.sweep_browser_helpers(
        SCOPE,
        dry_run=True,
        processes=[_helper(), _helper(pid=1, state=sweep.STATE_EXITED)],
    )
    summary = result.summary()
    assert "killed=1" in summary
    assert "zombie=1" in summary
    assert len(result.zombies) == 1


def test_unsupported_platform_reports_unknown_not_clean() -> None:
    """`supported=False` must read as *unknown*, never as a clean bill."""
    result = sweep.SweepResult(supported=False, scope=str(SCOPE), entries=())
    assert "UNKNOWN" in result.summary()
    assert "no helper processes" not in result.summary()


@WINDOWS_ONLY
def test_enumerating_the_real_process_table_never_raises() -> None:
    helpers = sweep.enumerate_browser_helpers()
    assert all(isinstance(helper, sweep.HelperProcess) for helper in helpers)
    for helper in helpers:
        assert helper.pid > 0
        assert helper.state in {
            sweep.STATE_RUNNING,
            sweep.STATE_EXITED,
            sweep.STATE_WEDGED,
            sweep.STATE_UNKNOWN,
        }


@WINDOWS_ONLY
@pytest.mark.slow
def test_real_process_liveness_probes_agree_with_the_os(tmp_path: Path) -> None:
    """Drive `liveness` off the real Win32 probes, live then genuinely dead (#236).

    The wedged case cannot be manufactured (it is a teardown race), but the
    *false-positive* direction can be closed here: a process that really did
    exit must keep reading `STATE_EXITED` while its handle is held, or every
    ordinary zombie would start reporting as an unreapable pin.
    """
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        cwd=tmp_path,
        creationflags=sweep.NO_WINDOW,
    )
    try:
        assert sweep.liveness(sweep._exit_code(child.pid), None) == sweep.STATE_RUNNING
        assert sweep._exit_time(child.pid) == 0, "a live process has no exit time"

        child.kill()
        child.wait(timeout=10)
        # `child` still holds the process handle, so the object survives —
        # exactly the zombie shape #203 measured.
        code = sweep._exit_code(child.pid)
        exit_time = sweep._exit_time(child.pid)
        assert code is not None and code != sweep._STILL_ACTIVE
        assert exit_time is not None and exit_time > 0, (
            "a genuinely-exited process must carry a recorded exit time; without "
            "one the discriminator would call every zombie a wedge"
        )
        assert sweep.liveness(code, exit_time) == sweep.STATE_EXITED
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)


@WINDOWS_ONLY
@pytest.mark.slow
def test_sweep_really_kills_a_nominated_process(tmp_path: Path) -> None:
    """Prove the kill leg end to end against a real (harmless) OS process."""
    child = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        cwd=tmp_path,
        creationflags=sweep.NO_WINDOW,
    )
    try:
        nominated = sweep.HelperProcess(
            pid=child.pid,
            ppid=1,
            name="WebKitNetworkProcess.exe",
            state=sweep.STATE_RUNNING,
            parent_alive=False,
            cwd=str(tmp_path),
        )
        result = sweep.sweep_browser_helpers(tmp_path, processes=[nominated])

        assert [entry.verdict for entry in result.entries] == [sweep.VERDICT_KILLED]
        deadline = time.monotonic() + 10
        while child.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
        assert child.poll() is not None, "sweep reported a kill but the process is alive"
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
