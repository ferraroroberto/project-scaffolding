"""Tests for the runtime write ratchet.

Four layers, mirroring `test_conventions_ratchet.py`:

1. **Resolution** on fixture sources: which write targets land in a code
   folder, which resolve elsewhere, and which stay unknown (never clean).
2. **Ratchet behaviour** on throwaway git repos: every mode, a new write into a
   code folder failing, a new unresolved target being "not confirmed".
3. **Runtime probe**: a file the run adds under a code folder fails; a missing
   snapshot is "not confirmed".
4. **Self-adoption** -- this repo's own declaration and gate wiring.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import runtime_write_ratchet as rw
from src.no_window import NO_WINDOW
from tests._git_repo import git, write
from tests._ratchet_not_confirmed import (
    GIT_FAILURES,
    assert_unlistable_git_not_confirmed,
    assert_unreadable_file_not_confirmed,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CFG = rw.Config()


def kinds(src: str, path: str = "src/a.py", cfg: rw.Config = CFG) -> list[str]:
    """`kind:line` of every hit in one in-memory module."""
    return [f"{h.kind}:{h.line}" for h in rw.scan_source(src, path, cfg)]


# ------------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert rw.parse_config('layer = "x"\n') is None
    assert rw.parse_config("[runtime_write_ratchet]\nenabled = false\n") is None
    assert rw.parse_config("[runtime_write_ratchet]\n") is None  # opting in is explicit


def test_enabled_table_defaults_and_keys() -> None:
    assert rw.parse_config("[runtime_write_ratchet]\nenabled = true\n") == rw.Config()
    cfg = rw.parse_config(
        '[runtime_write_ratchet]\nenabled = true\nbaseline = "b.json"\ncode_folders = ["lib/"]\n'
        'exclude = ["lib/gen/**"]\nsafe_calls = ["state_dir"]\n'
    )
    assert cfg == rw.Config("b.json", ("lib",), ("lib/gen/**",), ("state_dir",))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("enabled = true\nfolders = []\n", id="typo-in-key"),
        pytest.param('enabled = "yes"\n', id="enabled-not-bool"),
        pytest.param("enabled = true\ncode_folders = []\n", id="no-code-folders"),
        pytest.param("enabled = true\ncode_folders = ['src/sub']\n", id="nested-code-folder"),
        pytest.param("enabled = true\nbaseline = ''\n", id="empty-baseline"),
        pytest.param("enabled = true\nexclude = 'x'\n", id="exclude-not-a-list"),
    ],
)
def test_malformed_table_fails_loud(body: str) -> None:
    with pytest.raises(rw.ConfigError):
        rw.parse_config("[runtime_write_ratchet]\n" + body)


# --------------------------------------------------------------- resolution

@pytest.mark.parametrize(
    "src",
    [
        pytest.param("from pathlib import Path\nLOG = Path(__file__).parent / 'run.log'\nLOG.write_text('x')\n",
                     id="beside-the-module"),
        pytest.param("import os\nD = os.path.join(os.path.dirname(__file__), 'logs')\nos.makedirs(D)\n",
                     id="os-path-join"),
        pytest.param("import logging\nlogging.FileHandler('src/app.log')\n", id="relative-literal"),
        pytest.param("from pathlib import Path\nR = Path(__file__).resolve().parents[1]\n"
                     "open(R / 'app' / 'cache.json', 'w')\n", id="parents-index"),
        pytest.param("import sqlite3\nfrom pathlib import Path\nH = Path(__file__).parent\n"
                     "sqlite3.connect(f'{H}/state.db')\n", id="fstring-head"),
        pytest.param("from pathlib import Path\nP = Path(__file__).parent\ndef f(name):\n"
                     "    (P / name).open('a')\n", id="unknown-leaf-stays-in-folder"),
        pytest.param("import shutil\nshutil.copy('x', 'scripts/out.txt')\n", id="copy-destination"),
        pytest.param("import logging.handlers\nlogging.handlers.RotatingFileHandler('app/x.log')\n",
                     id="rotating-handler"),
        pytest.param("import logging\nlogging.basicConfig(filename='hooks/run.log')\n", id="basic-config"),
        pytest.param("def f(mode):\n    open('src/x.txt', mode)\n", id="unspelled-mode-counts-as-writing"),
    ],
)
def test_a_write_into_a_code_folder_is_found(src: str) -> None:
    assert [k.split(":")[0] for k in kinds(src)] == ["code-folder"]


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("from pathlib import Path\nROOT = Path(__file__).resolve().parent.parent\n"
                     "(ROOT / 'data' / 'logs' / 'x.log').write_text('x')\n", id="data-folder"),
        pytest.param("open('data/output/x.csv', 'w')\n", id="relative-data-literal"),
        pytest.param("import tempfile\nfrom pathlib import Path\nT = Path(tempfile.mkdtemp())\n"
                     "(T / 'x').write_text('x')\n", id="temp-dir"),
        pytest.param("from src.runtime_data import runtime_db_path\nimport sqlite3\n"
                     "sqlite3.connect(runtime_db_path('app', 'x.sqlite3'))\n", id="runtime-root"),
        pytest.param("from pathlib import Path\n(Path.home() / '.cache').mkdir()\n", id="home"),
        pytest.param("open('C:/elsewhere/x.txt', 'w')\nopen('/var/x', 'a')\n", id="absolute"),
        pytest.param("import sqlite3\nsqlite3.connect(':memory:')\n", id="memory-db"),
        pytest.param("from pathlib import Path\nPath(__file__).read_text()\nopen(__file__)\n", id="reads"),
        pytest.param("import ftplib\nftplib.FTP().mkdir('dir')\n", id="non-path-mkdir"),
        pytest.param("from pathlib import Path\nP = Path(__file__).parent\nP.open('rb')\n", id="read-mode"),
    ],
)
def test_a_write_off_the_code_folders_is_clean(src: str) -> None:
    assert kinds(src) == []


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("def save(path):\n    open(path, 'w')\n", id="parameter"),
        pytest.param("import os\nopen(os.environ['OUT'], 'w')\n", id="env-var"),
        pytest.param("class S:\n    def save(self):\n        self.path.write_text('x')\n", id="attribute"),
        pytest.param("P = 'src/a.log'\nP = 'data/a.log'\nopen(P, 'w')\n", id="rebound-name"),
        pytest.param("def f(name):\n    open(name + '.log', 'a')\n", id="concatenation"),
    ],
)
def test_an_unresolvable_target_is_unknown_never_clean(src: str) -> None:
    found = kinds(src)
    assert found and all(k.startswith("unresolved") for k in found)


def test_a_parameter_shadows_a_module_name_of_the_same_spelling() -> None:
    src = "LOG = 'src/x.log'\ndef f(LOG):\n    open(LOG, 'w')\n"
    assert kinds(src) == ["unresolved:3"]


def test_safe_calls_mark_an_adopters_own_runtime_helper() -> None:
    src = "from lib.paths import state_dir\nopen(state_dir() / 'x', 'w')\n"
    assert kinds(src) == ["unresolved:2"]
    assert kinds(src, cfg=rw.Config(safe_calls=("state_dir",))) == []


def test_exempt_marker_needs_a_reason() -> None:
    body = "open('src/out.txt', 'w')\n"
    assert kinds("# runtime-write-exempt: generated source, committed\n" + body) == []
    assert kinds("# runtime-write-exempt:\n" + body) == ["code-folder:2"]


def test_test_modules_and_non_python_are_out_of_scope() -> None:
    assert not rw.in_scope("tests/test_x.py", CFG, ())
    assert not rw.in_scope("src/conftest.py", CFG, ())
    assert not rw.in_scope("src/a.js", CFG, ())
    assert not rw.in_scope("src/vend/a.py", CFG, ("src/vend",))
    assert rw.in_scope("src/a.py", CFG, ())


def test_a_module_that_does_not_parse_raises() -> None:
    with pytest.raises(rw.NotConfirmed, match="does not parse"):
        rw.scan_source("def broken(:\n", "src/bad.py", CFG)


# ------------------------------------------------------- ratchet on a git repo

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the stage on and one baselined write beside the code."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text("[runtime_write_ratchet]\nenabled = true\n", encoding="utf-8")
    write(tmp_path, "src/a.py", "open('src/old.log', 'a')\n")
    return tmp_path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return rw.run(root, init=init, update=update, allow_additions=allow)


def baseline_text(root: Path) -> str:
    return (root / rw.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_init_records_real_counts_and_never_overwrites(repo: Path) -> None:
    assert run_mode(repo, init=True) == rw.EXIT_PASS
    assert '{"key": "src/a.py", "counts": {"code-folder": 1}}' in baseline_text(repo)
    assert run_mode(repo, init=True) == rw.EXIT_CONFIG


def test_unchanged_tree_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    assert run_mode(repo) == rw.EXIT_PASS
    assert "PASS (1 baselined write target(s) in code folders, none new" in capsys.readouterr().out


def test_a_new_write_into_a_code_folder_fails_the_gate(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "app/b.py", "from pathlib import Path\n(Path(__file__).parent / 'run.log').write_text('x')\n")
    capsys.readouterr()
    assert run_mode(repo) == rw.EXIT_RISE
    out = capsys.readouterr().out
    assert "app/b.py:2: [code-folder]" in out and "(app/run.log)" in out


def test_a_new_unresolved_target_is_not_confirmed_not_a_pass(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "src/c.py", "def save(path):\n    open(path, 'w')\n")
    capsys.readouterr()
    assert run_mode(repo) == rw.EXIT_NOT_CONFIRMED
    assert "unknown, not clean" in capsys.readouterr().out


def test_baselined_unresolved_targets_are_named_on_a_pass(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "src/c.py", "def save(path):\n    open(path, 'w')\n")
    run_mode(repo, init=True)
    capsys.readouterr()
    assert run_mode(repo) == rw.EXIT_PASS
    assert "1 baselined write target(s) stay unresolved: unknown, not clean" in capsys.readouterr().out


def test_update_shrinks_but_never_grows_without_allow(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/a.py", "open('data/new.log', 'a')\n")
    assert run_mode(repo, update=True) == rw.EXIT_PASS
    assert '"entries": []' in baseline_text(repo)
    write(repo, "src/a.py", "open('src/old.log', 'a')\n")
    assert run_mode(repo, update=True) == rw.EXIT_RISE
    assert run_mode(repo, update=True, allow=True) == rw.EXIT_PASS
    assert '"code-folder": 1' in baseline_text(repo)


def test_missing_baseline_fails_and_disabled_stage_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".fleet.toml").write_text("[runtime_write_ratchet]\nenabled = true\n", encoding="utf-8")
    assert run_mode(tmp_path) == rw.EXIT_RISE
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path) == rw.EXIT_PASS
    assert "not enabled" in capsys.readouterr().out
    assert run_mode(tmp_path, init=True) == rw.EXIT_CONFIG


@pytest.mark.parametrize(
    ("body", "says"),
    [
        pytest.param(b"def broken(:\n", "does not parse (line 1)", id="syntax"),
        pytest.param(b"x = 'caf\xe9'\n", "does not parse", id="not-utf8"),
    ],
)
def test_a_module_that_does_not_parse_is_not_confirmed_in_every_mode(
    repo: Path, body: bytes, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_unreadable_file_not_confirmed(rw, run_mode, repo, "src/bad.py", body, says, capsys)


@pytest.mark.parametrize(("var", "value", "says"), GIT_FAILURES)
def test_git_that_cannot_list_the_tree_is_not_confirmed(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], var: str, value: str, says: str
) -> None:
    assert_unlistable_git_not_confirmed(rw, run_mode, repo, monkeypatch, capsys, var, value, says)


# ------------------------------------------------------------ runtime probe

def test_probe_fails_on_a_file_the_run_added_under_a_code_folder(
    repo: Path, tmp_path_factory: pytest.TempPathFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    write(repo, "src/before.log", "x", track=False)
    snap = tmp_path_factory.mktemp("snap") / "s.json"
    assert rw.snapshot(repo, snap) == rw.EXIT_PASS
    write(repo, "src/__pycache__/a.cpython-311.pyc", "x", track=False)  # interpreter noise
    write(repo, "data/run.log", "x", track=False)  # the right place
    assert rw.probe(repo, snap) == rw.EXIT_PASS
    assert not snap.exists(), "a passing probe consumes its snapshot"

    assert rw.snapshot(repo, snap) == rw.EXIT_PASS
    write(repo, "app/run.log", "x", track=False)  # ignored, still a runtime file in a code folder
    write(repo, "scripts/out.json", "x", track=False)
    capsys.readouterr()
    assert rw.probe(repo, snap) == rw.EXIT_RISE
    out = capsys.readouterr().out
    assert "app/run.log" in out and "scripts/out.json" in out and "src/before.log" not in out


def test_probe_without_a_readable_snapshot_is_not_confirmed(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert rw.probe(repo, repo / "missing.json") == rw.EXIT_NOT_CONFIRMED
    assert "NOT CONFIRMED" in capsys.readouterr().out


def test_probe_is_a_no_op_when_the_stage_is_off(tmp_path: Path) -> None:
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert rw.snapshot(tmp_path, tmp_path / "s.json") == rw.EXIT_PASS
    assert rw.probe(tmp_path, tmp_path / "s.json") == rw.EXIT_PASS


def test_main_rejects_allow_additions_without_update(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        rw.main(["--allow-additions"])
    assert exc.value.code == 2
    assert "--allow-additions" in capsys.readouterr().err


# ------------------------------------------------------------ self-adoption

def test_scaffold_adopts_the_stage_and_commits_a_parseable_baseline() -> None:
    cfg, _ = rw.load_config(REPO_ROOT)
    assert cfg is not None, "the scaffold adopts its own stage first"
    assert (REPO_ROOT / cfg.baseline).is_file()
    rw.read_baseline(REPO_ROOT / cfg.baseline)


def test_gate_runs_the_stage_and_brackets_the_tests_with_the_probe() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    conventions, stage, mypy, snap, unit, e2e, probe = (
        text.index(s) for s in ('Invoke-Stage "conventions ratchet"', 'Invoke-Stage "runtime write ratchet"',
                                'Invoke-Stage "mypy', "--snapshot $runtimeSnapshot",
                                'Invoke-Stage "pytest (unit', "pytest e2e (", "--probe $runtimeSnapshot")
    )
    assert conventions < stage < mypy
    assert snap < unit < e2e < probe


def test_both_files_are_catalogued_so_they_are_mypy_gated_and_drift_checked() -> None:
    from scripts.vendored_catalog import load_catalog

    catalog = load_catalog(REPO_ROOT)
    assert catalog["runtime_write_ratchet"] == {"src": "scripts/runtime_write_ratchet.py"}
    assert catalog["runtime_write_resolve"] == {"src": "scripts/runtime_write_resolve.py"}


def test_the_script_runs_standalone_beside_its_sibling_and_exits_three_without_it(tmp_path: Path) -> None:
    """The gate runs `python scripts/runtime_write_ratchet.py`; an adopter that vendored one file must not pass."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(REPO_ROOT / "scripts" / "runtime_write_ratchet.py", scripts)
    (tmp_path / ".fleet.toml").write_text("layer = 'x'\n", encoding="utf-8")
    command = [sys.executable, "-P", str(scripts / "runtime_write_ratchet.py"), "--root", str(tmp_path)]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}  # the repo's own scripts/ must not resolve
    missing = subprocess.run(command, capture_output=True, text=True, env=env, cwd=tmp_path,
                             creationflags=NO_WINDOW, check=False)
    assert missing.returncode == rw.EXIT_NOT_CONFIRMED, missing.stdout + missing.stderr
    assert "runtime_write_resolve.py is missing" in missing.stdout
    shutil.copy(REPO_ROOT / "scripts" / "runtime_write_resolve.py", scripts)
    present = subprocess.run(command, capture_output=True, text=True, env=env, cwd=tmp_path,
                             creationflags=NO_WINDOW, check=False)
    assert present.returncode == rw.EXIT_PASS, present.stdout + present.stderr
    assert "not enabled" in present.stdout
