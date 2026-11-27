"""The clone-and-setup installer (`src/installer.py`, run by `setup.bat`).

Each test builds a throwaway repo under `tmp_path` and drives `installer.run` with
a fake runner in place of `subprocess.run`, so no venv is created and nothing is
installed: the runner records each command and plays the side effect the real
one would have (a venv's interpreter appearing, a probe's exit code).
"""

from __future__ import annotations

import datetime
import hashlib
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

    def __init__(self, root: Path, probe_codes: dict[str, int] | None = None, fail_pip: bool = False,
                 git: str = "ignored", venv_version: str = "3.14", probe_output: str = "") -> None:
        self.root = root
        self.calls: list[list[str]] = []
        self.probe_codes = probe_codes or {}
        self.fail_pip = fail_pip
        self.git = git
        self.venv_version = venv_version
        self.probe_output = probe_output

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(command))
        code = 0
        if command[:2] == ["git", "check-ignore"]:
            if self.git == "real":
                return subprocess.run(command, **kwargs)  # no-window-exempt: kwargs carry the installer's own creationflags=NO_WINDOW
            if self.git == "absent":
                raise FileNotFoundError("git")
            code = {"ignored": 0, "not ignored": 1, "not a repo": 128}[self.git]
        elif command[1:3] == ["-m", "venv"]:
            python = installer.venv_python(self.root)
            python.parent.mkdir(parents=True, exist_ok=True)
            python.write_text("", encoding="utf-8")
        elif "pip" in command:
            code = 1 if self.fail_pip else 0
        elif command[-1] == installer.PYTHON_VERSION_SNIPPET:
            return subprocess.CompletedProcess(command, 0, stdout=self.venv_version + "\n")
        else:
            code = self.probe_codes.get(command[-1], 0)
        return subprocess.CompletedProcess(command, code, stdout=self.probe_output)


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
    return {item: state for state, item, _ in report.required + report.optional}


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


def _stale_settings(tmp_path: Path) -> tuple[Path, Path, bytes]:
    root = _repo(tmp_path)
    target = root / "config" / "config.json"
    target.write_text(json.dumps({"port": 9999, "token": "s3cret"}), encoding="utf-8")
    return root, target, target.read_bytes()


def _assert_untouched(root: Path, target: Path, before: bytes) -> None:
    assert target.read_bytes() == before
    assert not list(target.parent.glob("config.json.bak-*"))


def test_top_up_is_refused_when_the_backup_would_not_be_gitignored(tmp_path: Path) -> None:
    root, target, before = _stale_settings(tmp_path)
    report = _run(root, FakeRunner(root, git="not ignored"))
    assert report.failed
    _assert_untouched(root, target, before)
    [(status, _, detail)] = [line for line in report.lines if line[1] == "config/config.json"]
    assert status == "refused"
    assert installer.BACKUP_IGNORE_PATTERN in detail


@pytest.mark.parametrize("git", ["not a repo", "absent"])
def test_top_up_is_not_confirmed_when_git_cannot_tell(tmp_path: Path, git: str) -> None:
    root, target, before = _stale_settings(tmp_path)
    report = _run(root, FakeRunner(root, git=git))
    assert report.failed
    _assert_untouched(root, target, before)
    assert [line[0] for line in report.lines if line[1] == "config/config.json"] == ["not confirmed"]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git on PATH")
def test_a_config_only_ignore_rule_does_not_cover_the_backup_until_the_pattern_is_added(tmp_path: Path) -> None:
    root, target, before = _stale_settings(tmp_path)
    subprocess.run(["git", "init", "-q", str(root)], check=True, creationflags=NO_WINDOW)
    (root / ".gitignore").write_text("config/*.json\n", encoding="utf-8")
    report = _run(root, FakeRunner(root, git="real"))
    assert [line[0] for line in report.lines if line[1] == "config/config.json"] == ["refused"]
    _assert_untouched(root, target, before)
    (root / ".gitignore").write_text(f"config/*.json\n{installer.BACKUP_IGNORE_PATTERN}\n", encoding="utf-8")
    report = _run(root, FakeRunner(root, git="real"))
    assert not report.failed
    assert [line[0] for line in report.lines if line[1] == "config/config.json"] == ["added"]
    assert (root / "config" / "config.json.bak-20260102-030405").read_bytes() == before


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
    assert [c[:2] for c in runner.calls] == [["git", "check-ignore"]]
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
    # No item declares a level: all are optional, so none of them fails setup.
    assert not report.failed
    states = {item: (state, detail) for state, item, detail in report.optional}
    unnamed = "unlocks a feature the declaration does not name"
    assert states["Certificate"] == ("off", f"{unnamed}; issue one")
    assert states["Tool"][0] == ("available" if shutil.which("git") else "off")
    assert states["Password"][0] == "off"
    assert states["Odd probe"] == ("unknown", f"{unnamed}; probe exited 2")


