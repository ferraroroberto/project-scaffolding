"""The PowerShell launcher under an AllSigned execution policy (``src/ps_script.py``).

The policy runs set ``PSExecutionPolicyPreference``, the variable behind ``powershell
-ExecutionPolicy``: it sets the *process*-scope policy of that one process tree and touches no
machine or user setting.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src import ps_script
from src.no_window import NO_WINDOW

ROOT = Path(__file__).resolve().parents[2]
POWERSHELL = ps_script.POWERSHELL_EXE

# The shape of tray_lifecycle.ps1: CmdletBinding, one positional action, strings and a switch.
_PROBE = """\
[CmdletBinding()]
param([Parameter(Mandatory, Position = 0)][string] $Action,
    [string] $TrayLaunch, [string] $TrayMatch, [string] $Empty, [switch] $Restart)
$leaked = @(Get-ChildItem Env: | Where-Object { $_.Name -like 'PSL_*' }).Count
Write-Host "action=$Action launch=[$TrayLaunch] match=[$TrayMatch] empty=[$Empty]"
Write-Host "restart=$($Restart.IsPresent) leaked=$leaked root=[$PSScriptRoot]"
exit 7
"""


def _launch(
    script: Path, args: list[str], policy: str, extra: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith("PSL_")}
    env.update({"PSExecutionPolicyPreference": policy, "PYTHONPATH": str(ROOT)}, **(extra or {}))
    return subprocess.run(
        [sys.executable, "-m", "src.ps_script", str(script), *args],
        capture_output=True, text=True, errors="replace", timeout=120, cwd=ROOT, env=env,
        check=False, creationflags=NO_WINDOW,
    )


def _script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "dir with space" / "probe.ps1"
    path.parent.mkdir(exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.mark.parametrize("policy", ["bypass", "unrestricted", "remotesigned", "allsigned", "restricted", None])
def test_only_a_policy_that_runs_local_files_takes_the_file_launch(policy: str | None) -> None:
    argv, extra = ps_script.script_command("x.ps1", ["launch", "", "a b"], policy=policy)

    assert argv[:3] == [POWERSHELL, "-NoProfile", "-NonInteractive"]
    assert "-ExecutionPolicy" not in argv
    if policy in ("allsigned", "restricted", None):
        assert argv[3] == "-Command" and "-File" not in argv
        assert extra[ps_script.ENV_ARGV].split(chr(31))[1:] == ["launch", "", "a b"]
    else:
        assert argv[3:] == ["-File", "x.ps1", "launch", "", "a b"] and extra == {}


def test_environment_arguments_become_named_parameters_and_switches() -> None:
    environ = {
        "PSL_ARG_TRAYLAUNCH": "-m app.tray",
        "PSL_SWITCH_RESTART": "1",
        "PSL_SWITCH_OFF": "",
        "PSL_SCRIPT": "ignored.ps1",
        "PATH": "ignored",
    }

    assert ps_script.env_args(environ) == ["-TRAYLAUNCH", "-m app.tray", "-RESTART"]


def test_a_policy_probe_that_cannot_run_is_not_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> object:
        raise OSError("no powershell")

    monkeypatch.setattr(ps_script.subprocess, "run", boom)

    assert ps_script.effective_policy() is None


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")
def test_allsigned_refuses_a_plain_file_launch_and_the_launcher_runs_it(tmp_path: Path) -> None:
    probe = _script(tmp_path, _PROBE)
    control = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "AllSigned", "-File", str(probe)],
        capture_output=True, text=True, errors="replace", timeout=120, check=False, creationflags=NO_WINDOW,
    )
    assert control.returncode != 0 and "not digitally signed" in " ".join(control.stderr.split())

    # `-m app.tray` and `-m\s+tray` start with a dash and are values, not parameters.
    args = ["launch", "-TrayLaunch", "-m app.tray", "-TrayMatch", r"-m\s+tray", "-Empty", ""]
    done = _launch(probe, args, "AllSigned", {"PSL_SWITCH_Restart": "1"})

    assert done.returncode == 7, done.stdout + done.stderr
    assert r"action=launch launch=[-m app.tray] match=[-m\s+tray] empty=[]" in done.stdout
    assert f"restart=True leaked=0 root=[{probe.parent}]" in done.stdout
    assert "PowerShell launch: ScriptBlock" in done.stderr and "allsigned" in done.stderr


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")
def test_a_permissive_policy_keeps_the_file_launch(tmp_path: Path) -> None:
    probe = _script(tmp_path, _PROBE)

    done = _launch(probe, ["launch"], "RemoteSigned", {"PSL_ARG_TrayLaunch": "-m tray"})

    assert done.returncode == 7, done.stdout + done.stderr
    assert "action=launch launch=[-m tray]" in done.stdout
    assert "restart=False leaked=0" in done.stdout
    assert "PowerShell launch: -File" in done.stderr


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Windows PowerShell only")
@pytest.mark.parametrize(
    ("body", "args", "said"),
    [
        ("throw 'boom'\n", [], "boom"),
        ("function {\n", [], "Missing"),
        (_PROBE, ["launch", "-TrayMatch", "-Restart"], "Missing an argument"),
        (_PROBE, ["launch", "-NoSuchParameter"], "NoSuchParameter"),
    ],
    ids=["throws", "does-not-parse", "missing-value", "unknown-parameter"],
)
def test_a_script_it_cannot_run_exits_nonzero(
    tmp_path: Path, body: str, args: list[str], said: str
) -> None:
    done = _launch(_script(tmp_path, body), args, "AllSigned")

    assert done.returncode == 1, done.stdout + done.stderr
    assert said in done.stderr


# Runs inside a console of its own (hidden), runs the launcher there uncaptured, then reads the
# console's screen back: the only way to see what a person at a terminal would see.
_IN_CONSOLE = """import ctypes, os, subprocess, sys
from ctypes import wintypes
root, script, out = sys.argv[1:]
env = dict(os.environ, PSExecutionPolicyPreference="AllSigned", PYTHONPATH=root)
subprocess.run([sys.executable, "-m", "src.ps_script", script], cwd=root, env=env, check=False)
class Coord(ctypes.Structure):
    _fields_ = [("x", wintypes.SHORT), ("y", wintypes.SHORT)]
