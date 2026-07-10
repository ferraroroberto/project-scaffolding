"""Behavioral e2e harness for the vendored tray lifecycle (project-scaffolding#152).

Drives the REAL `app/tray/tray_lifecycle.ps1` through a real `tray.bat`,
materialized from the real `tray.bat.template`, against a dummy stdlib
HTTP(S) app (`_dummy_tray_app.py`) -- cold start, idempotent relaunch,
`--restart` after a new commit (asserting the NEW git_sha is actually
served, not a stale adopt), the non-interactive nested-shell invocation
path that historically failed silently (#54/#144), and an HTTPS loopback
variant with a self-signed cert (#147/#148).

This complements -- does not replace -- `tests/test_tray_lifecycle.py`,
which stays the fast, string/grep-level regression suite for the same four
July bugs. These tests are marked `slow` because they spawn and kill real
Windows processes; see `_tray_harness.py` for the shared plumbing.
"""

from __future__ import annotations

import sys

import pytest

from tests.e2e import _tray_harness as harness

pytestmark = [
    pytest.mark.skipif(sys.platform != "win32", reason="tray lifecycle is Windows-only"),
    pytest.mark.slow,
]


@pytest.fixture(autouse=True)
def _bound_default_timeouts() -> None:
    """Shadow tests/e2e/conftest.py's same-named autouse fixture.

    That fixture takes the Playwright `page` fixture, which would force a
    real browser launch (and a `[chromium]` parametrization) onto every test
    in this module even though none of them touch a browser -- this suite
    drives real OS processes, not a page.
    """
    return None


@pytest.fixture
def env(tmp_path):
    e = harness.build_env(tmp_path)
    try:
        yield e
    finally:
        harness.cleanup_env(e)


@pytest.fixture
def env_https(tmp_path):
    e = harness.build_env(tmp_path, https=True)
    try:
        yield e
    finally:
        harness.cleanup_env(e)


def test_cold_start_serves_declared_sha(env: harness.TrayEnv) -> None:
    """A plain `tray.bat` launch boots the dummy app and serves repo HEAD."""
    result = harness.run_tray_bat(env.tray_bat, [])
    assert result.returncode == 0, result.stdout + result.stderr

    pids = harness.wait_for_tray_pids(env.venv_dir, env.tray_match)
    assert pids, "no tray process detected after a plain launch"

    version = harness.poll_version(env.port, https=False)
    assert version["git_sha"] == harness.head_sha(env.script_dir)


def test_idempotent_second_launch_does_not_duplicate_process(env: harness.TrayEnv) -> None:
    """Re-running `tray.bat` (no `--restart`) while one is up must no-op, not
    spawn a second process -- the "idempotent start" claim in
    docs/windows-tray.md and tray.bat.template's own header comment."""
    first = harness.run_tray_bat(env.tray_bat, [])
    assert first.returncode == 0, first.stdout + first.stderr
    pids_before = harness.wait_for_tray_pids(env.venv_dir, env.tray_match)
    assert pids_before, "no tray process detected after the first launch"

    second = harness.run_tray_bat(env.tray_bat, [])
    assert second.returncode == 0, second.stdout + second.stderr

    pids_after = harness.wait_for_tray_pids(env.venv_dir, env.tray_match)
    assert pids_after == pids_before, (
        f"a second plain launch must adopt the running tray, not duplicate it: "
        f"before={pids_before} after={pids_after}"
    )


def test_restart_serves_new_sha_after_bump(env: harness.TrayEnv) -> None:
    """`--restart` after a new commit must serve the NEW git_sha -- not exit 0
    while still serving the process it never actually replaced (#144)."""
    first = harness.run_tray_bat(env.tray_bat, [])
    assert first.returncode == 0, first.stdout + first.stderr
    harness.wait_for_tray_pids(env.venv_dir, env.tray_match)
    old_sha = harness.poll_version(env.port, https=False)["git_sha"]
    assert old_sha == harness.head_sha(env.script_dir)

    new_sha = harness.git_commit_allow_empty(env.script_dir, "bump build")
    assert new_sha != old_sha

    restarted = harness.run_tray_bat(env.tray_bat, ["--restart"])
    assert restarted.returncode == 0, restarted.stdout + restarted.stderr

    served = harness.poll_version(env.port, https=False, timeout=30)["git_sha"]
    assert served == new_sha, (
        f"--restart reported success but served {served!r}, expected the new "
        f"HEAD {new_sha!r} -- this is the exact silent stale-serve #144 covers"
    )


def test_restart_via_noninteractive_nested_shell_serves_new_build(env: harness.TrayEnv) -> None:
    """The full cold-start -> bump -> `--restart` cycle, launched the way that
    historically failed silently: a non-interactive nested shell with no
    console/tty attached (project-scaffolding#54, #144)."""
    first = harness.run_tray_bat(env.tray_bat, [], nested=True)
    assert first.returncode == 0, first.stdout + first.stderr
    harness.wait_for_tray_pids(env.venv_dir, env.tray_match)
    old_sha = harness.poll_version(env.port, https=False)["git_sha"]

    new_sha = harness.git_commit_allow_empty(env.script_dir, "bump build (nested)")

    restarted = harness.run_tray_bat(env.tray_bat, ["--restart"], nested=True)
    assert restarted.returncode == 0, restarted.stdout + restarted.stderr

    served = harness.poll_version(env.port, https=False, timeout=30)["git_sha"]
    assert served == new_sha != old_sha, (
        f"--restart from a non-interactive nested shell reported success but "
        f"served {served!r}; the old cmd `for /f` shape silently degraded to a "
        f"plain start under exactly this invocation (#54/#144)"
    )


def test_https_loopback_self_signed_cert_restart_verifies(env_https: harness.TrayEnv) -> None:
    """The verify leg must reach an HTTPS PWA over loopback despite a
    self-signed cert that names 127.0.0.1, not a public host (#147/#148)."""
    first = harness.run_tray_bat(env_https.tray_bat, [])
    assert first.returncode == 0, first.stdout + first.stderr
    harness.wait_for_tray_pids(env_https.venv_dir, env_https.tray_match)

    old_sha = harness.poll_version(env_https.port, https=True)["git_sha"]
    assert old_sha == harness.head_sha(env_https.script_dir)

    new_sha = harness.git_commit_allow_empty(env_https.script_dir, "bump https build")

    restarted = harness.run_tray_bat(env_https.tray_bat, ["--restart"])
    # Load-bearing: Wait-VersionMatchesHead inside the real ps1 must itself
    # succeed against the self-signed loopback cert (via LoopbackCertBypass)
    # for --restart to exit 0 at all -- a broken bypass fails right here.
    assert restarted.returncode == 0, restarted.stdout + restarted.stderr

    served = harness.poll_version(env_https.port, https=True, timeout=30)["git_sha"]
    assert served == new_sha
