import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW
from tests.e2e._tray_harness import make_stub_venv, resolve_tray_lifecycle_path

ROOT = Path(__file__).resolve().parents[1]
# Fleet convention: always the absolute PowerShell 5.1 path, never `shutil.which`
# (global-CLAUDE.md "Windows PowerShell in spawned commands"; matches
# tests/e2e/_tray_harness.py's own POWERSHELL constant).
POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


def _active_batch_lines() -> list[str]:
    lines = []
    for line in (ROOT / "tray.bat.template").read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.upper().startswith("REM "):
            continue
        lines.append(stripped)
    return lines


def test_tray_template_delegates_lifecycle_to_one_call_per_path() -> None:
    """One launcher call, and no plain `-File` line that AllSigned would refuse."""
    lines = _active_batch_lines()
    launcher = [line for line in lines if "-m src.ps_script" in line]

    assert len(launcher) == 1
    # With the trailing space: `Start-Process -FilePath` is not a script launch.
    assert not any(" -File " in line for line in lines)
    # The launcher's command line stops at the action: the helper matches running trays by
    # command line, so TRAY_LAUNCH on it would make the launcher look like the tray (#1003).
    assert launcher[0].endswith('-m src.ps_script "%TRAY_PS%" launch')


def test_tray_template_never_sets_an_execution_policy() -> None:
    text = " ".join(_active_batch_lines()).lower()

    assert "-executionpolicy" not in text and "set-executionpolicy" not in text


def test_tray_template_does_not_parse_detect_output_with_for_f() -> None:
    active_lines = [line.lower() for line in _active_batch_lines()]

    assert not any(line.startswith("for /f") for line in active_lines)
    assert not any("usebackq" in line for line in active_lines)


_STUB_PARAMS = (
    "[CmdletBinding()]\n"
    "param([Parameter(Position=0)][string]$Action, [string]$AppName,\n"
    " [string]$ScriptDir, [string]$VenvDir, [string]$TrayMatch,\n"
    " [string]$Ports, [string]$TrayLaunch, [string]$VersionUrl, [switch]$Restart)\n"
)
_ECHO_ARGS = (
    'Write-Output "ACTION=$Action"\n'
    'Write-Output "SCRIPTDIR=$ScriptDir"\n'
    'Write-Output "TRAYMATCH=$TrayMatch"\n'
    'Write-Output "TRAYLAUNCH=$TrayLaunch"\n'
    'Write-Output "PORTS=$Ports"\n'
    'Write-Output "RESTART=$($Restart.IsPresent)"\n'
)


def _make_app(tmp_path: Path, helper_body: str, *, venv: bool = True) -> dict[str, str]:
    """A throwaway app with the filled template and a stub helper; returns its environment.

    The template resolves the helper at %USERPROFILE%/.claude/tray/tray_lifecycle.ps1
    (project-scaffolding#153), so the stub lives under a fake home. With ``venv`` the app also
    gets a stub `.venv` and the vendored launcher, as a real adopter has.
    """
    probe = tmp_path / "_home" / ".claude" / "tray" / "tray_lifecycle.ps1"
    probe.parent.mkdir(parents=True)
    probe.write_text(_STUB_PARAMS + helper_body, encoding="utf-8")

    batch = (ROOT / "tray.bat.template").read_text(encoding="utf-8")
    batch = (
        batch.replace("__APP_NAME__", "ProbeApp")
        .replace("__TRAY_LAUNCH__", "-m app.tray")
        .replace("__TRAY_MATCH__", r"-m\s+app\.tray")
        .replace("__OWNED_PORTS__", "8445")
    )
    (tmp_path / "tray.bat").write_text(batch, encoding="utf-8")
    if venv:
        make_stub_venv(tmp_path / ".venv")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").write_text("", encoding="utf-8")
        shutil.copy2(ROOT / "src" / "ps_script.py", tmp_path / "src" / "ps_script.py")

    env = {k: v for k, v in os.environ.items() if k.upper() != "APP_NAME"}
    env["USERPROFILE"] = str(tmp_path / "_home")
    return env