def test_python_probe_before_a_venv_exists_is_unknown(tmp_path: Path) -> None:
    root = _repo(tmp_path, '[[install.check]]\nname = "Password"\ncommand = ["{python}", "-m", "pw", "status"]')
    report = _run(root, FakeRunner(root), what_if=True)
    [(state, item, detail)] = report.optional
    assert (state, item) == ("unknown", "Password")
    assert "not checked before .venv exists" in detail


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
    assert _checklist(report)["Start at log on"] == "available"


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
    '[[install.check]]\nname = "A"\nwhich = "b"\nlevel = "optional"',
    '[[install.check]]\nname = "A"\nwhich = "b"\nlevel = "needed"',
    '[[install.check]]\nname = "A"\nwhich = "b"\nlevel = "required"\nblocks = "x"',
    '[[install.check]]\nname = "A"\npython = 3.14',
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


# One sample declaration with every level: a minimum Python and two optional features.
def _sample_declaration(python_minimum: str = "3.0") -> str:
    return "\n".join([
        "[[install.check]]", 'name = "Interpreter"', f'python = "{python_minimum}"', 'hint = "install it, then rerun"',
        "[[install.check]]", 'name = "Recording"', 'level = "optional"', 'blocks = "recording"',
        'command = ["{python}", "-m", "pw", "missing"]', 'hint = "put ffmpeg on PATH"',
        "[[install.check]]", 'name = "Phone sign-in"', 'level = "optional"', 'blocks = "remote sign-in"',
        'command = ["{python}", "-m", "pw", "weird"]',
    ])


SAMPLE_CODES = {"missing": 1, "weird": 2}


def test_a_required_python_that_is_not_available_stops_before_any_install(tmp_path: Path) -> None:
    root = _repo(tmp_path, _sample_declaration("99.0"))
    before = _snapshot(root)
    runner = FakeRunner(root, probe_codes=SAMPLE_CODES)
    report = _run(root, runner)
    assert report.failed and report.stopped
    assert runner.calls == []
    assert _snapshot(root) == before
    [(state, item, detail)] = report.required
    assert (state, item) == ("missing", "Interpreter")
    assert "needs 99.0 or newer" in detail and "install it, then rerun" in detail
    text = installer.render(report)
    assert "nothing was installed or written" in text
    assert "Setup failed" in text and "Optional features:" not in text


@pytest.mark.parametrize(("found", "state"), [("3.12", "missing"), ("not a version", "unknown")])
def test_the_existing_venv_is_the_python_that_is_checked(tmp_path: Path, found: str, state: str) -> None:
    root = _repo(tmp_path, _sample_declaration("3.14"))
    python = installer.venv_python(root)
    python.parent.mkdir(parents=True)
    python.write_text("", encoding="utf-8")
    runner = FakeRunner(root, venv_version=found)
    report = _run(root, runner)
    assert report.stopped and report.failed
    assert [row[0] for row in report.required] == [state]
    assert not any("pip" in command for command in runner.calls)
    assert "not a version" not in installer.render(report)


def test_optional_items_never_fail_setup_and_each_names_what_it_unlocks(tmp_path: Path) -> None:
    root = _repo(tmp_path, _sample_declaration())
    report = _run(root, FakeRunner(root, probe_codes=SAMPLE_CODES))
    assert not report.failed
    assert {state for state, _, _ in report.required} == {"ok"}
    assert report.optional == [
        ("off", "Recording", "unlocks recording; put ffmpeg on PATH"),
        ("unknown", "Phone sign-in", "unlocks remote sign-in; probe exited 2"),
    ]
    assert "Setup complete: every required item is ok." in installer.render(report)


@pytest.mark.parametrize(("code", "state"), [(1, "missing"), (2, "unknown")])
def test_a_required_probe_needing_no_venv_stops_setup_unless_it_is_ok(tmp_path: Path, code: int, state: str) -> None:
    root = _repo(tmp_path, '[[install.check]]\nname = "Node"\nlevel = "required"\ncommand = ["node", "probe"]')
    runner = FakeRunner(root, probe_codes={"probe": code})
    report = _run(root, runner)
    assert report.stopped and report.failed
    assert runner.calls == [["node", "probe"]]
    assert [row[:2] for row in report.required] == [(state, "Node")]


