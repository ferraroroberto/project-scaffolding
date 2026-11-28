"""Which copy `-Replace` treats as the install (`src/installer_inplace.py`), and the scaffold-hosted entry point.

The pair of repositories comes from `test_installer_migrate.py`; processes and ports are injected, so
these tests start nothing.
"""

from __future__ import annotations

import datetime
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from src import installer_inplace
from src import installer_migrate as m
from src.no_window import NO_WINDOW
from tests.vendored.test_installer_migrate import (
    OLD_TOML,
    _child_ok,
    _clone,
    _git,
    _listing,
    _pair,
    _proc,
    _replace,
    _runner,
    _states,
)

# Windows paths, process trees and cmd.exe are the subject: the Mac nightly leaves this module out.
pytestmark = [pytest.mark.windows_only, pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH")]


@pytest.fixture(autouse=True)
def _no_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m.time, "sleep", lambda _s: None)
    monkeypatch.setattr(m, "PORT_FREE_TIMEOUT_S", 0)


# ---------------------------------------------------------------- finding the live install

def _sibling(tmp_path: Path, origin: Path, name: str) -> Path:
    """Another checkout of the app beside the install, as an old copy left in a suffixed folder."""
    path = tmp_path / name
    _git(tmp_path, "clone", "-q", str(origin), str(path))
    return path


def _unrelated(tmp_path: Path, name: str) -> Path:
    """A repository with a history of its own: other content, so its root commit can never be the app's."""
    return _clone(tmp_path / f"{name}-src", OLD_TOML + f"# {name}, another app\n").rename(tmp_path / name)


def _windows_holder(pid: int, folder: Path, port: int = 8453) -> m.Snapshot:
    """A Windows listing: a venv python launcher in ``folder`` and its base-python child holding ``port``."""
    launcher = _proc(pid, folder)
    venv_python = folder / ".venv" / "Scripts" / "python.exe"
    child = m.Proc(pid + 1, pid, r"C:\Python313\python.exe", f'"{venv_python}" -m app')
    return m.Snapshot({launcher.pid: launcher, child.pid: child}, {port: {child.pid: {"0.0.0.0"}}})


def _kills(calls: list[Any]) -> list[str]:
    return [c[2] for c in calls if isinstance(c, list) and c[:1] == ["taskkill"]]