def _run_bat(
    tmp_path: Path, env: dict[str, str], *args: str, policy: str | None = None
) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    """Run the app's tray.bat, from a child PowerShell under *policy* when one is given.

    ``-ExecutionPolicy`` sets that child's process scope only, which the processes it starts
    inherit; no machine or user setting is touched.
    """
    bat = tmp_path / "tray.bat"
    if policy is None:
        argv = ["cmd", "/c", str(bat), *args]
    else:
        command = f"& '{bat}' {' '.join(args)}; exit $LASTEXITCODE"
        argv = [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", policy, "-Command", command]
    result = subprocess.run(
        argv, check=False, capture_output=True, text=True, errors="replace", timeout=120,
        cwd=str(tmp_path), env=env, creationflags=NO_WINDOW,
    )
    out = dict(
        line.split("=", 1)
        for line in result.stdout.splitlines()
        if "=" in line and line.split("=", 1)[0].isupper()
    )
    return result, out


@pytest.mark.skipif(sys.platform != "win32", reason="tray lifecycle is Windows-only")
def test_tray_template_launch_args_survive_argv_parsing(tmp_path: Path) -> None:
    """The template must deliver every switch intact to the helper (#145).

    `%~dp0` ends in a backslash, and Windows argv parsing treats an odd run of
    backslashes before a closing quote as escaping it. Passing `-ScriptDir
    "%SCRIPT_DIR%"` therefore swallows the rest of the command line, so
    `-TrayMatch` and `-Ports` reach the helper EMPTY: detect matches nothing,
    reclaim reclaims nothing, and `--restart` degrades to the adopt-the-stale-
    build start the whole template exists to prevent. Grepping the batch text
    cannot catch that, so drive the real template through a real `cmd` + real
    PowerShell and read the parsed values back.
    """
    assert Path(POWERSHELL).exists(), f"expected PowerShell at {POWERSHELL}"
    env = _make_app(tmp_path, _ECHO_ARGS)

    result, out = _run_bat(tmp_path, env)

    # The two switches that follow -ScriptDir are the ones a swallowed quote eats.
    assert out.get("TRAYMATCH") == r"-m\s+app\.tray", result.stdout + result.stderr
    assert out.get("PORTS") == "8445", result.stdout
    assert out.get("ACTION") == "launch", result.stdout
    assert out.get("TRAYLAUNCH") == "-m app.tray", result.stdout
    assert out.get("RESTART") == "False", result.stdout
    # ScriptDir still arrives, just without the trailing separator.
    assert out.get("SCRIPTDIR", "").rstrip("\\") == str(tmp_path).rstrip("\\")
    assert not out.get("SCRIPTDIR", "x").endswith("\\")


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="tray lifecycle is Windows-only")
@pytest.mark.parametrize(("policy", "method"), [("AllSigned", "ScriptBlock"), ("RemoteSigned", "-File")])
@pytest.mark.parametrize("restart", [False, True], ids=["start", "restart"])
def test_tray_template_reaches_the_helper_under_the_policy(
    tmp_path: Path, policy: str, method: str, restart: bool
) -> None:
    """Start and --restart both enter the helper, and say which launch they used (#1003)."""
    env = _make_app(tmp_path, _ECHO_ARGS)
    # A switch left in the caller's environment must not turn a plain start into a restart.
    env["PSL_SWITCH_Restart"] = "1"

    result, out = _run_bat(tmp_path, env, *(["--restart"] if restart else []), policy=policy)

    assert result.returncode == 0, result.stdout + result.stderr
    assert out.get("ACTION") == "launch", result.stdout + result.stderr
    assert out.get("RESTART") == str(restart), result.stdout
    assert f"PowerShell launch: {method} for tray_lifecycle.ps1" in result.stdout + result.stderr


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="tray lifecycle is Windows-only")
@pytest.mark.parametrize(
    "body", ["throw 'helper broke'\n", "exit 5\n", "function {\n"], ids=["throws", "exits", "unparsable"]
)
def test_tray_template_restart_fails_when_the_helper_does(tmp_path: Path, body: str) -> None:
    """A --restart the helper could not carry out is a non-zero exit, never a plain start."""
    env = _make_app(tmp_path, body)

    result, _ = _run_bat(tmp_path, env, "--restart", policy="AllSigned")

    assert result.returncode != 0, result.stdout + result.stderr
    assert "starting the ProbeApp tray standalone" not in result.stdout