@pytest.mark.parametrize(("check", "state"), [
    ('paths = ["vendor/model.bin"]', "missing"),
    ('command = ["{python}", "-m", "pw", "weird"]', "unknown"),
])
def test_a_required_item_setup_may_create_is_checked_after_the_install(tmp_path: Path, check: str, state: str) -> None:
    root = _repo(tmp_path, f'[[install.check]]\nname = "Needed"\nlevel = "required"\n{check}')
    # -WhatIf on a fresh clone created nothing, so the item is reported and not held against the run.
    assert not _run(root, FakeRunner(root, probe_codes=SAMPLE_CODES), what_if=True).failed
    report = _run(root, FakeRunner(root, probe_codes=SAMPLE_CODES))
    assert report.failed and not report.stopped
    assert ("installed", "requirements", "") in report.lines
    assert [row[0] for row in report.required if row[1] == "Needed"] == [state]


def test_no_probe_output_or_config_value_is_printed(tmp_path: Path) -> None:
    root = _repo(tmp_path, '[[install.check]]\nname = "Token"\ncommand = ["{python}", "-m", "pw", "missing"]')
    (root / "config" / "apps.json").write_text('{"token": "s3cret-value", broken', encoding="utf-8")
    report = _run(root, FakeRunner(root, probe_codes=SAMPLE_CODES, probe_output="s3cret-value"))
    assert report.failed  # a config that does not parse is a required item that is not ok
    assert "s3cret-value" not in installer.render(report)


def test_a_registry_that_is_a_json_list_is_ok(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    (root / "config" / "apps.json").write_text('["mine"]', encoding="utf-8")
    report = _run(root, FakeRunner(root))
    assert not report.failed
    assert _checklist(report)["config/apps.json"] == "ok"


def test_setup_bat_runs_the_module_isolated_with_its_flags_passed_through() -> None:
    template = (REPO_ROOT / "scripts" / "templates" / "setup.bat").read_text(encoding="ascii")
    assert r'"%PY_EXE%" %PY_ARGS% -I "%SCRIPT_DIR%src\installer.py" %*' in template


def test_isolated_script_run_keeps_a_failed_steps_output_and_never_imports_the_apps_src_package(tmp_path: Path) -> None:
    """setup.bat's command line, redirected to a file: the failed step's own lines land above the checklist, and a
    broken src package or a stdlib-shadowing module beside the installer is never loaded."""
    step = "import sys; print('step-stdout', flush=True); print('step-stderr', file=sys.stderr); sys.exit(3)"
    root = _repo(tmp_path, f"[install.deps]\ncommand = {json.dumps([sys.executable, '-c', step])}")
    (root / "src").mkdir()
    shutil.copyfile(REPO_ROOT / "src" / "installer.py", root / "src" / "installer.py")
    poison = "raise ImportError('loaded from the app tree')\n"
    (root / "src" / "__init__.py").write_text(poison, encoding="utf-8")
    (root / "src" / "json.py").write_text(poison, encoding="utf-8")
    # A .venv with requirements already recorded, so the dependency step is the only step that spawns.
    interpreter = installer.venv_python(root)
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text("", encoding="utf-8")
    recorded = hashlib.sha256((root / "requirements.txt").read_bytes()).hexdigest()
    (root / ".venv" / installer.REQUIREMENTS_STAMP).write_text(recorded, encoding="ascii")
    log = tmp_path / "setup.log"
    with log.open("wb") as out:
        done = subprocess.run([sys.executable, "-I", str(root / "src" / "installer.py")], cwd=root, stdout=out,
                              stderr=subprocess.STDOUT, timeout=60, check=False, creationflags=NO_WINDOW)
    text = log.read_text(encoding="utf-8", errors="replace")
    assert done.returncode == 1, text
    assert "dependency step  (exited 3)" in text, text
    for line in ("step-stdout", "step-stderr"):
        assert 0 <= text.find(line) < text.find("Required:"), text


@pytest.mark.parametrize("console", [True, False])
def test_a_step_is_denied_a_window_only_when_setup_has_no_console(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch, console: bool) -> None:
    """A CREATE_NO_WINDOW child writes to a hidden console of its own, never to the one setup.bat runs in."""
    root = _repo(tmp_path, STARTUP)
    monkeypatch.setattr(installer, "_has_console", lambda: console)
    fake = FakeRunner(root, probe_codes={"status": 1})
    steps: list[dict[str, Any]] = []

    def runner(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if not kwargs.get("capture_output"):
            steps.append(kwargs)
        return fake(command, **kwargs)

    installer.run(root, runner=runner, what_if=False, startup=True, now=lambda: FIXED_NOW)
    assert len(steps) == 3  # the venv, the requirements and the autostart register
    for kwargs in steps:
        assert kwargs["creationflags"] == (0 if console else installer.NO_WINDOW)
        assert kwargs["stdout"] is sys.stdout and kwargs["stderr"] is sys.stderr