def _recording(calls: list[Any]) -> Any:
    def runner(command: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return _child_ok(command, **kwargs)
    return runner


def _replace_seq(folder: Path, incoming: Path, calls: list[Any], snaps: list[m.Snapshot],
                 runner: Any = None) -> m.MigrationReport:
    """A real run whose process listings follow ``snaps``, then show nothing running."""
    queue = iter(snaps)
    cwd = os.getcwd()
    try:
        return installer_inplace.replace(folder, incoming, what_if=False, as_json=True,
                                         runner=runner or _recording(calls),
                                         snapshot_fn=lambda: next(queue, m.Snapshot({}, {})),
                                         today=datetime.date(2026, 11, 27))
    finally:
        os.chdir(cwd)


def test_a_port_holder_is_traced_to_its_checkout_on_windows_listings(tmp_path: Path) -> None:
    _, folder, _ = _pair(tmp_path, with_incoming=False)
    snap = _windows_holder(10, folder)
    [(pid, owner, home)] = installer_inplace.port_holders(snap, 8453)
    assert (pid, home) == (11, folder) and owner is not None and owner.pid == 11
    # A base python whose parent is gone is still traced through the venv path on its command line.
    del snap.procs[10]
    assert installer_inplace.port_holders(snap, 8453)[0][2] == folder
    outsider = m.Snapshot({77: m.Proc(77, 1, r"C:\Other\server.exe", "server")}, {8453: {77: {"::"}}})
    assert installer_inplace.port_holders(outsider, 8453) == [(77, outsider.procs[77], None)]


def test_a_macos_listing_with_no_drive_path_is_never_traced_to_a_checkout() -> None:
    """The installer probes Windows only: a macOS framework python names no drive path, so it is never the app's."""
    framework = "/Library/Frameworks/Python.framework/Versions/3.13/Resources/Python.app/Contents/MacOS/Python"
    darwin = m.Snapshot({5: m.Proc(5, 1, framework, "/Users/sample/app/.venv/bin/python -m app")}, {8453: {5: {"*"}}})
    assert installer_inplace.port_holders(darwin, 8453) == []  # "*" is not a loopback address in the Windows listing's terms
    darwin.listeners[8453] = {5: {"::"}}
    assert installer_inplace.port_holders(darwin, 8453) == [(5, darwin.procs[5], None)]


def test_same_app_is_the_shared_root_commit_whatever_the_origin(tmp_path: Path) -> None:
    origin, folder, incoming = _pair(tmp_path)
    _git(incoming, "remote", "set-url", "origin", "https://github.com/o/app.git")
    ref = installer_inplace.read_checkout(incoming, _runner)
    for url in ("git@github.com:o/app.git", "https://github.com/o/old-name"):  # ssh form; a renamed repository
        _git(folder, "remote", "set-url", "origin", url)
        assert installer_inplace.same_app(installer_inplace.read_checkout(folder, _runner), ref)[0], url
    other = installer_inplace.read_checkout(_unrelated(tmp_path, "other"), _runner)
    assert not installer_inplace.same_app(other, ref)[0]
    # A repository of its own built from the app's history (a "lite" copy) is another app.
    lite = _sibling(tmp_path, origin, "app-lite")
    _git(lite, "remote", "set-url", "origin", "https://github.com/o/app-lite.git")
    assert installer_inplace.same_app(installer_inplace.read_checkout(lite, _runner), ref) == (
        False, "a repository of its own (app-lite) that shares the app's history")
    # With no history on one side, the parsed origin decides.
    no_history = installer_inplace.Checkout(folder, None, "git@example.invalid:o/App")
    assert installer_inplace.same_app(no_history, installer_inplace.Checkout(incoming, None,
                                                                             "https://example.invalid/o/app"))[0]


def _squatted(tmp_path: Path, with_incoming: bool = True) -> tuple[Path, Path, Path]:
    """Another app's repository at <root>/app, the app's live copy at <root>/app-new, a fresh clone beside them."""
    origin, folder, incoming = _pair(tmp_path, with_incoming)
    folder.rename(tmp_path / "old-app")  # a name no sibling pattern matches
    _unrelated(tmp_path, "app")
    return folder, _sibling(tmp_path, origin, "app-new"), incoming


def test_an_unrelated_install_folder_is_moved_aside_and_the_live_sibling_is_migrated(tmp_path: Path) -> None:
    folder, live, incoming = _squatted(tmp_path)
    before = _listing(tmp_path)
    preview = _replace(folder, incoming, what_if=True, snap=_windows_holder(10, live))
    assert not preview.failed, preview.render()
    assert _states(preview, "discover") == {"app": "other app", "app-new": "live"}
    assert {i: d for _, i, d in preview.rows["discover"]}["app"].startswith("left alone: shares no root commit")
    assert {i for s, i, _ in preview.rows["stop"] if s == "would stop"} == {"PID 10 python.exe", "PID 11 python.exe"}
    assert [(s, i) for s, i, _ in preview.rows["in place"]] == [
        ("would rename", "app"), ("would rename", "app.incoming"), ("would run", "setup.bat -MigrateFrom"),
        ("would rename", "app-new")]
    assert "another app" in preview.rows["in place"][0][2] and _listing(tmp_path) == before

    calls: list[Any] = []
    report = _replace_seq(folder, incoming, calls, [_windows_holder(10, live)] * 2)
    assert not report.failed, report.render()
    assert _kills(calls) == ["10"]
    child = [c for c in calls if isinstance(c, str)]
    assert len(child) == 1 and f'-MigrateFrom "{live}"' in child[0]
    backup = tmp_path / "app.bak-20261127-1"
    assert "another app" in (backup / ".fleet.toml").read_text(encoding="utf-8")
    assert (tmp_path / "app-new.bak-20261127-1" / ".git").is_dir() and not live.exists()
    assert "[install.migrate]" in (folder / ".fleet.toml").read_text(encoding="utf-8") and not incoming.exists()


def test_another_apps_backup_is_never_named_the_fallback(tmp_path: Path) -> None:
    folder, live, incoming = _squatted(tmp_path)

    def failing(command: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if isinstance(command, str) and "-MigrateFrom" in command:
            return subprocess.CompletedProcess(command, 1, stdout='{"ok": false}')
        return _runner(command, **kwargs)

    report = _replace_seq(folder, incoming, [], [_windows_holder(10, live)] * 2, runner=failing)
    assert report.failed and live.is_dir(), report.render()
    [detail] = [d for _, i, d in report.rows["in place"] if i == "setup.bat -MigrateFrom"]
    assert "app.bak-20261127-1 holds the other app" in detail and "the fallback" not in detail


@pytest.mark.parametrize("what_if", [True, False])
def test_an_unrelated_install_folder_in_use_is_refused_before_anything_stops(tmp_path: Path, what_if: bool) -> None:
    folder, live, incoming = _squatted(tmp_path)
    snap = _windows_holder(10, live)
    snap.procs[500] = _proc(500, folder)
    calls: list[Any] = []
    report = _replace(folder, incoming, what_if=what_if, runner=_recording(calls), snap=snap)
    state, item, detail = report.rows["guard"][-1]
    assert report.failed and (state, item) == ("refused", "app") and "PID 500" in detail, report.render()
    assert not _kills(calls) and folder.is_dir() and live.is_dir() and not list(tmp_path.glob("*.bak-*"))


def test_an_unrelated_install_folder_with_no_copy_of_the_app_is_left_where_it_is(tmp_path: Path) -> None:
    folder, live, incoming = _squatted(tmp_path)
    live.rename(tmp_path / "elsewhere")
    calls: list[Any] = []
    report = _replace(folder, incoming, what_if=False, runner=_recording(calls))
    assert report.failed and _states(report, "discover") == {"app": "refused"}, report.render()
    assert [s for s, i, _ in report.rows["discover"] if i == "app"] == ["other app", "refused"]
    assert not _kills(calls) and folder.is_dir() and incoming.is_dir() and not list(tmp_path.glob("*.bak-*"))


def test_an_install_folder_that_is_no_checkout_is_still_refused(tmp_path: Path) -> None:
    folder, live, incoming = _squatted(tmp_path)
    folder.rename(tmp_path / "set-aside")
    folder.mkdir()
    report = _replace(folder, incoming, what_if=False, runner=_recording([]), snap=_windows_holder(10, live))
    assert report.failed and _states(report, "guard")["app"] == "refused"
    assert "not the root of a git checkout" in report.rows["guard"][-1][2] and live.is_dir()


def test_replace_with_only_a_live_suffixed_copy_lands_the_clone_at_the_canonical_path(tmp_path: Path) -> None:
    _, folder, incoming = _pair(tmp_path)
    live = folder.rename(tmp_path / "app-new")
    calls: list[Any] = []
    report = _replace_seq(folder, incoming, calls, [_windows_holder(10, live)] * 2)
    assert not report.failed, report.render()
    assert _states(report, "discover") == {"app": "missing", "app-new": "live"}
    assert _kills(calls) == ["10"]
    child = [c for c in calls if isinstance(c, str)]
    assert len(child) == 1 and f'-MigrateFrom "{live}"' in child[0]
    assert (folder / ".git").is_dir() and not incoming.exists() and not live.exists()
    assert (tmp_path / "app-new.bak-20261127-1" / ".git").is_dir()
    assert [r[:2] for r in report.rows["in place"]] == [("renamed", "app.incoming"), ("ok", "setup.bat -MigrateFrom"),
                                                        ("renamed", "app-new")]


def test_replace_with_a_stale_install_and_a_live_sibling_previews_both_then_keeps_both(tmp_path: Path) -> None:
    origin, folder, incoming = _pair(tmp_path)
    live = _sibling(tmp_path, origin, "app-new")
    _unrelated(tmp_path, "app-tools")  # a name that matches, a history that does not: left alone
    before = _listing(tmp_path)
    preview = _replace(folder, incoming, what_if=True, snap=_windows_holder(10, live))
    assert not preview.failed, preview.render()
    assert _states(preview, "discover") == {"app": "stale", "app-new": "live", "app-tools": "other app"}
    assert "holds port 8453 (PID 11)" in {i: d for _, i, d in preview.rows["discover"]}["app-new"]
    stops = [(i, d) for s, i, d in preview.rows["stop"] if s == "would stop"]
    assert {i for i, _ in stops} == {"PID 10 python.exe", "PID 11 python.exe"}
    assert all("runs from app-new" in d for _, d in stops) and _listing(tmp_path) == before
    plan = [(s, i) for s, i, _ in preview.rows["in place"]]
    assert plan == [("would rename", "app"), ("would rename", "app.incoming"),
                    ("would run", "setup.bat -MigrateFrom"), ("would rename", "app-new")]

    calls: list[Any] = []
    report = _replace_seq(folder, incoming, calls, [_windows_holder(10, live)] * 2)
    assert not report.failed, report.render()
    assert _kills(calls) == ["10"]
    assert (tmp_path / "app.bak-20261127-1" / ".git").is_dir()
    assert (tmp_path / "app-new.bak-20261127-1" / ".git").is_dir()
    assert (folder / ".git").is_dir() and (tmp_path / "app-tools").is_dir()


def test_a_failed_migration_leaves_the_live_sibling_at_its_path(tmp_path: Path) -> None:
    origin, folder, incoming = _pair(tmp_path)
    live = _sibling(tmp_path, origin, "app-new")

    def failing(command: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if isinstance(command, str) and "-MigrateFrom" in command:
            return subprocess.CompletedProcess(command, 1, stdout='{"ok": false}')
        return _runner(command, **kwargs)

    report = _replace_seq(folder, incoming, [], [_windows_holder(10, live)] * 2, runner=failing)
    assert report.failed and live.is_dir() and report.rows["in place"][-1][:2] == ("kept", "app-new")


def test_a_port_held_by_another_program_is_refused_and_nothing_is_stopped(tmp_path: Path) -> None:
    _, folder, incoming = _pair(tmp_path)
    outsider = m.Proc(77, 1, r"C:\Other\server.exe", "server")
    snap = m.Snapshot({10: _proc(10, folder), 77: outsider}, {8453: {77: {"127.0.0.1"}}})
    calls: list[Any] = []
    for what_if in (True, False):
        report = _replace(folder, incoming, what_if=what_if, runner=_recording(calls), snap=snap)
        state, item, detail = report.rows["discover"][-1]
        assert report.failed and (state, item) == ("refused", "port 8453")
        assert r"PID 77 C:\Other\server.exe" in detail and "stop" not in report.rows
    assert not _kills(calls) and folder.is_dir() and not list(tmp_path.glob("*.bak-*"))


def test_a_copy_elsewhere_holding_the_port_is_found_by_its_port(tmp_path: Path) -> None:
    origin, folder, incoming = _pair(tmp_path)
    elsewhere = _sibling(tmp_path, origin, "moved")
    report = _replace(folder, incoming, what_if=True, snap=_windows_holder(10, elsewhere))
    assert not report.failed, report.render()
    assert _states(report, "discover") == {"app": "stale", "moved": "live"}


def test_with_nothing_running_the_most_recent_commit_is_live(tmp_path: Path) -> None:
    origin, folder, incoming = _pair(tmp_path)
    newer = _sibling(tmp_path, origin, "app.e2e")
    # Commit times have one-second resolution, and a tie goes to <root>/app: this copy's commit is decades later.
    subprocess.run(["git", "-c", f"core.hooksPath={tmp_path / 'no-hooks'}", "-c", "user.name=t", "-c",
                    "user.email=t@example.invalid", "commit", "-q", "--allow-empty", "-m", "later"], cwd=newer,
                   check=True, capture_output=True, timeout=60, creationflags=NO_WINDOW,
                   env={**os.environ, "GIT_COMMITTER_DATE": "2090-01-01T00:00:00"})
    report = _replace(folder, incoming, what_if=True)
    assert _states(report, "discover") == {"app": "stale", "app.e2e": "live"}, report.render()
    assert "nothing runs from any copy" in {i: d for _, i, d in report.rows["discover"]}["app.e2e"]


def test_backups_and_incoming_clones_are_never_candidates(tmp_path: Path) -> None:
    origin, folder, incoming = _pair(tmp_path)
    for name in ("app.bak-20261101-1", "app-new.bak-20261101-1", "app.incoming-old"):
        _sibling(tmp_path, origin, name)
    keep = _sibling(tmp_path, origin, "app-new")
    assert installer_inplace.siblings(folder, incoming) == [keep]


# ---------------------------------------------------------------- the scaffold-hosted entry point

def _entry(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> tuple[int, Any]:
    from scripts.tools import replace_app

    inplace = replace_app.load_inplace()
    monkeypatch.setattr(inplace.m, "take_snapshot", lambda _r: inplace.m.Snapshot({}, {}))
    monkeypatch.setattr(inplace.m.time, "sleep", lambda _s: None)
    seen: list[Any] = []
    monkeypatch.setattr(inplace.m, "emit", lambda report, _j: seen.append(report) or int(report.failed))
    cwd = os.getcwd()
    try:
        code = replace_app.main(argv, runner=_child_ok)
    finally:
        os.chdir(cwd)
    return code, seen[0] if seen else None


def test_the_entry_point_runs_the_scaffold_flow_on_an_app_that_vendors_none_of_it(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    origin, folder, incoming = _pair(tmp_path, with_incoming=False)
    named = shutil.copytree(origin, tmp_path / "o" / "app")  # an origin named after the app
    live = folder.rename(tmp_path / "app-new")  # only a suffixed copy, at the commit that declares the migration
    _git(live, "remote", "set-url", "origin", str(named))
    _git(live, "pull", "-q", "--ff-only", "origin", _git(live, "branch", "--show-current"))
    code, report = _entry(["app", "--root", str(tmp_path), "-WhatIf"], monkeypatch)
    assert code == 0, report.render()
    assert _states(report, "discover") == {"app": "missing", "app-new": "live"} and not incoming.exists()
    code, report = _entry(["app", "--root", str(tmp_path), "-Json"], monkeypatch)
    assert code == 0, report.render()
    assert (folder / ".git").is_dir() and (tmp_path / f"app-new.bak-{datetime.date.today():%Y%m%d}-1").is_dir()
    assert "[install.migrate]" in (folder / ".fleet.toml").read_text(encoding="utf-8")


def test_the_entry_point_uses_an_incoming_clone_that_is_already_there(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _pair(tmp_path)
    code, report = _entry(["app", "--root", str(tmp_path), "-WhatIf", "-Json"], monkeypatch)
    assert code == 0 and report.mode == "replace" and _states(report, "guard")["incoming clone"] == "ok"


def test_the_entry_point_clones_the_app_not_an_unrelated_install_folder(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    folder, live, _ = _squatted(tmp_path, with_incoming=False)
    named = shutil.copytree(tmp_path / "o" / "new", tmp_path / "remotes" / "app")  # an origin named after the app
    _git(live, "remote", "set-url", "origin", str(named))
    _git(folder, "remote", "add", "origin", "https://example.invalid/o/something-else.git")
    code, report = _entry(["app", "--root", str(tmp_path), "-WhatIf"], monkeypatch)
    assert code == 0, report.render()
    assert _states(report, "discover") == {"app": "other app", "app-new": "live"}, report.render()
    assert [d for s, _, d in report.rows["in place"] if s == "would clone"] == [f"into {tmp_path / 'app.incoming'}"]
    assert str(named) in [i for s, i, _ in report.rows["in place"] if s == "would clone"]


def test_the_entry_point_refuses_when_no_copy_names_the_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    code, report = _entry(["app", "--root", str(tmp_path), "-WhatIf"], monkeypatch)
    assert code == 1 and _states(report, "guard") == {"origin": "refused"}