k = ctypes.windll.kernel32
k.CreateFileW.restype = wintypes.HANDLE
k.ReadConsoleOutputCharacterW.argtypes = [
    wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, Coord, ctypes.POINTER(wintypes.DWORD)]
screen = k.CreateFileW("CONOUT$", 0xC0000000, 3, None, 3, 0, None)
text = ctypes.create_unicode_buffer(4000)
k.ReadConsoleOutputCharacterW(screen, text, 4000, Coord(0, 0), ctypes.byref(wintypes.DWORD()))
open(out, "w", encoding="utf-8").write(text.value)
"""


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="Windows console only")
def test_the_script_output_reaches_a_real_console(tmp_path: Path) -> None:
    """`tray.bat --restart` typed in a terminal must show the helper's own lines."""
    probe = _script(tmp_path, "Write-Host 'LINE-FROM-THE-SCRIPT'\n")
    reader, screen = tmp_path / "in_console.py", tmp_path / "screen.txt"
    reader.write_text(_IN_CONSOLE, encoding="utf-8")
    hidden = subprocess.STARTUPINFO()
    hidden.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    hidden.wShowWindow = subprocess.SW_HIDE

    # no-window-exempt: the console is what is under test; STARTUPINFO keeps its window hidden.
    subprocess.run(
        [sys.executable, str(reader), str(ROOT), str(probe), str(screen)],
        creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=hidden, timeout=120, check=True,
    )

    assert "LINE-FROM-THE-SCRIPT" in screen.read_text(encoding="utf-8")


def test_a_missing_script_or_none_at_all_exits_nonzero(tmp_path: Path) -> None:
    assert ps_script.main([str(tmp_path / "gone.ps1")]) == 1
    assert ps_script.main([]) == 2