@pytest.mark.windows_only
@pytest.mark.skipif(sys.platform != "win32", reason="tray lifecycle is Windows-only")
@pytest.mark.parametrize("policy", ["AllSigned", "RemoteSigned"])
@pytest.mark.parametrize("restart", [False, True], ids=["start", "restart"])
@pytest.mark.parametrize("helper", [True, False], ids=["helper", "no-helper"])
def test_tray_template_without_a_venv_names_setup_bat(
    tmp_path: Path, policy: str, restart: bool, helper: bool
) -> None:
    """No `.venv`: exit non-zero, name `setup.bat`, start no PowerShell script."""
    env = _make_app(tmp_path, 'Write-Output "HELPER=ran"\n', venv=False)
    if not helper:
        (tmp_path / "_home" / ".claude" / "tray" / "tray_lifecycle.ps1").unlink()

    result, out = _run_bat(tmp_path, env, *(["--restart"] if restart else []), policy=policy)

    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "setup.bat" in result.stdout, output
    assert "HELPER" not in out, output
    assert "PowerShell launch" not in output and "digitally signed" not in output, output


@pytest.mark.skipif(sys.platform != "win32", reason="tray lifecycle is Windows-only")
def test_tray_template_does_not_leak_app_name_to_children(tmp_path: Path) -> None:
    """The template must not hand a bare `APP_NAME` to the tray it starts (#264).

    `setlocal` scopes a variable away from the *calling* console only; every
    process tray.bat launches still inherits it. A bare `APP_NAME` then rode the
    whole tray -> service chain into every session and app that service spawns,
    where another project reads `APP_NAME` as its own config key
    (ferraroroberto/app-launcher#963). The usual restart route is an agent in a
    session that already carries the leaked value, so the caller presets it:
    the template must clear it, not merely stop setting it. The stub helper
    records the environment it inherited plus its `-AppName` argument.
    """
    assert Path(POWERSHELL).exists(), f"expected PowerShell at {POWERSHELL}"
    env = _make_app(
        tmp_path,
        "$state = if (Test-Path Env:APP_NAME) { 'present:' + $env:APP_NAME } else { 'absent' }\n"
        'Write-Output "APPNAMEENV=$state"\n'
        'Write-Output "APPNAMEARG=$AppName"\n',
    )
    env["APP_NAME"] = "LeakedFromCaller"

    result, out = _run_bat(tmp_path, env)

    assert out.get("APPNAMEENV") == "absent", result.stdout + result.stderr
    # The display name still reaches the lifecycle helper as its argument.
    assert out.get("APPNAMEARG") == "ProbeApp", result.stdout + result.stderr


def test_tray_template_is_ascii_only() -> None:
    """A non-ASCII byte anywhere in the template corrupts non-interactive
    --restart (#183).

    The template opens with `chcp 65001`, switching the console codepage
    mid-file. cmd.exe read-ahead-buffers a chunk of the batch file for parsing
    at the codepage active when the buffer was filled, so a multi-byte UTF-8
    character anywhere in that pre-fetch window (REM comments included) gets
    misparsed once the switch lands, throwing spurious `'X' is not recognized
    as an internal or external command` errors on unrelated later lines.
    Removing every non-ASCII byte is the fix; this guard stops one creeping
    back in. (The whole file, not just active lines: cmd's read-ahead buffers
    REM comments too.)
    """
    raw = (ROOT / "tray.bat.template").read_bytes()
    offenders = [offset for offset, byte in enumerate(raw) if byte > 0x7F]
    assert not offenders, (
        "tray.bat.template must be ASCII-only (#183); "
        f"non-ASCII bytes at offsets {offenders}"
    )


def test_tray_lifecycle_helper_contains_restart_verification() -> None:
    helper = resolve_tray_lifecycle_path().read_text(encoding="utf-8")

    assert "[ValidateSet('detect', 'reclaim', 'launch')]" in helper
    assert "Wait-RestartedAndServingHead" in helper
    assert "git_sha" in helper
    assert "Invoke-RestMethod" in helper


