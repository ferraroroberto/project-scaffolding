"""Tests for the windows-only ratchet.

Three layers, mirroring `test_request_budget_ratchet.py`:

1. **Rules** on in-memory test modules: each rule fails by name on a planted
   unmarked Windows-only test and passes once it is marked, guarded, faked or
   exempted. The reference case is a test that planted a `.exe` under a fake
   `ProgramFiles` and passed only on Windows, before and after its marker.
2. **Ratchet behaviour** on throwaway git repos: every mode, a rise, vendored
   copies, and the "not confirmed" exit for anything that cannot be read through.
3. **Self-adoption**: this repo's own declaration, catalogue entry and gate wiring.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import windows_only_ratchet as wo
from src.no_window import NO_WINDOW
from tests._git_repo import git, write
from tests._ratchet_not_confirmed import assert_unreadable_file_not_confirmed, git_failure_test

REPO_ROOT = Path(__file__).resolve().parents[2]


def hits(src: str) -> list[str]:
    """`rule:line` of each finding left after coverage and exemptions in one test module."""
    return [f"{rule}:{line}" for line, rule, _ in wo.scan_source(src, "tests/test_x.py").findings]


# A trimmed copy of the test that kept the Mac nightly red: it plants chrome.exe under a fake
# ProgramFiles and expects the Windows install-folder lookup to find it, which only Windows does.
INSTALL_LOOKUP = '''\
from src.desktop import browser


def _installed(*names):
    return lambda name: f"C:/Apps/{name}.exe" if name in names else None


{marker}def test_find_browser_prefers_app_paths_then_the_install_folders(monkeypatch, tmp_path):
    exe = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    for key in browser._INSTALL_ROOT_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(browser, "_app_paths_exe", lambda name: None)
    assert browser.find_browser("chrome") is None
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    assert browser.find_browser("chrome") == str(exe)
'''



def lookup(marker: str = "") -> str:
    """The reference test, with `marker` (a decorator line) above its `def`."""
    return INSTALL_LOOKUP.replace("{marker}", marker)


# The same file's other kind of test: Windows APIs faked, never used.
FAKED = '''\
import sys
from unittest.mock import MagicMock

from src.launching import launcher


def test_stop_and_close_finds_the_window_by_its_marker(monkeypatch):
    win32gui = MagicMock(name="win32gui")
    win32gui.EnumWindows.side_effect = lambda cb, extra: [cb(h, extra) for h in (1, 2)]
    monkeypatch.setitem(sys.modules, "win32gui", win32gui)
    monkeypatch.setattr(launcher, "find_browser", lambda name: f"C:/Apps/{name}.exe")
    assert launcher.close_mirror_window("sid1") is True
'''


# ------------------------------------------------- the reference case

def test_the_unmarked_install_lookup_test_is_a_hit() -> None:
    assert hits(lookup("")) == ["win-exe-lookup:9"]


def test_the_same_test_with_the_marker_passes() -> None:
    assert hits("import pytest\n" + lookup("@pytest.mark.windows_only\n")) == []


def test_a_test_that_only_fakes_windows_apis_is_not_a_hit() -> None:
    assert hits(FAKED) == []


def test_a_faked_platform_keeps_the_install_lookup_clean() -> None:
    src = lookup("").replace(
        '    monkeypatch.setenv("ProgramFiles"', '    monkeypatch.setattr(sys, "platform", "win32")\n'
                                                 '    monkeypatch.setenv("ProgramFiles"')
    assert hits("import sys\n" + src) == []


def test_an_env_var_alone_or_a_exe_string_alone_is_not_an_install_lookup() -> None:
    redirect = 'def test_data_dir(monkeypatch, tmp_path):\n    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))\n'
    name = 'def test_name(tmp_path):\n    assert pick() == "chrome.exe"\n    assert (tmp_path / "x.txt")\n'
    assert hits(redirect) == [] and hits(name) == []


# ------------------------------------------------- win-module / win-api

def test_a_windows_module_import_is_a_hit_at_module_and_test_level() -> None:
    assert hits("import winreg\n\ndef test_a():\n    import win32api\n    from msvcrt import getch\n") == [
        "win-module:1", "win-module:4", "win-module:5"]


def test_a_windows_api_attribute_is_a_hit_through_an_alias_or_a_module_attribute() -> None:
    src = ("import ctypes\nimport subprocess as sp\n\ndef test_a(launcher):\n    ctypes.windll.user32\n"
           "    assert launcher.subprocess.CREATE_NO_WINDOW\n    sp.STARTUPINFO()\n")
    assert hits(src) == ["win-api:5", "win-api:6", "win-api:7"]
    assert hits("from os import startfile\n") == ["win-api:1"]


@pytest.mark.parametrize("src", [
    pytest.param("import sys, subprocess\n\ndef test_a():\n    f = subprocess.CREATE_NO_WINDOW "
                 "if sys.platform == 'win32' else 0\n", id="platform-ternary"),
    pytest.param("import os\n\ndef test_a():\n    if os.name == 'nt':\n        os.startfile('x')\n", id="platform-if"),
    pytest.param("try:\n    import winreg\nexcept ImportError:\n    winreg = None\n", id="try-import"),
    pytest.param("import subprocess\n\ndef test_a():\n    getattr(subprocess, 'CREATE_NO_WINDOW', 0)\n", id="getattr"),
    pytest.param("import ctypes\n\ndef test_a(monkeypatch):\n    monkeypatch.setattr(ctypes, 'windll', 1, "
                 "raising=False)\n", id="patched-by-name"),
    pytest.param("def test_a():\n    src = 'import winreg; os.startfile(p)'\n", id="inside-a-string"),
    pytest.param("def helper():\n    import winreg\n", id="non-test-function"),
])
def test_guarded_faked_or_non_test_code_is_not_a_hit(src: str) -> None:
    assert hits(src) == []


# ------------------------------------------------- win-env-read

def test_reading_a_windows_only_variable_is_a_hit_unless_the_file_sets_it() -> None:
    read = 'import os\n\ndef test_a():\n    assert os.environ["ProgramFiles"]\n'
    assert hits(read) == ["win-env-read:4"]
    sets = read + '\n\n@pytest.fixture(autouse=True)\ndef env(monkeypatch):\n    monkeypatch.setenv("PROGRAMFILES", "x")\n'
    assert hits(sets) == []
    assert hits('import os\n\ndef test_a():\n    os.environ.get("APPDATA")\n    os.environ["HOME"]\n') == []


# ------------------------------------------------- coverage

@pytest.mark.parametrize("cover", [
    pytest.param("pytestmark = pytest.mark.windows_only\n", id="pytestmark"),
    pytest.param("pytestmark = [pytest.mark.slow, pytest.mark.windows_only]\n", id="pytestmark-list"),
    pytest.param("pytestmark = pytest.mark.skipif(sys.platform != 'win32', reason='w')\n", id="pytestmark-skipif"),
    pytest.param("winreg = pytest.importorskip('winreg')\n", id="importorskip"),
    pytest.param("if sys.platform != 'win32':\n    pytest.skip('w', allow_module_level=True)\n", id="module-skip"),
])
def test_a_covered_module_has_no_hits(cover: str) -> None:
    assert hits(f"import sys\nimport pytest\n{cover}\n\ndef test_a():\n    import win32api\n") == []


@pytest.mark.parametrize("decorated", [
    pytest.param("@pytest.mark.windows_only\ndef test_a():\n", id="marker"),
    pytest.param("@pytest.mark.skipif(sys.platform != 'win32', reason='w')\ndef test_a():\n", id="skipif"),
    pytest.param("WIN = pytest.mark.skipif(sys.platform != 'win32', reason='w')\n\n@WIN\ndef test_a():\n", id="alias"),
    pytest.param("@pytest.mark.windows_only\nclass TestA:\n    def test_a(self):\n", id="class"),
    pytest.param("def test_a():\n    if sys.platform != 'win32':\n        pytest.skip('w')\n", id="skip-in-body"),
])
def test_a_covered_test_has_no_hits(decorated: str) -> None:
    body = "        import win32api\n" if "class" in decorated else "    import win32api\n"
    assert hits(f"import sys\nimport pytest\n\n{decorated}{body}") == []


def test_a_differently_named_marker_is_honoured() -> None:
    src = "import pytest\n\n@pytest.mark.win\ndef test_a():\n    import winreg\n"
    assert wo.scan_source(src, "t.py", marker="win").findings == []
    assert [f[1] for f in wo.scan_source(src, "t.py").findings] == ["win-module"]


# ------------------------------------------------- exemptions

def test_an_exempt_marker_on_the_line_or_on_the_test_keeps_the_hit_out() -> None:
    on_line = "def test_a():\n    import winreg  # windows-only-exempt: imported for its constants only\n"
    above_def = "# windows-only-exempt: guarded by a conftest skip\ndef test_a():\n    import winreg\n"
    scanned = wo.scan_source(on_line, "t.py")
    assert scanned.findings == [] and scanned.exempted == [(2, "win-module", "imported for its constants only")]
    assert hits(above_def) == []


def test_a_marker_with_no_reason_exempts_nothing_and_is_itself_a_hit() -> None:
    assert sorted(hits("def test_a():\n    import winreg  # windows-only-exempt\n")) == [
        "bare-exempt:2", "win-module:2"]


# ------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert wo.parse_config("") is None
    assert wo.parse_config("[windows_only_ratchet]\nenabled = false\n") is None


def test_enabled_table_defaults() -> None:
    cfg = wo.parse_config("[windows_only_ratchet]\nenabled = true\n")
    assert cfg is not None and cfg.rules == wo.RULES and cfg.marker == "windows_only"
    assert cfg.baseline == wo.DEFAULT_BASELINE and cfg.test_paths == ("tests/**",)


@pytest.mark.parametrize("body", [
    "enabled = 'yes'", "enabled = true\ntypo = 1", "enabled = true\nrules = ['nope']",
    "enabled = true\nmarker = 'not a name'", "enabled = true\nexclude = 'x'",
])
def test_a_malformed_table_is_a_config_error(body: str) -> None:
    with pytest.raises(wo.ConfigError):
        wo.parse_config(f"[windows_only_ratchet]\n{body}\n")


# ------------------------------------------------- ratchet on a git repo

def run_mode(repo: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return wo.run(repo, init=init, update=update, allow_additions=allow)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    write(tmp_path, ".fleet.toml", "[windows_only_ratchet]\nenabled = true\n")
    write(tmp_path, "tests/test_ok.py", "def test_a():\n    assert True\n")
    return tmp_path


def test_init_then_a_new_unmarked_test_rises_and_exits_one(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo, init=True) == wo.EXIT_PASS
    assert run_mode(repo) == wo.EXIT_PASS
    write(repo, "tests/unit/test_browser.py", lookup(""))
    assert run_mode(repo) == wo.EXIT_RISE
    assert "tests/unit/test_browser.py:9: [win-exe-lookup]" in capsys.readouterr().out
    write(repo, "tests/unit/test_browser.py", "import pytest\n" + lookup(
        marker="@pytest.mark.windows_only\n"))
    assert run_mode(repo) == wo.EXIT_PASS


def test_existing_debt_passes_and_a_fix_hints_the_shrink(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "tests/test_reg.py", "def test_a():\n    import winreg\n")
    assert run_mode(repo, init=True) == wo.EXIT_PASS
    write(repo, "tests/test_reg.py", "import pytest\n\n@pytest.mark.windows_only\ndef test_a():\n    import winreg\n")
    capsys.readouterr()
    assert run_mode(repo) == wo.EXIT_PASS
    assert "1 baselined hit(s) are gone" in capsys.readouterr().out
    assert run_mode(repo, update=True) == wo.EXIT_PASS
    assert '"entries": []' in (repo / wo.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_update_refuses_additions_unless_allowed(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "tests/test_reg.py", "def test_a():\n    import winreg\n")
    assert run_mode(repo, update=True) == wo.EXIT_RISE
    assert run_mode(repo, update=True, allow=True) == wo.EXIT_PASS
    assert run_mode(repo) == wo.EXIT_PASS


def test_init_never_overwrites_and_a_missing_baseline_fails(repo: Path) -> None:
    assert run_mode(repo) == wo.EXIT_RISE
    run_mode(repo, init=True)
    assert run_mode(repo, init=True) == wo.EXIT_CONFIG


def test_only_test_modules_under_test_paths_are_read(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "tests/_helper.py", "import winreg\n")
    write(repo, "src/test_like.py", "import winreg\n")
    write(repo, "tests/fixtures/test_sample.py", "import winreg\n")
    write(repo, ".fleet.toml", "[windows_only_ratchet]\nenabled = true\nexclude = ['tests/fixtures/**']\n"
                               "[vendored]\nx = { src = 'tests/v', dest = 'tests/vendored' }\n")
    write(repo, "tests/vendored/test_copy.py", "import winreg\n")
    assert run_mode(repo) == wo.EXIT_PASS


@pytest.mark.parametrize(("rel", "body", "says"), [
    ("tests/test_bad.py", b"def test_a(:\n", "does not parse"),
    ("tests/test_latin.py", b"x = '\xe9'\n", "is not UTF-8"),
])
def test_a_file_it_cannot_read_through_is_not_confirmed(
    repo: Path, rel: str, body: bytes, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_unreadable_file_not_confirmed(wo, run_mode, repo, rel, body, says, capsys)


test_git_that_cannot_list_the_tree_is_not_confirmed = git_failure_test(wo, run_mode)


def test_the_script_runs_standalone(repo: Path) -> None:
    proc = subprocess.run([sys.executable, "-P", str(REPO_ROOT / "scripts" / "windows_only_ratchet.py"), "--root",
                           str(repo), "--init"], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=60)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --------------------------------------------------------- self-adoption

def test_the_scaffold_enables_the_stage_with_a_baseline() -> None:
    cfg, _ = wo.load_config(REPO_ROOT)
    assert cfg is not None and (REPO_ROOT / cfg.baseline).is_file()


def test_gate_runs_the_stage_after_the_request_budget_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    before, stage, mypy = (text.index(s) for s in (
        'Invoke-Stage "request budget ratchet"', 'Invoke-Stage "windows only ratchet"', 'Invoke-Stage "mypy'))
    assert before < stage < mypy


def test_the_script_is_catalogued() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["windows_only_ratchet"]["src"] == "scripts/windows_only_ratchet.py"


def test_every_rule_is_documented() -> None:
    doc = (REPO_ROOT / "docs" / "windows-only-ratchet.md").read_text(encoding="utf-8")
    for rule in wo.RULES:
        assert f"`{rule}`" in doc and f"`{rule}`" in (wo.__doc__ or ""), rule
