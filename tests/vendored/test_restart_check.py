"""The vendored shell-neutral restart: started by absolute path, never a bare name.

A bare ``tray.bat`` is found by no shell on a host that sets
``NoDefaultCurrentDirectoryInExePath``, and Git Bash ``cmd.exe /c`` exits 0 without
entering the script. These tests pin that ``restart`` starts the bat by its full path and
that it exits non-zero unless a different process serves ``HEAD``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from src import restart_check
from src.no_window import NO_WINDOW
from src.restart_check import EXIT_FAILED, EXIT_NOT_CONFIRMED, EXIT_OK, decide

HEAD = "abc1234"
OLD = {"git_sha": HEAD, "pid": 100, "built_at": "2026-01-01T10:00:00"}


class _Run:
    """Stands in for ``subprocess.run`` and records the call."""

    def __init__(
        self, returncode: int = 0, raises: BaseException | None = None, output: bytes | None = None,
    ) -> None:
        self.returncode = returncode
        self.raises = raises
        self.output = output
        self.calls: list[tuple[list[str], dict[str, Any]]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
        self.calls.append((argv, kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.output)


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


def test_failing_bat_leaves_its_last_output_lines_in_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str], synthetic_host: Any,
) -> None:
    home = str(synthetic_host.home)
    lines = [f"step {n}" for n in range(40)] + [f"ERROR cannot open {home}/app/tray.log", "", "tray start failed"]
    run = _Run(returncode=1, output="\r\n".join(lines).encode("utf-8"))
    with caplog.at_level("INFO", logger="restart_check"):
        assert _restart(tmp_path, run, [OLD, {**OLD, "pid": 200}]) == EXIT_FAILED
    text = caplog.text
    assert "tray.bat exited 1" in text
    assert "tray start failed" in text and "step 39" in text
    assert "step 0" not in text and "step 20" not in text  # bounded to the tail
    tail = [r.getMessage() for r in caplog.records if r.getMessage().startswith("   |")]
    assert tail and all(home not in line for line in tail) and "   | ERROR cannot open ~/app/tray.log" in tail
    assert "step 0" in capsys.readouterr().out  # the caller still sees the whole output


def test_failing_bat_with_no_output_says_its_error_is_unknown(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("INFO", logger="restart_check"):
        assert _restart(tmp_path, _Run(returncode=1), [OLD]) == EXIT_FAILED
    assert "wrote no output" in caplog.text


def test_hung_bat_keeps_the_output_it_wrote_before_the_timeout(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    hung = subprocess.TimeoutExpired("tray.bat", 180, output=b"waiting for port 8080\r\n")
    with caplog.at_level("INFO", logger="restart_check"):
        assert _restart(tmp_path, _Run(raises=hung), [OLD]) == EXIT_FAILED
    assert "waiting for port 8080" in caplog.text


def test_successful_restart_passes_output_through_and_logs_no_tail(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str],
) -> None:
    run = _Run(output=b"starting tray\r\ntray up\r\n")
    with caplog.at_level("INFO", logger="restart_check"):
        assert _restart(tmp_path, run, [OLD, {**OLD, "pid": 200}]) == EXIT_OK
    assert "tray up" in capsys.readouterr().out
    assert "tray.bat output" not in caplog.text and "verify OK" in caplog.text


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


class _Resp:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _Resp:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _record_urls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    urls: list[str] = []

    def urlopen(url: str, **_kwargs: Any) -> _Resp:
        urls.append(url)
        return _Resp(b'{"git_sha": "abc1234", "pid": 7}')

    monkeypatch.setattr(restart_check.urllib.request, "urlopen", urlopen)
    return urls


def test_fetch_version_defaults_to_api_version(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = _record_urls(monkeypatch)
    assert restart_check.fetch_version(8080) == {"git_sha": HEAD, "pid": 7}
    assert urls == ["https://127.0.0.1:8080/api/version"]


def test_fetch_version_reads_a_named_path(monkeypatch: pytest.MonkeyPatch) -> None:
    urls = _record_urls(monkeypatch)
    assert restart_check.fetch_version(8000, "/admin/api/version") == {"git_sha": HEAD, "pid": 7}
    assert urls == ["https://127.0.0.1:8000/admin/api/version"]


def test_restart_probes_the_named_version_path_before_and_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both the snapshot and the verify poll read ``version_path``, not the default."""
    urls = _record_urls(monkeypatch)
    answers = iter([{"git_sha": HEAD, "pid": 1}, {"git_sha": HEAD, "pid": 2}])
    monkeypatch.setattr(restart_check, "resolve_git_sha", lambda _root: HEAD)
    monkeypatch.setattr(
        restart_check.urllib.request, "urlopen",
        lambda url, **_k: urls.append(url) or _Resp(json.dumps(next(answers)).encode()),
    )
    code = restart_check.restart(
        8000, 5.0, tray_bat=_bat(tmp_path), run=_Run(), version_path="/admin/api/version",
    )
    assert code == EXIT_OK
    assert urls == ["https://127.0.0.1:8000/admin/api/version"] * 2


def test_cli_passes_version_path_through(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    def fake_restart(port: int, timeout_s: float, **kwargs: Any) -> int:
        seen.update(port=port, timeout_s=timeout_s, **kwargs)
        return EXIT_OK

    monkeypatch.setattr(restart_check, "restart", fake_restart)
    assert restart_check.main(["restart", "--port", "8000", "--version-path", "/admin/api/version"]) == EXIT_OK
    assert seen["version_path"] == "/admin/api/version"
    assert restart_check.main(["restart", "--port", "8000"]) == EXIT_OK
    assert seen["version_path"] == "/api/version"


def test_cli_rejects_a_version_path_without_a_leading_slash() -> None:
    with pytest.raises(SystemExit) as exc:
        restart_check.main(["restart", "--port", "8000", "--version-path", "admin/api/version"])
    assert exc.value.code == 2


def test_ok_line_survives_a_console_that_cannot_encode_emoji() -> None:
    """A cp1252 stdout must still carry the OK line, with no logging traceback."""
    child = (
        "import sys\n"
        "from src import restart_check\n"
        "restart_check.restart = lambda *a, **k: (restart_check._log.info('✅ verify OK :1 new build'), 0)[1]\n"
        "sys.exit(restart_check.main(['restart', '--port', '1']))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", child],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "PYTHONIOENCODING": "cp1252", "PYTHONUTF8": "0"},
        capture_output=True, timeout=60, creationflags=NO_WINDOW,
    )
    assert done.returncode == 0
    assert b"verify OK" in done.stdout
    assert b"Traceback" not in done.stderr and b"UnicodeEncodeError" not in done.stderr
