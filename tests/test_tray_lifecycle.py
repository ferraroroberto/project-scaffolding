import os
import shutil
import subprocess
import sys
from pathlib import Path

from tests.e2e._tray_harness import resolve_tray_lifecycle_path

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


def test_tray_template_launch_args_survive_argv_parsing(tmp_path: Path) -> None:
    """The template's launch line must deliver every switch intact (#145).

    `%~dp0` ends in a backslash, and Windows argv parsing treats an odd run of
    backslashes before a closing quote as escaping it. Passing `-ScriptDir
    "%SCRIPT_DIR%"` therefore swallows the rest of the command line, so
    `-TrayMatch` and `-Ports` reach the helper EMPTY: detect matches nothing,
    reclaim reclaims nothing, and `--restart` degrades to the adopt-the-stale-
    build start the whole template exists to prevent. Grepping the batch text
    cannot catch that, so drive the real template through a real `cmd` + real
    `powershell -File` and read the parsed values back.
    """
    if sys.platform != "win32":
        return
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        return

    # project-scaffolding#153: the template resolves the helper at
    # %USERPROFILE%/.claude/tray/tray_lifecycle.ps1, not <ScriptDir>\app\tray\,
    # so the probe stub lives under a throwaway fake home and the subprocess
    # gets USERPROFILE pointed there -- same shape as tests/e2e/_tray_harness.py.
    fake_home = tmp_path / "_home"
    probe = fake_home / ".claude" / "tray" / "tray_lifecycle.ps1"
    probe.parent.mkdir(parents=True)
    probe.write_text(
        "param([Parameter(Position=0)][string]$Action, [string]$AppName,\n"
        " [string]$ScriptDir, [string]$VenvDir, [string]$TrayMatch,\n"
        " [string]$Ports, [string]$TrayLaunch, [string]$VersionUrl, [switch]$Restart)\n"
        "Write-Output \"ACTION=$Action\"\n"
        "Write-Output \"SCRIPTDIR=$ScriptDir\"\n"
        "Write-Output \"TRAYMATCH=$TrayMatch\"\n"
        "Write-Output \"PORTS=$Ports\"\n",
        encoding="utf-8",
    )

    batch = (ROOT / "tray.bat.template").read_text(encoding="utf-8")
    batch = (
        batch.replace("__APP_NAME__", "ProbeApp")
        .replace("__TRAY_LAUNCH__", "launcher.py tray")
        .replace("__TRAY_MATCH__", r"launcher\.py\s+tray")
        .replace("__OWNED_PORTS__", "8445")
    )
    (tmp_path / "tray.bat").write_text(batch, encoding="utf-8")

    env = dict(os.environ)
    env["USERPROFILE"] = str(fake_home)
    result = subprocess.run(
        ["cmd", "/c", str(tmp_path / "tray.bat")],
        check=False,
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        env=env,
    )
    out = dict(
        line.split("=", 1)
        for line in result.stdout.splitlines()
        if "=" in line and line.split("=", 1)[0].isupper()
    )

    # The two switches that follow -ScriptDir are the ones a swallowed quote eats.
    assert out.get("TRAYMATCH") == r"launcher\.py\s+tray", result.stdout
    assert out.get("PORTS") == "8445", result.stdout
    assert out.get("ACTION") == "launch", result.stdout
    # ScriptDir still arrives, just without the trailing separator.
    assert out.get("SCRIPTDIR", "").rstrip("\\") == str(tmp_path).rstrip("\\")
    assert not out.get("SCRIPTDIR", "x").endswith("\\")


def test_tray_lifecycle_helper_contains_restart_verification() -> None:
    helper = resolve_tray_lifecycle_path().read_text(encoding="utf-8")

    assert "[ValidateSet('detect', 'reclaim', 'launch')]" in helper
    assert "Wait-VersionMatchesHead" in helper
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
    if sys.platform != "win32":
        return
    powershell = shutil.which("powershell.exe")
    if powershell is None:
        return

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
        [powershell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(harness)],
        check=False, capture_output=True, text=True,
    )
    types = [ln.strip() for ln in result.stdout.splitlines() if ln.strip()]
    assert types == ["String"], f"expected one String element, got {types}: {result.stdout}{result.stderr}"


def test_tray_lifecycle_helper_parses_on_windows(tmp_path: Path) -> None:
    if sys.platform != "win32":
        return

    powershell = shutil.which("powershell.exe")
    if powershell is None:
        return

    helper = resolve_tray_lifecycle_path()
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
