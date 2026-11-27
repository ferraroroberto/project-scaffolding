"""Migrating an install into a fresh clone (`src/installer_migrate.py`) and in place (`src/installer_inplace.py`).

The clone is a real git checkout under `tmp_path`; processes, ports and the
endpoint are injected (`snapshot_fn`, `fetch`), and the install itself is a stub,
so these tests start nothing. `test_installer_migrate_live.py` runs the same flow
for real on a disposable pair.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src import installer, installer_inplace
from src import installer_migrate as m
from src.no_window import NO_WINDOW

# Windows paths, process trees and cmd.exe are the subject: the Mac nightly leaves this module out.
pytestmark = [pytest.mark.windows_only, pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH")]

CANARY = "CANARY-VALUE-7f3a"  # a config and secret value no output may contain
TOML = """port = ":8453"

[install]
samples = []

[install.endpoint]
version_path = "/api/version"

[install.migrate]
copy    = ["config.json", "data", ".env"]
secrets = [".env"]
shared  = ["demo-app"]
start   = ["start.bat"]
"""


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          creationflags=NO_WINDOW, timeout=60)
    return done.stdout.strip()


def _clone(tmp_path: Path, toml: str = TOML) -> Path:
    root = tmp_path / "new"
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    (root / ".fleet.toml").write_text(toml, encoding="utf-8")
    (root / ".gitignore").write_text("config.json\ndata/\n.env\n.venv/\n", encoding="utf-8")
    _git(root, "add", "-A")
    # The machine's commit hooks are not under test.
    _git(root, "-c", f"core.hooksPath={tmp_path / 'no-hooks'}", "-c", "user.name=t",
         "-c", "user.email=t@example.invalid", "commit", "-qm", "init")
    return root


def _old(tmp_path: Path) -> Path:
    old = tmp_path / "old"
    (old / "data" / "logs").mkdir(parents=True)
    (old / "config.json").write_text(json.dumps({
        "token": CANARY, "data_dir": str(old / "data"), "nested": {"paths": [str(old).replace("\\", "/") + "/x"]},
        "sibling": str(old) + ".bak-1\\y"}), encoding="utf-8")
    (old / "data" / "state.db").write_bytes(b"db")
    (old / "data" / "state.db-wal").write_bytes(b"wal")
    (old / "data" / "logs" / "a.log").write_text(f"ran from {old}", encoding="utf-8")
    (old / ".env").write_text(f"SECRET={CANARY}\n", encoding="utf-8")
    return old


class StubInstaller:
    """Stands in for `src/installer.py`: records the call, reports success."""

    def __init__(self, failed: bool = False) -> None:
        self.calls: list[Path] = []
        self.failed = failed

    def run(self, root: Path, *, what_if: bool, startup: bool) -> Any:
        self.calls.append(root)
        return SimpleNamespace(lines=[("unchanged", ".venv", "")], required=[], optional=[], failed=self.failed)

    def render(self, report: Any) -> str:
        return "install steps"


def _runner(command: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """Real git; an empty autostart list from PowerShell; every start command succeeds."""
    if isinstance(command, list) and command[0] == "git":
        return subprocess.run(command, **kwargs)  # no-window-exempt: kwargs carry the module's own creationflags=NO_WINDOW
    return subprocess.CompletedProcess(command, 0, stdout="[]")


def _snap(*procs: m.Proc, port: int | None = None, listener: int | None = None) -> m.Snapshot:
    listeners = {port: {listener: {"127.0.0.1"}}} if port and listener else {}
    return m.Snapshot({p.pid: p for p in procs}, listeners)


def _proc(pid: int, folder: Path, ppid: int = 1) -> m.Proc:
    return m.Proc(pid, ppid, str(folder / ".venv" / "Scripts" / "python.exe"), "python -m app")


def _junction(link: Path, target: Path) -> Path:
    """A real directory junction: another spelling of ``target``."""
    import _winapi  # Windows only, and the Mac nightly still imports this module to collect it

    target.mkdir(parents=True, exist_ok=True)
    _winapi.CreateJunction(str(target), str(link))
    return link


@pytest.fixture(autouse=True)
def _fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(m.time, "sleep", lambda _s: None)
    monkeypatch.setattr(m, "VERIFY_TIMEOUT_S", 0)
    monkeypatch.setattr(m, "PORT_FREE_TIMEOUT_S", 0)


def _migrate(root: Path, old: Path, snap: m.Snapshot | None, head_served: str | None = "head", **kw: Any) -> m.MigrationReport:
    head = _git(root, "rev-parse", "HEAD")
    served = {"git_sha": head if head_served == "head" else head_served} if head_served else None
    (root / ".venv").mkdir(exist_ok=True)
    return m.migrate(root, old, installer=kw.pop("installer", StubInstaller()), what_if=kw.pop("what_if", False),
                     stop=kw.pop("stop", False), runner=_runner, snapshot_fn=lambda: snap,
                     fetch=lambda _ep: served, **kw)


def _states(report: m.MigrationReport, section: str) -> dict[str, str]:
    return {item: state for state, item, _ in report.rows.get(section, [])}


# ---------------------------------------------------------------- declaration and paths

def test_declaration_parses_and_the_port_falls_back_to_the_top_level_one() -> None:
    mig = m.parse_migration({"port": ":8453", "install": {"endpoint": {}, "migrate": {"copy": ["a\\b/"]}}})
    assert mig.copy == ["a/b"] and mig.start == ["tray.bat", "--restart"]
    assert mig.endpoint == m.Endpoint(scheme="http", port=8453, version_path="/api/version", self_signed=False)
    assert m.parse_migration({"install": {"migrate": {}}}).endpoint is None


@pytest.mark.parametrize(("migrate", "endpoint", "message"), [
    ({"copy": ["../x"]}, None, "inside the repo"),
    ({"copy": ["C:/x"]}, None, "inside the repo"),
    ({"shared": ["C:/sqlite/app"]}, None, "names, not paths"),
    ({"start": []}, None, "start"),
    ({}, {"port": 70000}, "TCP port"),
    ({}, {"scheme": "ftp", "port": 1}, "scheme"),
    ({}, {}, "needs a port"),
])
def test_a_malformed_declaration_names_the_key(migrate: dict[str, Any], endpoint: Any, message: str) -> None:
    table: dict[str, Any] = {"migrate": migrate}
    if endpoint is not None:
        table["endpoint"] = endpoint
    with pytest.raises(ValueError, match=message):
        m.parse_migration({"install": table})


def test_paths_match_by_component_so_a_backup_folder_is_never_the_app_folder(tmp_path: Path) -> None:
    app = tmp_path / "app"
    assert m.inside(str(app / "x.py"), app) and not m.inside(str(tmp_path / "app.bak-20260101-1" / "x.py"), app)
    assert m.mentions(f'"{app}\\.venv\\python.exe" -m x', app)
    assert m.mentions(str(app).replace("\\", "/").upper() + "/tray.bat", app)
    assert not m.mentions(f"{app}.bak-20260101-1\\tray.bat", app)


def test_a_process_reached_through_a_junction_runs_from_the_folder(tmp_path: Path) -> None:
    app = tmp_path / "my app"
    link, above = _junction(tmp_path / "li nk", app), _junction(tmp_path / "above", tmp_path)
    sibling = _junction(tmp_path / "other", tmp_path / "my app.bak-1")
    base_python = r"C:\Python\python.exe"
    found = m.processes_from(_snap(
        _proc(1, link),
        m.Proc(2, 0, base_python, f'"{link}\\.venv\\Scripts\\python.exe" -m app'),
        m.Proc(3, 0, base_python, "python -X x " + str(above / "my app" / "server.py").replace("\\", "/")),
        _proc(4, sibling), _proc(5, above / "my app.bak-1"),
        m.Proc(6, 0, base_python, f'python "{sibling}\\server.py" http://localhost/x'),
    ), app, set())
    assert [p.pid for p in found] == [1, 2, 3]


def test_a_venv_that_is_a_junction_to_elsewhere_still_belongs_to_its_app(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    link = _junction(tmp_path / "link", app)
    _junction(app / ".venv", tmp_path / "shared-venv")
    for spelled in (app, link):
        assert m.inside(str(spelled / ".venv" / "Scripts" / "python.exe"), app)
        assert m.mentions(f'"{spelled}\\.venv\\Scripts\\python.exe" -m app', app)
    assert not m.inside(str(tmp_path / "shared-venv" / "Scripts" / "python.exe"), app)


def test_a_value_or_text_spelled_through_a_junction_is_rebound_and_reported(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    link = _junction(tmp_path / "link", old)
    data_link = _junction(tmp_path / "datalink", old / "data")
    data = {"a": str(link / "d"), "b": str(link).replace("\\", "/"), "c": str(data_link) + "\\x.db",
            "d": str(link) + ".bak-1\\y"}
    assert m.rebind_values(data, old, new) == ["a", "b", "c"]
    assert data["a"] == str(new / "d") and data["b"] == str(new).replace("\\", "/")
    assert data["c"] == str(new / "data" / "x.db") and data["d"] == str(link) + ".bak-1\\y"
    assert m.mentions(f'@echo off\r\nstart "" "{link}\\tray.bat"\r\n', old)
    # A shortcut's target, arguments and folder arrive unquoted on one line: the later path counts too.
    assert m.mentions(f"C:\\Windows\\System32\\cmd.exe /c {link}\\tray.bat C:\\Windows", old)


def test_a_config_holding_only_backslash_paths_is_rebound(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    new.mkdir()
    old.mkdir()
    # JSON doubles each backslash, so the raw text never holds the folder as spelled.
    (new / "config.json").write_text(json.dumps({"data_dir": str(old / "data")}), encoding="utf-8")
    shutil.copy(new / "config.json", old / "config.json")
    report = m.MigrationReport(mode="migrate", what_if=False)
    m.rebind_copied(old, new, ["config.json"], report)
    assert _states(report, "rebind") == {"config.json": "rebound"}
    assert json.loads((new / "config.json").read_text(encoding="utf-8")) == {"data_dir": str(new / "data")}


def test_rebind_rewrites_leading_old_paths_in_their_own_slash_style(tmp_path: Path) -> None:
    old, new = tmp_path / "old", tmp_path / "new"
    data = {"a": str(old / "d"), "b": [str(old).replace("\\", "/") + "/e"], "c": {"d": "x " + str(old)},
            "e": str(old) + "er"}
    assert m.rebind_values(data, old, new) == ["a", "b[0]"]
    assert data["a"] == str(new / "d") and data["b"] == [str(new).replace("\\", "/") + "/e"]
    assert data["c"] == {"d": "x " + str(old)} and data["e"] == str(old) + "er"


# ---------------------------------------------------------------- -MigrateFrom

def test_migrate_copies_rebinds_compares_and_verifies(tmp_path: Path) -> None:
    root, old = _clone(tmp_path), _old(tmp_path)
    report = _migrate(root, old, _snap(_proc(100, root), port=8453, listener=100))
    assert not report.failed, report.render()
    assert _states(report, "copy") == {"config.json": "copied", "data/": "copied", ".env": "copied"}
    assert (root / "data" / "state.db").read_bytes() == b"db"
    assert not (root / "data" / "state.db-wal").exists()
    config = json.loads((root / "config.json").read_text(encoding="utf-8"))
    assert config["data_dir"] == str(root / "data")
    assert config["nested"]["paths"] == [str(root).replace("\\", "/") + "/x"]
    assert config["sibling"] == str(old) + ".bak-1\\y"
    assert _states(report, "rebind") == {"config.json": "rebound", "data/logs/a.log": "names old"}
    assert _states(report, "secrets") == {".env": "same"}
    assert _states(report, "shared") == {"demo-app": "left in place"}
    assert [state for state, _, _ in report.rows["verify"]] == ["ok", "ok"]


def test_no_output_contains_a_config_or_secret_value(tmp_path: Path) -> None:
    root, old = _clone(tmp_path), _old(tmp_path)
    report = _migrate(root, old, _snap(_proc(100, root), port=8453, listener=100))
    assert CANARY not in report.render() and CANARY not in json.dumps(report.to_json())


def test_an_existing_file_is_kept_and_a_database_is_held_back_while_the_old_copy_runs(tmp_path: Path) -> None:
    root, old = _clone(tmp_path), _old(tmp_path)
    (root / ".env").write_text("SECRET=mine\n", encoding="utf-8")
    report = _migrate(root, old, _snap(_proc(100, root), _proc(200, old), port=8453, listener=100))
    assert (root / ".env").read_text(encoding="utf-8") == "SECRET=mine\n"
    assert _states(report, "copy")[".env"] == "kept" and _states(report, "secrets") == {".env": "differs"}
    assert not (root / "data" / "state.db").exists()
    assert "held back 1" in dict((i, d) for _, i, d in report.rows["copy"])["data/"]
    assert _states(report, "leftover")["PID 200 python.exe"] == "still running"


def test_verify_fails_when_the_old_copy_still_serves_the_port(tmp_path: Path) -> None:
    root, old = _clone(tmp_path), _old(tmp_path)
    old_python = m.Proc(201, 200, r"C:\Python\python.exe", "python -m app")  # a venv python's base child
    report = _migrate(root, old, _snap(_proc(200, old), old_python, port=8453, listener=201))
    assert report.failed
    owner = [row for row in report.rows["verify"] if row[1] == "port 8453 owner"]
    assert owner[0][0] == "failed" and "PID 201 runs from the old copy" in owner[0][2]


def test_verify_fails_on_a_stale_commit_and_reports_unknown_when_nothing_can_be_listed(tmp_path: Path) -> None:
    root, old = _clone(tmp_path), _old(tmp_path)
    stale = _migrate(root, old, _snap(_proc(100, root), port=8453, listener=100), head_served="0123456789ab")
    assert stale.failed and "serves 0123456789ab" in stale.rows["verify"][0][2]
    blind = _migrate(_clone(tmp_path / "b"), old, None)
    assert blind.failed and _states(blind, "verify")["port 8453 owner"] == "unknown"


def test_no_endpoint_declared_is_unknown_never_ok(tmp_path: Path) -> None:
    root = _clone(tmp_path, TOML.replace('[install.endpoint]\nversion_path = "/api/version"\n', ""))
    report = _migrate(root, _old(tmp_path), _snap())
    assert report.failed and _states(report, "verify") == {"endpoint": "unknown"}


def test_what_if_changes_nothing(tmp_path: Path) -> None:
    root, old = _clone(tmp_path), _old(tmp_path)
    (root / ".venv").mkdir()
    before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts)
    report = _migrate(root, old, _snap(), what_if=True)
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if ".git" not in p.parts) == before
    assert _states(report, "copy")["config.json"] == "would copy"
    assert _states(report, "rebind")["config.json"] == "would rebind"
    assert _states(report, "start") == {"start.bat": "would run"}


def test_what_if_names_every_file_a_folder_would_copy(tmp_path: Path) -> None:
    root, old = _clone(tmp_path), _old(tmp_path)
    report = _migrate(root, old, _snap(), what_if=True, stop=True)
    would = {item for state, item, _ in report.rows["copy"] if state == "would copy"}
    assert would == {"config.json", ".env", "data/state.db", "data/logs/a.log"}
    assert CANARY not in report.render()


# ---------------------------------------------------------------- the port and scheme verify asks

PORT_TOML = TOML.replace('[install.endpoint]\n', '[install.endpoint]\nscheme = "https"\n'
                         'port_config = "config.json"\nport_key = "web.port"\n')


@pytest.mark.parametrize(("content", "expected"), [
    (None, (8453, "declared; config.json is not here")),
    ({"web": {}}, (8453, "declared; config.json sets no web.port")),
    ({"web": {"port": 9001}}, (9001, "config.json web.port")),
    ({"web": {"port": "x"}}, (None, "config.json web.port is not a TCP port")),
    ("{not json", (None, "config.json cannot be read or does not parse")),
])
def test_the_local_config_sets_the_port_and_the_declaration_is_the_fallback(
        tmp_path: Path, content: Any, expected: tuple[int | None, str]) -> None:
    endpoint = m.parse_migration({"port": ":8453", "install": {"endpoint": {"port_config": "config.json",
                                  "port_key": "web.port"}, "migrate": {}}}).endpoint
    assert endpoint is not None
    if content is not None:
        (tmp_path / "config.json").write_text(content if isinstance(content, str) else json.dumps(content),
                                              encoding="utf-8")
    assert m.local_port(tmp_path, endpoint) == expected


@pytest.mark.parametrize("endpoint", [{"port_config": "../x.json"}, {"port_config": 3}, {"port_key": "a..b"}])
def test_a_malformed_port_config_names_the_key(endpoint: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="port_"):
        m.parse_migration({"port": ":8453", "install": {"endpoint": endpoint, "migrate": {}}})


def test_verify_asks_the_configured_port_on_the_scheme_that_answers(tmp_path: Path) -> None:
    root, old = _clone(tmp_path, PORT_TOML), _old(tmp_path)
    config = json.loads((old / "config.json").read_text(encoding="utf-8"))
    (old / "config.json").write_text(json.dumps({**config, "web": {"port": 9001}}), encoding="utf-8")
    head = _git(root, "rev-parse", "HEAD")
    asked: list[str] = []

    def fetch(endpoint: m.Endpoint) -> dict[str, Any] | None:
        asked.append(m._url(endpoint))
        return {"git_sha": head} if endpoint.scheme == "http" else None

    (root / ".venv").mkdir()
    report = m.migrate(root, old, installer=StubInstaller(), what_if=False, stop=False, runner=_runner,
                       snapshot_fn=lambda: _snap(_proc(100, root), port=9001, listener=100), fetch=fetch)
    assert not report.failed, report.render()
    assert asked[:2] == ["https://127.0.0.1:9001/api/version", "http://127.0.0.1:9001/api/version"]
    assert _states(report, "verify") == {"http://127.0.0.1:9001/api/version": "ok", "port 9001 owner": "ok"}


def test_verify_is_unknown_when_the_local_config_cannot_tell_the_port(tmp_path: Path) -> None:
    root, old = _clone(tmp_path, PORT_TOML), _old(tmp_path)
    (old / "config.json").write_text("{not json", encoding="utf-8")
    report = _migrate(root, old, _snap(_proc(100, root), port=8453, listener=100))
    assert report.failed and _states(report, "verify") == {"endpoint port": "unknown"}


@pytest.mark.parametrize("case", ["dirty", "nested", "missing"])
def test_guard_refuses_before_anything_is_copied(tmp_path: Path, case: str) -> None:
    root, old = _clone(tmp_path), _old(tmp_path)
    if case == "dirty":
        (root / "stray.txt").write_text("x", encoding="utf-8")
    target = {"nested": root / "sub", "missing": tmp_path / "nowhere"}.get(case, old)
    if case == "nested":
        target.mkdir()
    stub = StubInstaller()
    report = _migrate(root, target, _snap(), installer=stub)
    assert report.failed and "refused" in _states(report, "guard").values()
    assert not (root / "config.json").exists() and stub.calls == []


def test_a_failed_install_does_not_start_the_app(tmp_path: Path) -> None:
    root, old = _clone(tmp_path), _old(tmp_path)
    report = _migrate(root, old, _snap(), installer=StubInstaller(failed=True))
    assert report.failed and _states(report, "start") == {"start": "not run"} and "verify" not in report.rows


def test_installer_rejects_migration_flags_without_migrate_from(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        installer.main(tmp_path, ["-StopOld"])


# ---------------------------------------------------------------- stopping

@pytest.mark.parametrize("spelling", ["old", "junction"])
def test_stop_refuses_when_this_run_was_started_from_the_old_copy(tmp_path: Path, spelling: str) -> None:
    old = tmp_path / "old"
    host = old if spelling == "old" else _junction(tmp_path / spelling, old)
    me = os.getpid()
    snap = m.Snapshot({me: m.Proc(me, 50, r"C:\Python\python.exe", "python x"), 50: _proc(50, host)}, {})
    report = m.MigrationReport(mode="migrate", what_if=False)
    calls: list[Any] = []
    m.stop_old(old, 8453, report, lambda c, **k: calls.append(c), lambda: snap)
    assert report.failed and _states(report, "stop") == {"old copy": "refused"} and calls == []


def test_stop_kills_each_tree_root_by_pid_and_waits_for_the_port(tmp_path: Path) -> None:
    old = tmp_path / "old"
    running = _snap(_proc(10, old), _proc(11, old, ppid=10), port=8453, listener=11)
    snaps = iter([running, _snap(), _snap()])
    calls: list[list[str]] = []
    report = m.MigrationReport(mode="migrate", what_if=False)
    m.stop_old(old, 8453, report, lambda c, **k: calls.append(c), lambda: next(snaps))
    assert calls == [["taskkill", "/PID", "10", "/T", "/F"]]
    assert _states(report, "stop") == {"old copy": "stopped", "port 8453": "ok"}


def test_stop_fails_naming_what_still_holds_the_port(tmp_path: Path) -> None:
    other = m.Proc(77, 1, r"C:\Other\server.exe", "server")
    report = m.MigrationReport(mode="migrate", what_if=False)
    m.stop_old(tmp_path / "old", 8453, report, lambda c, **k: None, lambda: _snap(other, port=8453, listener=77))
    assert report.failed and "PID 77 server.exe" in report.rows["stop"][-1][2]


# ---------------------------------------------------------------- which listeners hold the port

OUTSIDER = m.Proc(77, 1, r"C:\Other\proxy.exe", "proxy")


def _listed(procs: list[m.Proc], *listeners: tuple[int, str]) -> m.Snapshot:
    """What ``take_snapshot`` reads from a faked listing: ``(pid, local address)`` listeners on port 8453."""
    data = {"procs": [{"pid": p.pid, "ppid": p.ppid, "exe": p.exe, "cmd": p.cmdline} for p in procs],
            "ports": [{"port": 8453, "pid": pid, "address": address} for pid, address in listeners]}
    snap = m.take_snapshot(lambda c, **k: subprocess.CompletedProcess(c, 0, stdout=json.dumps(data)))
    assert snap is not None
    return snap


def _stop_report(tmp_path: Path, snap: m.Snapshot) -> m.MigrationReport:
    report = m.MigrationReport(mode="migrate", what_if=False)
    m.stop_old(tmp_path / "old", 8453, report, lambda c, **k: None, lambda: snap)
    return report


@pytest.mark.parametrize("address", ["192.0.2.7", "2001:db8::7"])
def test_a_listener_that_cannot_answer_loopback_neither_holds_nor_owns_the_port(tmp_path: Path, address: str) -> None:
    stop = _stop_report(tmp_path, _listed([OUTSIDER], (77, address)))
    assert not stop.failed and _states(stop, "stop")["port 8453"] == "ok", stop.render()
    root, old = _clone(tmp_path), _old(tmp_path)
    report = _migrate(root, old, _listed([_proc(100, root), OUTSIDER], (100, "127.0.0.1"), (77, address)))
    assert not report.failed, report.render()
    assert [row[2].split()[:2] for row in report.rows["verify"] if row[1] == "port 8453 owner"] == [["PID", "100"]]


@pytest.mark.parametrize("address", ["0.0.0.0", "::", "127.0.0.1", "::1", ""])
def test_a_loopback_wildcard_or_unlisted_address_from_outside_still_counts(tmp_path: Path, address: str) -> None:
    snap = _listed([OUTSIDER], (77, "192.0.2.7"), (77, address))
    stop = _stop_report(tmp_path, snap)
    assert stop.failed and "PID 77 proxy.exe" in stop.rows["stop"][-1][2]
    report = m.MigrationReport(mode="migrate", what_if=False)
    m._verify_owner(tmp_path / "new", None, 8453, report, lambda: snap)
    assert _states(report, "verify") == {"port 8453 owner": "unknown"}


# ---------------------------------------------------------------- -InPlace

def test_backup_name_counts_up_within_the_day(tmp_path: Path) -> None:
    folder = tmp_path / "app"
    day = datetime.date(2026, 11, 27)
    assert installer_inplace.backup_path(folder, day).name == "app.bak-20261127-1"
    (tmp_path / "app.bak-20261127-1").mkdir()
    assert installer_inplace.backup_path(folder, day).name == "app.bak-20261127-2"


def test_in_place_what_if_names_the_backup_and_touches_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer_inplace.m.time, "sleep", lambda _s: None)
    origin = _clone(tmp_path / "o")
    folder = tmp_path / "app"
    _git(tmp_path, "clone", "-q", str(origin), str(folder))
    cwd = os.getcwd()
    try:
        report = installer_inplace.in_place(folder, what_if=True, as_json=False, runner=_runner,
                                            snapshot_fn=lambda: installer_inplace.m.Snapshot({}, {}),
                                            today=datetime.date(2026, 11, 27))
    finally:
        os.chdir(cwd)
    assert not report.failed, report.render()
    rows = {item: (state, detail) for state, item, detail in report.rows["in place"]}
    assert rows["app"] == ("would rename", "to app.bak-20261127-1, kept as a working checkout")
    assert rows[str(origin)][0] == "would clone"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["app", "o"]


def test_in_place_what_if_names_every_file_it_would_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(installer_inplace.m.time, "sleep", lambda _s: None)
    origin = _clone(tmp_path / "o")
    folder = tmp_path / "app"
    _git(tmp_path, "clone", "-q", str(origin), str(folder))
    shutil.copytree(_old(tmp_path / "src"), folder, dirs_exist_ok=True)
    cwd = os.getcwd()
    try:
        report = installer_inplace.in_place(folder, what_if=True, as_json=False, runner=_runner,
                                            snapshot_fn=lambda: installer_inplace.m.Snapshot({}, {}))
    finally:
        os.chdir(cwd)
    assert not report.failed, report.render()
    would = {item for state, item, _ in report.rows["copy"] if state == "would copy"}
    assert would == {"config.json", ".env", "data/state.db", "data/logs/a.log"}
    assert "data/state.db-wal" not in {item for _, item, _ in report.rows["copy"]}
    assert CANARY not in report.render() and (folder / "config.json").is_file()


def test_in_place_refuses_a_folder_without_an_origin(tmp_path: Path) -> None:
    folder = _clone(tmp_path)
    cwd = os.getcwd()
    try:
        report = installer_inplace.in_place(folder, what_if=True, as_json=False, runner=_runner,
                                            snapshot_fn=lambda: None)
    finally:
        os.chdir(cwd)
    assert report.failed and _states(report, "guard") == {"folder": "refused"}


# ---------------------------------------------------------------- -Replace

OLD_TOML = """port = ":8453"