def test_tray_lifecycle_verify_probes_https_over_loopback() -> None:
    """The verify leg must reach an HTTPS PWA over loopback (#147).

    A fleet PWA serves HTTPS under a leaf for its public name (Tailscale /
    self-signed CA), never for 127.0.0.1, and `/api/version` is auth-gated off
    loopback. So the probe must (a) try https on 127.0.0.1 by default, not just
    http, and (b) skip cert validation — but ONLY for loopback, via a compiled
    delegate (a PowerShell scriptblock callback throws "no Runspace" on .NET's
    TLS thread). Guard both, and guard that the bypass is not a blanket disable.
    """
    helper = resolve_tray_lifecycle_path().read_text(encoding="utf-8")

    # https attempted on loopback by default (not only when -VersionUrl is set).
    assert "https://127.0.0.1:" in helper
    # cert bypass is a COMPILED type, not a scriptblock callback.
    assert "Add-Type" in helper
    assert "class LoopbackCertBypass" in helper
    # …and it is SCOPED to loopback — a blanket `{ $true }` / unconditional
    # `return true` would trust every host and is the regression to prevent.
    assert "IsLoopback" in helper
    assert 'h == "127.0.0.1"' in helper
    # the previous callback is restored, so the bypass doesn't leak process-wide.
    assert "Restore" in helper
    # Non-loopback must fall through to normal validation, not a bare reject
    # (#151): the callback REPLACES .NET's own chain validation, so returning a
    # hardcoded `false` off-loopback rejects perfectly valid remote certs too.
    assert "e == SslPolicyErrors.None" in helper
    assert "return r != null && IsLoopback(r.RequestUri.Host);" not in helper


@pytest.mark.skipif(sys.platform != "win32", reason="tray lifecycle is Windows-only")
def test_resolve_versionurls_returns_flat_string_list(tmp_path: Path) -> None:
    """An explicit -VersionUrl must yield a flat list of strings, not a nested
    array (#149).

    `return , @($VersionUrl)` applies the unary comma to something already an
    array, double-wrapping it; the probe then hands Invoke-RestMethod a
    string[] and throws "Cannot convert System.Object[] to System.Uri" — so
    `--restart` exits 1 on a fully successful restart, for every app that sets
    an explicit VERSION_URL. Only the explicit path is affected (the default
    multi-URL path is a genuine 2-element array), so this drives the real
    function with an explicit URL and asserts each element is a plain string.
    """
    assert Path(POWERSHELL).exists(), f"expected PowerShell at {POWERSHELL}"

    # Source only the helper's functions (strip its param() header and trailing
    # switch dispatcher), bind the script-scope inputs, then print the type of
    # each Resolve-VersionUrls element for an explicit -VersionUrl.
    harness = tmp_path / "probe.ps1"
    harness.write_text(
        f"$raw = Get-Content -Raw '{resolve_tray_lifecycle_path().as_posix()}'\n"
        "$body = $raw.Substring($raw.IndexOf('function Test-UnderVenv'))\n"
        "$body = $body.Substring(0, $body.IndexOf('switch ($Action)'))\n"
        "$VersionUrl = 'http://127.0.0.1:8000/admin/api/version'\n"
        ". ([ScriptBlock]::Create($body))\n"
        "$urls = @(Resolve-VersionUrls)\n"
        "$urls | ForEach-Object { Write-Output ($_.GetType().Name) }\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(harness)],
        check=False, capture_output=True, text=True, creationflags=NO_WINDOW,
    )
    types = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    assert types == ["String"], f"expected one String element, got {types}: {result.stdout}{result.stderr}"


@pytest.mark.skipif(sys.platform != "win32", reason="tray lifecycle is Windows-only")
def test_tray_lifecycle_helper_parses_on_windows(tmp_path: Path) -> None:
    assert Path(POWERSHELL).exists(), f"expected PowerShell at {POWERSHELL}"

    helper = resolve_tray_lifecycle_path()
    result = subprocess.run(
        [
            POWERSHELL,
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
        creationflags=NO_WINDOW,
    )

    assert result.returncode == 0, result.stderr
