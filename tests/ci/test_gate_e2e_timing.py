"""The gate leaves the e2e audit a timing source that outlives a worktree.

`.fleet.toml` `[e2e] junit_xml` names the report; the gate writes it on a
full-tier browser run and copies a green one to the primary checkout. The copy
helper (between the `e2e-timing` markers) is run for real in a throwaway repo
with a linked worktree.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW
from tests._git_repo import git

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
GATE = REPO_ROOT / "scripts" / "verify-before-ship.ps1"
POWERSHELL = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
REPORT = "data/logs/e2e-junit.xml"

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="the gate is a Windows PowerShell script")


def _gate_text() -> str:
    return GATE.read_text(encoding="utf-8").replace("\r\n", "\n")


def _timing_block() -> str:
    match = re.search(r"# e2e-timing:begin\n(.*?)# e2e-timing:end", _gate_text(), re.DOTALL)
    assert match, "the gate lost its e2e-timing block"
    return match.group(1)


def _publish(checkout: Path, **env: str) -> None:
    script = f'$ErrorActionPreference = "Stop"\n{_timing_block()}\nPublish-E2eJunit $e2eJunit\n'
    clean = {k: v for k, v in os.environ.items() if k != "E2E_JUNIT_PUBLISH" and not k.startswith("GIT_")}
    run = subprocess.run(
        [str(POWERSHELL), "-NoProfile", "-NonInteractive", "-Command", script], cwd=checkout,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, timeout=120, env={**clean, **env},
    )
    assert run.returncode == 0, run.stderr
    assert "[WARN]" not in run.stdout, run.stdout


def test_the_declared_report_is_the_one_the_gate_writes_on_a_full_run() -> None:
    declared = tomllib.loads((REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8"))["e2e"]["junit_xml"]
    assert declared == REPORT
    assert f'$e2eJunit = "{REPORT}"' in _timing_block()
    assert 'if ($tier -eq "full") { $e2eArgs += "--junitxml=$e2eJunit" }' in _gate_text()


@windows_only
def test_a_worktree_report_reaches_the_primary_checkout(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    git(primary, "init", "-q")
    # The machine's commit hooks are not under test.
    for setting in (f"core.hooksPath={tmp_path / 'no-hooks'}", "user.name=t", "user.email=t@example.invalid"):
        git(primary, "config", *setting.split("=", 1))
    git(primary, "commit", "-q", "--allow-empty", "-m", "i")
    worktree = tmp_path / "primary-wt-1"
    git(primary, "worktree", "add", "-q", str(worktree))
    report = worktree / REPORT
    report.parent.mkdir(parents=True)
    report.write_text("<testsuites/>", encoding="utf-8")

    _publish(worktree, E2E_JUNIT_PUBLISH="0")
    assert not (primary / REPORT).exists()

    _publish(worktree)
    assert (primary / REPORT).read_text(encoding="utf-8") == "<testsuites/>"
    assert [p.name for p in (primary / REPORT).parent.iterdir()] == ["e2e-junit.xml"]

    _publish(primary)  # the primary's own report is already in place
    assert (primary / REPORT).read_text(encoding="utf-8") == "<testsuites/>"