[install]
samples = []
"""  # an install from before [install.migrate] existed


def _pair(tmp_path: Path, with_incoming: bool = True) -> tuple[Path, Path, Path]:
    """An origin whose first commit is an old install's, the install at that commit, and a fresh clone beside it."""
    origin = _clone(tmp_path / "o", OLD_TOML)
    folder = tmp_path / "app"
    _git(tmp_path, "clone", "-q", str(origin), str(folder))
    (origin / ".fleet.toml").write_text(TOML, encoding="utf-8")
    _git(origin, "-c", f"core.hooksPath={tmp_path / 'no-hooks'}", "-c", "user.name=t",
         "-c", "user.email=t@example.invalid", "commit", "-qam", "new")
    incoming = installer_inplace.incoming_path(folder)
    if with_incoming:
        _git(tmp_path, "clone", "-q", str(origin), str(incoming))
    return origin, folder, incoming


def _replace(folder: Path, incoming: Path | None, what_if: bool, runner: Any = _runner,
             snap: m.Snapshot | None = None) -> m.MigrationReport:
    cwd = os.getcwd()
    try:
        return installer_inplace.replace(folder, incoming, what_if=what_if, as_json=True, runner=runner,
                                         snapshot_fn=lambda: snap if snap is not None else m.Snapshot({}, {}),
                                         today=datetime.date(2026, 11, 27))
    finally:
        os.chdir(cwd)


