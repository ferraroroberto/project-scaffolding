"""The clone-and-setup installer (`src/installer.py`, run by `setup.bat`).

Each test builds a throwaway repo under `tmp_path` and drives `installer.run` with
a fake runner in place of `subprocess.run`, so no venv is created and nothing is
installed: the runner records each command and plays the side effect the real
one would have (a venv's interpreter appearing, a probe's exit code).
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from src import installer
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXED_NOW = datetime.datetime(2026, 1, 2, 3, 4, 5)


class FakeRunner:
    """Stands in for `subprocess.run`: records commands, creates the venv, answers probes."""

    def __init__(self, root: Path, probe_codes: dict[str, int] | None = None, fail_pip: bool = False) -> None:
        self.root = root
        self.calls: list[list[str]] = []
        self.probe_codes = probe_codes or {}
        self.fail_pip = fail_pip

    def __call__(self, command: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(command))
        code = 0
        if command[1:3] == ["-m", "venv"]:
            python = installer.venv_python(self.root)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")
        elif "pip" in command:
            code = 1 if self.fail_pip else 0
        else:
            code = self.probe_codes.get(command[-1], 0)
        return subprocess.CompletedProcess(command, code)


def _repo(tmp_path: Path, install_table: str = "") -> Path:
    root = tmp_path / "app"
    (root / "config").mkdir(parents=True)
    (root / "requirements.txt").write_text("requests==2.32.3\n", encoding="utf-8")
    (root / "config" / "config.sample.json").write_text(
        json.dumps({"_comment": "sample", "port": 8000, "ui": {"theme": "dark", "dense": False}}), encoding="utf-8")
    (root / "config" / "apps.sample.json").write_text(json.dumps({"apps": [], "version": 1}), encoding="utf-8")
    table = install_table or 'settings = ["config/config.json"]'
    (root / ".fleet.toml").write_text(f"[install]\n{table}\n", encoding="utf-8")
    return root


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def _run(root: Path, runner: FakeRunner, **kwargs: Any) -> installer.Report:
    return installer.run(root, runner=runner, now=lambda: FIXED_NOW, what_if=kwargs.pop("what_if", False), **kwargs)


def _checklist(report: installer.Report) -> dict[str, str]:
    return {item: state for state, item, _ in report.checklist}


def test_fresh_install_creates_venv_requirements_and_configs(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    runner = FakeRunner(root)
    report = _run(root, runner)
    assert not report.failed
    statuses = {item: status for status, item, _ in report.lines}
    assert statuses == {".venv": "created", "requirements": "installed",
                        "config/apps.json": "created", "config/config.json": "created"}
    assert (root / "config" / "config.json").read_bytes() == (root / "config" / "config.sample.json").read_bytes()
    assert _checklist(report) == {"Python environment (.venv)": "ok", "Requirements installed": "ok",
                                  "config/apps.json": "ok", "config/config.json": "ok"}


def test_second_run_reports_unchanged_and_writes_nothing(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _run(root, FakeRunner(root))
    before = _snapshot(root)
    runner = FakeRunner(root)
    report = _run(root, runner)
    assert report.changes == []
    assert "-> unchanged: nothing to do" in installer.render(report)
    assert runner.calls == []
    assert _snapshot(root) == before


def test_requirements_reinstall_only_when_the_file_changes(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _run(root, FakeRunner(root))
    (root / "requirements.txt").write_text("requests==2.32.4\n", encoding="utf-8")
    runner = FakeRunner(root)
    report = _run(root, runner)
    assert ("installed", "requirements", "") in report.lines
    assert len([c for c in runner.calls if "pip" in c]) == 1


def test_failed_pip_records_no_stamp(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    report = _run(root, FakeRunner(root, fail_pip=True))
    assert report.failed
    assert not (root / ".venv" / installer.REQUIREMENTS_STAMP).exists()
    assert _checklist(report)["Requirements installed"] == "unknown"


def test_settings_top_up_adds_missing_keys_after_a_backup_and_keeps_values(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    _run(root, FakeRunner(root))
    target = root / "config" / "config.json"
    original = {"port": 9999, "ui": {"theme": "light"}, "owner_only": True}
    target.write_text(json.dumps(original), encoding="utf-8")
    report = _run(root, FakeRunner(root))
    updated = json.loads(target.read_text(encoding="utf-8"))
    assert updated == {"port": 9999, "ui": {"theme": "light", "dense": False}, "owner_only": True}
    assert "_comment" not in updated
    backup = root / "config" / "config.json.bak-20260102-030405"
    assert json.loads(backup.read_text(encoding="utf-8")) == original
    added = [line for line in report.lines if line[0] == "added"]
    assert added == [("added", "config/config.json", "keys: ui.dense (backup config.json.bak-20260102-030405)")]


def test_registry_is_never_rewritten(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    registry = root / "config" / "apps.json"
    registry.write_text('{ "apps": ["mine"] }', encoding="utf-8")
    report = _run(root, FakeRunner(root))
    assert registry.read_text(encoding="utf-8") == '{ "apps": ["mine"] }'
    assert ("unchanged", "config/apps.json", "the owner's own list, never rewritten") in report.lines
    assert not list((root / "config").glob("apps.json.bak-*"))


def test_unparseable_settings_file_is_left_alone_and_fails_the_run(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    target = root / "config" / "config.json"
    target.write_text("{not json", encoding="utf-8")
    report = _run(root, FakeRunner(root))
    assert report.failed
    assert target.read_text(encoding="utf-8") == "{not json"
    assert any(status == "left alone" for status, item, _ in report.lines if item == "config/config.json")
    assert _checklist(report)["config/config.json"] == "missing"


def test_what_if_changes_nothing_and_runs_nothing(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "config" / "config.json").write_text(json.dumps({"port": 1}), encoding="utf-8")
    before = _snapshot(root)
    runner = FakeRunner(root)
    report = _run(root, runner, what_if=True, startup=True)
    assert runner.calls == []
    assert _snapshot(root) == before
    statuses = {item: status for status, item, _ in report.lines}
    assert statuses[".venv"] == "would create"
    assert statuses["requirements"] == "would install"
    assert statuses["config/apps.json"] == "would create"
    assert statuses["config/config.json"] == "would add"
    assert installer.render(report).startswith("What-if: nothing below is changed.")


def test_declared_pair_outside_the_sample_convention(tmp_path: Path) -> None:
    root = _repo(tmp_path, '[[install.config]]\nsample = "webapp/tunnel.sample.yml"\ntarget = "webapp/tunnel.yml"')
    (root / "webapp").mkdir()
    (root / "webapp" / "tunnel.sample.yml").write_text("url: x\n", encoding="utf-8")
    report = _run(root, FakeRunner(root))
    assert (root / "webapp" / "tunnel.yml").read_text(encoding="utf-8") == "url: x\n"
    assert _checklist(report)["webapp/tunnel.yml"] == "ok"


def test_checklist_items_report_ok_missing_and_unknown(tmp_path: Path) -> None:
    table = "\n".join([
        "[[install.check]]", 'name = "Certificate"', 'paths = ["certs/cert.pem"]', 'hint = "issue one"',
        "[[install.check]]", 'name = "Tool"', 'which = "git"',
        "[[install.check]]", 'name = "Password"', 'command = ["{python}", "-m", "pw", "missing"]',
        "[[install.check]]", 'name = "Odd probe"', 'command = ["{python}", "-m", "pw", "weird"]',
    ])
    root = _repo(tmp_path, table)
    report = _run(root, FakeRunner(root, probe_codes={"missing": 1, "weird": 2}))
    states = {item: (state, detail) for state, item, detail in report.checklist}
    assert states["Certificate"] == ("missing", "issue one")
    assert states["Tool"][0] == ("ok" if shutil.which("git") else "missing")
    assert states["Password"][0] == "missing"
    assert states["Odd probe"] == ("unknown", "probe exited 2")


def test_python_probe_before_a_venv_exists_is_unknown(tmp_path: Path) -> None:
    root = _repo(tmp_path, '[[install.check]]\nname = "Password"\ncommand = ["{python}", "-m", "pw", "status"]')
    report = _run(root, FakeRunner(root), what_if=True)
    assert ("unknown", "Password", "not checked before .venv exists") in report.checklist


STARTUP = '[install.startup]\ncheck = ["{python}", "-m", "auto", "status"]\nregister = ["{python}", "-m", "auto", "enable"]'


def test_startup_is_registered_only_with_the_flag(tmp_path: Path) -> None:
    root = _repo(tmp_path, STARTUP)
    runner = FakeRunner(root, probe_codes={"status": 1})
    report = _run(root, runner)
    assert ("not registered", "start at log on", "pass -Startup to add it") in report.lines
    assert not any(c[-1] == "enable" for c in runner.calls)
    report = _run(root, runner, startup=True)
    assert ("registered", "start at log on", "") in report.lines
    assert any(c[-1] == "enable" for c in runner.calls)


def test_existing_startup_is_kept(tmp_path: Path) -> None:
    root = _repo(tmp_path, STARTUP)
    runner = FakeRunner(root, probe_codes={"status": 0})
    report = _run(root, runner, startup=True)
    assert ("kept", "start at log on", "already registered") in report.lines
    assert not any(c[-1] == "enable" for c in runner.calls)
    assert _checklist(report)["Start at log on"] == "ok"


def test_dependency_step_reruns_only_when_its_inputs_change(tmp_path: Path) -> None:
    root = _repo(tmp_path, '[install.deps]\ncommand = ["npm", "ci"]\ninputs = ["package-lock.json"]')
    (root / "package-lock.json").write_text("{}", encoding="utf-8")
    runner = FakeRunner(root)
    _run(root, runner)
    _run(root, runner)
    assert [c for c in runner.calls if c[0] == "npm"] == [["npm", "ci"]]
    (root / "package-lock.json").write_text('{"v": 2}', encoding="utf-8")
    report = _run(root, runner)
    assert ("installed", "dependency step", "") in report.lines
    assert _checklist(report)["Dependency step"] == "ok"


@pytest.mark.parametrize("table", [
    'settings = "config/config.json"',
    '[[install.check]]\nname = "Both"\npaths = ["a"]\nwhich = "b"',
    '[install.startup]\ncheck = ["x"]',
    "requirements = 3",
])
def test_malformed_install_table_fails_before_any_step(tmp_path: Path, table: str) -> None:
    root = _repo(tmp_path, table)
    runner = FakeRunner(root)
    report = _run(root, runner)
    assert report.failed
    assert runner.calls == []
    assert report.lines[0][1] == ".fleet.toml [install]"


def test_no_fleet_toml_uses_the_defaults(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / ".fleet.toml").unlink()
    report = _run(root, FakeRunner(root))
    assert not report.failed
    assert (root / "config" / "config.json").exists()


def test_setup_bat_runs_the_module_isolated_with_its_flags_passed_through() -> None:
    template = (REPO_ROOT / "setup.bat.template").read_text(encoding="ascii")
    assert r'"%PY_EXE%" %PY_ARGS% -I "%SCRIPT_DIR%src\installer.py" %*' in template


def test_isolated_script_run_never_imports_the_apps_src_package(tmp_path: Path) -> None:
    """setup.bat's command line on a fresh tree: a broken src package and a stdlib-shadowing module are never loaded."""
    root = _repo(tmp_path)
    (root / "src").mkdir()
    shutil.copyfile(REPO_ROOT / "src" / "installer.py", root / "src" / "installer.py")
    poison = "raise ImportError('loaded from the app tree')\n"
    (root / "src" / "__init__.py").write_text(poison, encoding="utf-8")
    (root / "src" / "json.py").write_text(poison, encoding="utf-8")
    before = _snapshot(root)
    done = subprocess.run([sys.executable, "-I", str(root / "src" / "installer.py"), "-WhatIf"], cwd=root,
                          capture_output=True, text=True, encoding="utf-8", timeout=60, check=False,
                          creationflags=NO_WINDOW)
    assert done.returncode == 0, done.stderr
    assert "would create    .venv" in done.stdout
    assert _snapshot(root) == before
