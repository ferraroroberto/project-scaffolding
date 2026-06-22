import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _active_batch_lines() -> list[str]:
    lines = []
    for line in (ROOT / "tray.bat.template").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper().startswith("REM "):
            continue
        lines.append(stripped)
    return lines


def test_tray_template_delegates_lifecycle_to_one_powershell_call() -> None:
    calls = [
        line
        for line in _active_batch_lines()
        if "%PS%" in line and "-File" in line and "%TRAY_PS%" in line
    ]

    assert len(calls) == 1
    assert " launch " in calls[0]
    assert "-Restart" not in calls[0]
    assert "!RESTART_ARG!" in calls[0]


def test_tray_template_does_not_parse_detect_output_with_for_f() -> None:
    active_lines = [line.lower() for line in _active_batch_lines()]

    assert not any(line.startswith("for /f") for line in active_lines)
    assert not any("usebackq" in line for line in active_lines)


def test_tray_lifecycle_helper_contains_restart_verification() -> None:
    helper = (ROOT / "app" / "tray" / "tray_lifecycle.ps1").read_text(encoding="utf-8")

    assert "[ValidateSet('detect', 'reclaim', 'launch')]" in helper
    assert "Wait-VersionMatchesHead" in helper
    assert "git_sha" in helper
    assert "Invoke-RestMethod" in helper


def test_tray_lifecycle_helper_parses_on_windows(tmp_path: Path) -> None:
    if sys.platform != "win32":
        return

    powershell = shutil.which("powershell.exe")
    if powershell is None:
        return

    helper = ROOT / "app" / "tray" / "tray_lifecycle.ps1"
    result = subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(helper),
            "detect",
            "-VenvDir",
            str(tmp_path),
            "-TrayMatch",
            "definitely-not-this-tray",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