def _child_ok(command: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
    """The moved clone's `setup.bat -MigrateFrom` succeeds; everything else as `_runner`."""
    if isinstance(command, str) and "-MigrateFrom" in command:
        return subprocess.CompletedProcess(command, 0, stdout='{"ok": true}')
    return _runner(command, **kwargs)


def _listing(tmp_path: Path) -> list[str]:
    return sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*") if ".git" not in p.parts)


def test_origins_match_whatever_their_spelling() -> None:
    assert installer_inplace.same_origin("https://github.com/o/App.git", "https://github.com/o/app/")
    assert installer_inplace.same_origin(r"E:\tmp\origin.git", "e:/tmp/origin")
    assert not installer_inplace.same_origin("https://github.com/o/app", "https://github.com/o/other")


def test_replace_what_if_lists_the_clone_declaration_for_an_old_install_and_touches_nothing(tmp_path: Path) -> None:
    _, folder, incoming = _pair(tmp_path)
    shutil.copytree(_old(tmp_path / "src"), folder, dirs_exist_ok=True)
    shutil.rmtree(tmp_path / "src")
    before = _listing(tmp_path)
    report = _replace(folder, incoming, what_if=True)
    assert not report.failed, report.render()
    assert _listing(tmp_path) == before
    rows = report.rows["in place"]
    assert rows[0] == ("would rename", "app", "to app.bak-20261127-1, kept as a working checkout")
    assert rows[1] == ("would rename", "app.incoming", "to app")
    would = {item for state, item, _ in report.rows["copy"] if state == "would copy"}
    assert would == {"config.json", ".env", "data/state.db", "data/logs/a.log"}, "not the clone's declaration"


def test_replace_swaps_the_clone_in_and_keeps_uncommitted_edits_in_the_backup(tmp_path: Path) -> None:
    _, folder, incoming = _pair(tmp_path)
    (folder / ".gitignore").write_text("edited by hand\n", encoding="utf-8")
    calls: list[tuple[str, Path]] = []

    def runner(command: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if isinstance(command, str):
            calls.append((command, kwargs["cwd"]))
        return _child_ok(command, **kwargs)

    report = _replace(folder, incoming, what_if=False, runner=runner)
    assert not report.failed, report.render()
    backup = tmp_path / "app.bak-20261127-1"
    assert not incoming.exists() and (folder / ".git").is_dir()
    assert (backup / ".gitignore").read_text(encoding="utf-8") == "edited by hand\n"
    assert "[install.migrate]" in (folder / ".fleet.toml").read_text(encoding="utf-8")
    assert len(calls) == 1 and f'-MigrateFrom "{backup}"' in calls[0][0] and calls[0][1] == folder
    assert report.migration == {"ok": True}


@pytest.mark.parametrize("case", ["other origin", "untracked file", "venv", "running"])
def test_replace_refuses_a_clone_that_is_not_fresh_or_not_the_same_app(tmp_path: Path, case: str) -> None:
    _, folder, incoming = _pair(tmp_path)
    snap = None
    if case == "other origin":
        _git(incoming, "remote", "set-url", "origin", "https://example.invalid/other.git")
    elif case == "untracked file":
        (incoming / "stray.txt").write_text("x", encoding="utf-8")
    elif case == "venv":
        (incoming / ".venv").mkdir()
    else:
        snap = _snap(_proc(4242, incoming))
    report = _replace(folder, incoming, what_if=False, runner=_child_ok, snap=snap)
    assert report.failed and _states(report, "guard")["incoming clone"] == "refused"
    assert folder.is_dir() and incoming.is_dir() and not list(tmp_path.glob("app.bak-*"))


def test_a_failed_move_of_the_clone_renames_the_backup_back(tmp_path: Path) -> None:
    folder, backup = tmp_path / "app", tmp_path / "app.bak-20261127-1"
    folder.mkdir()
    report = m.MigrationReport(mode="replace", what_if=False)
    assert not installer_inplace._swap(folder, tmp_path / "missing.incoming", backup, None, report)
    assert folder.is_dir() and not backup.exists()
    state, item, detail = report.rows["in place"][-1]
    assert (state, item) == ("failed", "rename") and "renamed back" in detail and "tray.bat --restart" in detail


def test_in_place_clones_beside_the_install_before_it_stops_anything_then_swaps(tmp_path: Path) -> None:
    _, folder, incoming = _pair(tmp_path, with_incoming=False)
    report = _replace(folder, None, what_if=False, runner=_child_ok)
    assert not report.failed, report.render()
    states = [state for state, _, _ in report.rows["in place"]]
    assert states == ["cloned", "renamed", "renamed", "ok"]
    assert not incoming.exists() and (tmp_path / "app.bak-20261127-1" / ".git").is_dir()
    assert "[install.migrate]" in (folder / ".fleet.toml").read_text(encoding="utf-8")


def test_in_place_refuses_when_an_incoming_clone_is_already_there(tmp_path: Path) -> None:
    _, folder, _ = _pair(tmp_path)
    report = _replace(folder, None, what_if=True)
    assert report.failed and _states(report, "guard")["incoming clone"] == "refused"
