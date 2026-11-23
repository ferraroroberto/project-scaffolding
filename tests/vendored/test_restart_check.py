"""The vendored shell-neutral restart: started by absolute path, never a bare name.

A bare ``tray.bat`` is found by no shell on a host that sets
``NoDefaultCurrentDirectoryInExePath``, and Git Bash ``cmd.exe /c`` exits 0 without
entering the script. These tests pin that ``restart`` starts the bat by its full path and
that it exits non-zero unless a different process serves ``HEAD``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from src import restart_check
from src.restart_check import EXIT_FAILED, EXIT_NOT_CONFIRMED, EXIT_OK, decide

HEAD = "abc1234"
OLD = {"git_sha": HEAD, "pid": 100, "built_at": "2026-01-01T10:00:00"}


class _Run:
    """Stands in for ``subprocess.run`` and records the call."""

    def __init__(self, returncode: int = 0, raises: BaseException | None = None) -> None:
        self.returncode = returncode
        self.raises = raises
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode)


def _bat(tmp_path: Path) -> Path:
    bat = tmp_path / "tray.bat"
    bat.write_text("@echo off\r\n", encoding="utf-8")
    return bat


def _restart(tmp_path: Path, run: _Run, answers: list[dict[str, Any] | None], timeout_s: float = 0.0) -> int:
    queue = list(answers)

    def fetch(_port: int) -> dict[str, Any] | None:
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def verify_fn(port: int, before: dict[str, Any] | None, timeout: float) -> int:
        return restart_check.verify(
            port, before, timeout, fetch=fetch, sleep=lambda _s: None, head_sha=HEAD,
            clock=iter(range(0, 1000)).__next__ if timeout_s else (lambda: 0.0),
        )

    return restart_check.restart(
        8080, timeout_s, tray_bat=_bat(tmp_path), run=run, fetch=fetch, verify_fn=verify_fn,
    )


def test_bat_is_started_by_absolute_path_not_a_shell_spelling(tmp_path: Path) -> None:
    run = _Run()
    assert _restart(tmp_path, run, [OLD, {**OLD, "pid": 200}]) == EXIT_OK
    argv, kwargs = run.calls[0]
    assert argv == [str((tmp_path / "tray.bat").resolve()), "--restart"]
    assert Path(argv[0]).is_absolute()
    assert Path(argv[0]).name == "tray.bat"
    assert kwargs["cwd"] == str(tmp_path.resolve())
    assert "shell" not in kwargs or kwargs["shell"] is False
    assert kwargs["timeout"] == restart_check.TRAY_RESTART_TIMEOUT_S


def test_default_bat_is_this_checkouts_tray_bat() -> None:
    assert restart_check.TRAY_BAT.is_absolute()
    assert restart_check.TRAY_BAT == Path(restart_check.__file__).resolve().parent.parent / "tray.bat"


def test_missing_bat_is_not_confirmed_and_runs_nothing(tmp_path: Path) -> None:
    run = _Run()
    code = restart_check.restart(8080, tray_bat=tmp_path / "tray.bat", run=run, fetch=lambda _p: OLD)
    assert code == EXIT_NOT_CONFIRMED
    assert run.calls == []


def test_old_process_still_serving_fails(tmp_path: Path) -> None:
    assert _restart(tmp_path, _Run(), [OLD, OLD]) == EXIT_FAILED


def test_bat_exiting_nonzero_fails_without_polling(tmp_path: Path) -> None:
    assert _restart(tmp_path, _Run(returncode=1), [OLD, {**OLD, "pid": 200}]) == EXIT_FAILED


@pytest.mark.parametrize("error", [OSError("not found"), subprocess.TimeoutExpired("tray.bat", 180)])
def test_bat_that_cannot_run_or_hangs_fails(tmp_path: Path, error: BaseException) -> None:
    assert _restart(tmp_path, _Run(raises=error), [OLD]) == EXIT_FAILED


def test_new_pid_serving_head_passes() -> None:
    assert decide(OLD, {**OLD, "pid": 200}, HEAD)[0] is True


def test_new_process_serving_an_old_build_fails() -> None:
    verdict, reason = decide(OLD, {**OLD, "pid": 200, "git_sha": "ffff000"}, HEAD)
    assert verdict is False and "expected HEAD" in reason


def test_same_pid_serving_head_fails() -> None:
    verdict, reason = decide(OLD, dict(OLD), HEAD)
    assert verdict is False and "same process" in reason


def test_built_at_tells_old_from_new_when_there_is_no_pid() -> None:
    before = {"git_sha": HEAD, "built_at": "2026-01-01T10:00:00"}
    assert decide(before, dict(before), HEAD)[0] is False
    assert decide(before, {**before, "built_at": "2026-01-01T10:05:00"}, HEAD)[0] is True


def test_no_identity_to_compare_is_not_a_pass() -> None:
    bare = {"git_sha": HEAD}
    verdict, reason = decide(bare, dict(bare), HEAD)
    assert verdict is None and "cannot be told" in reason


def test_nothing_answering_before_makes_any_answer_new() -> None:
    assert decide(None, {"git_sha": HEAD}, HEAD)[0] is True


def test_nothing_answering_after_is_a_failure() -> None:
    assert decide(OLD, None, HEAD)[0] is False


def test_unresolvable_head_is_not_a_pass() -> None:
    assert decide(OLD, {**OLD, "pid": 200}, "unknown")[0] is None


def test_unconfirmable_outcome_exits_not_confirmed_without_waiting(tmp_path: Path) -> None:
    bare = {"git_sha": HEAD}
    assert _restart(tmp_path, _Run(), [bare, bare]) == EXIT_NOT_CONFIRMED


@pytest.mark.windows_only
def test_real_bat_runs_by_absolute_path_from_another_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A real ``.bat`` is entered by its full path even when the bare name resolves nowhere."""
    marker = tmp_path / "entered.txt"
    bat = tmp_path / "tray.bat"
    bat.write_text(f'@echo off\r\necho %* > "{marker}"\r\nexit /b 0\r\n', encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    code = restart_check.restart(
        8080, tray_bat=bat, fetch=lambda _p: OLD,
        verify_fn=lambda *_a: EXIT_OK,
    )
    assert code == EXIT_OK
    assert marker.read_text(encoding="utf-8").strip() == "--restart"
