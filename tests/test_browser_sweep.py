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
    exited: bool = False,
    parent_alive: bool = False,
    cwd: str | None = r"E:\automation\demo-wt-1",
) -> sweep.HelperProcess:
    """A running, orphaned, in-scope helper — the kill-nominated baseline."""
    return sweep.HelperProcess(
        pid=pid, ppid=ppid, name=name, exited=exited, parent_alive=parent_alive, cwd=cwd
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
    assert sweep.classify(_helper(exited=True), SCOPE) == sweep.VERDICT_ZOMBIE


def test_zombie_wins_over_every_other_signal() -> None:
    entry = _helper(exited=True, parent_alive=True, cwd=None)
    assert sweep.classify(entry, SCOPE) == sweep.VERDICT_ZOMBIE


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
        processes=[_helper(), _helper(pid=1, exited=True)],
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
            exited=False,
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
