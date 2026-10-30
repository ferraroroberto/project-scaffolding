"""Tests for the structure ratchet's extra-roots and second-level placement checks.

Three layers:

1. **Placement matching** on path lists: what a home pattern does and does not match.
2. **Ratchet behaviour** on throwaway git repos: a deviation is baselined by `--init`, a new one
   fails by name, removal lowers the record, `--update-baseline` never adds, `--allow-additions` adds,
   and a baseline written before these checks existed loads unchanged.
3. **Self-adoption**: the sibling module is catalogued, loads from a script run and exits 3 when absent.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import structure_layout as layout
from scripts import structure_ratchet as sr
from src.no_window import NO_WINDOW
from tests._git_repo import git, write

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = "[structure_ratchet]\nenabled = true\n"
WEBAPP = ("app/webapp/routers/chat.py", "app/webapp/static/index.html", "src/chat/core.py", "tests/test_x.py", "docs/a.md")


def make_repo(root: Path, shape: str, files: tuple[str, ...], extra_roots: tuple[str, ...] = (), init: bool = True) -> Path:
    git(root, "init", "-q")
    (root / ".fleet.toml").write_text(
        f'shape = "{shape}"\nextra_roots = {json.dumps(list(extra_roots))}\n{CONFIG}', encoding="utf-8"
    )
    for rel in files:
        write(root, rel, "x\n")
    if init:
        assert sr.run(root, init=True, update=False, allow_additions=False) == sr.EXIT_PASS
    return root


def run(root: Path, *, update: bool = False, allow: bool = False) -> int:
    return sr.run(root, init=False, update=update, allow_additions=allow)


def recorded(root: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads((root / sr.DEFAULT_BASELINE).read_text(encoding="utf-8"))
    return data


# --------------------------------------------------------------- placement

@pytest.mark.parametrize(
    "path",
    [
        "app/server.py", "app/__init__.py", "app/cli/main.py", "app/tray/deep/x.py", "app/webapp/server.py",
        "app/webapp/routers/chat.py", "app/webapp/static/js/chat/index.js", "src/anything.py", "src/pkg/sub/x.py",
        "tests/anything.py", "scripts/x.py", "README.md",
    ],
)
def test_files_in_a_home_or_outside_the_home_roots_are_not_misplaced(path: str) -> None:
    assert layout.misplaced([path], "webapp-tray") == {}


@pytest.mark.parametrize(
    ("path", "folder"),
    [
        ("app/helpers/x.py", "app/helpers"),
        ("app/webapp/templates/index.html", "app/webapp/templates"),
        ("app/webapp/data.json", "app/webapp"),
        ("app/data.json", "app"),
        ("app/clix/main.py", "app/clix"),
        ("app/webapp/routers_old/x.py", "app/webapp/routers_old"),
    ],
)
def test_a_file_outside_every_home_is_counted_per_folder(path: str, folder: str) -> None:
    assert layout.misplaced([path], "webapp-tray") == {folder: 1}


def test_a_py_pattern_matches_a_direct_child_only() -> None:
    assert layout.misplaced(["app/webapp/sub/x.py"], "webapp-tray") == {"app/webapp/sub": 1}
    assert layout.misplaced(["app/webapp/x.py"], "webapp-tray") == {}


def test_shapes_without_homes_check_nothing() -> None:
    assert all(shape.home_roots == frozenset() for name, shape in layout.SHAPES.items() if name != "webapp-tray")
    assert layout.misplaced(["app/helpers/x.py"], "streamlit") == {}


def test_extra_root_names_skips_untracked_and_preset_folders() -> None:
    paths = ["spike/a.py", "webapp/b.json", "docs/c.md", "app/d.py"]
    declared = ("spike", "webapp", "docs", "gone")
    assert layout.extra_root_names(paths, "webapp-tray", declared) == ["spike"]


# ------------------------------------------------------------- extra roots

def test_init_records_the_deviation_and_the_check_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, "webapp-tray", (*WEBAPP, "spike/app.py"), ("spike",))
    assert recorded(tmp_path)["root_extras"] == ["spike"]
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_PASS
    assert "1 extra root(s)" in capsys.readouterr().out


def test_a_shape_with_no_deviation_records_an_empty_list(tmp_path: Path) -> None:
    make_repo(tmp_path, "webapp-tray", WEBAPP)
    assert recorded(tmp_path)["root_extras"] == []


def test_a_new_extra_root_fails_by_name(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, "webapp-tray", (*WEBAPP, "spike/app.py"), ("spike",))
    write(tmp_path, "labs/x.py", "x = 1\n")
    (tmp_path / ".fleet.toml").write_text(
        f'shape = "webapp-tray"\nextra_roots = ["spike", "labs"]\n{CONFIG}', encoding="utf-8"
    )
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert "[extra root] labs/ is an extra root, outside the webapp-tray tree; not baselined" in out
    assert "docs/repo-layout.md#extra-roots" in out
    assert "spike" not in out.split("[extra root]", 1)[1]


def test_a_promoted_folder_needs_no_baseline_entry(tmp_path: Path) -> None:
    make_repo(tmp_path, "webapp-tray", (*WEBAPP, "webapp/tunnel.json"), ("webapp",))
    assert recorded(tmp_path)["root_extras"] == []
    assert run(tmp_path) == sr.EXIT_PASS


def test_removing_the_folder_passes_and_update_lowers_the_record(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, "webapp-tray", (*WEBAPP, "spike/app.py"), ("spike",))
    git(tmp_path, "rm", "-q", "-f", "spike/app.py")
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_PASS
    assert "below the baseline" in capsys.readouterr().out
    assert run(tmp_path, update=True) == sr.EXIT_PASS
    assert recorded(tmp_path)["root_extras"] == []


def test_update_never_adds_an_extra_root_and_allow_additions_does(tmp_path: Path) -> None:
    make_repo(tmp_path, "webapp-tray", WEBAPP)
    write(tmp_path, "labs/x.py", "x = 1\n")
    (tmp_path / ".fleet.toml").write_text(f'shape = "webapp-tray"\nextra_roots = ["labs"]\n{CONFIG}', encoding="utf-8")
    assert run(tmp_path, update=True) == sr.EXIT_RISE
    assert recorded(tmp_path)["root_extras"] == []
    assert run(tmp_path, update=True, allow=True) == sr.EXIT_PASS
    assert recorded(tmp_path)["root_extras"] == ["labs"]
    assert run(tmp_path) == sr.EXIT_PASS


def test_an_undeclared_root_still_fails_the_layout_check(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, "webapp-tray", (*WEBAPP, "labs/x.py"), init=False)
    assert sr.run(tmp_path, init=True, update=False, allow_additions=False) == sr.EXIT_PASS
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_RISE
    assert "[root layout]" in capsys.readouterr().out


# --------------------------------------------------------- second-level

def test_a_baselined_outlier_passes_and_a_second_file_in_its_folder_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path, "webapp-tray", (*WEBAPP, "app/webapp/templates/index.html"))
    assert {"key": "place:app/webapp/templates", "files": 1} in recorded(tmp_path)["entries"]  # type: ignore[operator]
    assert run(tmp_path) == sr.EXIT_PASS
    write(tmp_path, "app/webapp/templates/other.html", "x\n")
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_RISE
    assert "holds 2 file(s)" in capsys.readouterr().out


def test_a_new_misplaced_folder_fails_and_names_the_homes_and_the_doc_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path, "webapp-tray", WEBAPP)
    write(tmp_path, "app/helpers/util.py", "x = 1\n")
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert "[placement] app/helpers/ holds 1 file(s) outside the homes of the webapp-tray tree; not baselined" in out
    assert "app/webapp/routers/" in out
    assert "app/webapp/static/" in out
    assert "src/" in out
    assert "docs/repo-layout.md#second-level-placement" in out


def test_moving_the_file_home_passes_and_update_drops_the_entry(tmp_path: Path) -> None:
    make_repo(tmp_path, "webapp-tray", (*WEBAPP, "app/helpers/util.py"))
    git(tmp_path, "mv", "app/helpers/util.py", "src/chat/util.py")
    assert run(tmp_path) == sr.EXIT_PASS
    assert run(tmp_path, update=True) == sr.EXIT_PASS
    assert not [e for e in recorded(tmp_path)["entries"] if str(e["key"]).startswith("place:")]  # type: ignore[attr-defined]


def test_update_never_adds_a_misplaced_folder_and_allow_additions_does(tmp_path: Path) -> None:
    make_repo(tmp_path, "webapp-tray", WEBAPP)
    write(tmp_path, "app/helpers/util.py", "x = 1\n")
    assert run(tmp_path, update=True) == sr.EXIT_RISE
    assert run(tmp_path, update=True, allow=True) == sr.EXIT_PASS
    assert run(tmp_path) == sr.EXIT_PASS


def test_a_shape_without_homes_ignores_the_location_of_files(tmp_path: Path) -> None:
    make_repo(tmp_path, "streamlit", ("app/helpers/x.py", "src/a.py", "tests/t.py"))
    assert run(tmp_path) == sr.EXIT_PASS


# ---------------------------------------------------------- old baselines

def test_a_baseline_from_before_the_layout_checks_passes_then_records(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path, "webapp-tray", (*WEBAPP, "spike/app.py", "app/helpers/x.py"), ("spike",))
    old = recorded(tmp_path)
    del old["root_extras"]
    old["entries"] = [e for e in old["entries"] if not str(e["key"]).startswith("place:")]  # type: ignore[attr-defined]
    (tmp_path / sr.DEFAULT_BASELINE).write_text(json.dumps(old), encoding="utf-8")
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_PASS
    assert "extra roots and placement are not recorded" in capsys.readouterr().out
    assert run(tmp_path, update=True) == sr.EXIT_PASS
    assert recorded(tmp_path)["root_extras"] == ["spike"]
    write(tmp_path, "app/more/y.py", "x = 1\n")
    assert run(tmp_path) == sr.EXIT_RISE


@pytest.mark.parametrize("value", ['"spike"', "[1]", '[""]'])
def test_a_malformed_root_extras_is_a_baseline_error(tmp_path: Path, value: str) -> None:
    make_repo(tmp_path, "webapp-tray", WEBAPP)
    text = (tmp_path / sr.DEFAULT_BASELINE).read_text(encoding="utf-8").replace('"root_extras": []', f'"root_extras": {value}')
    (tmp_path / sr.DEFAULT_BASELINE).write_text(text, encoding="utf-8")
    assert run(tmp_path) == sr.EXIT_CONFIG


# ------------------------------------------------------------ self-adoption

def test_the_sibling_is_catalogued_and_both_scripts_stay_under_the_limit() -> None:
    components = (REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8")
    assert 'structure_layout = { src = "scripts/structure_layout.py" }' in components
    for name in ("structure_ratchet.py", "structure_layout.py"):
        lines = (REPO_ROOT / "scripts" / name).read_text(encoding="utf-8").count("\n")
        assert lines <= sr.DEFAULT_MAX_FILE_LINES, name


def test_the_script_runs_standalone_beside_its_sibling_and_exits_three_without_it(tmp_path: Path) -> None:
    """The gate runs `python scripts/structure_ratchet.py`; an adopter that vendored only one file must not pass."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(REPO_ROOT / "scripts" / "structure_ratchet.py", scripts)
    command = [sys.executable, str(scripts / "structure_ratchet.py"), "--root", str(tmp_path)]
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}  # the repo's own scripts/ must not resolve

    def invoke() -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, capture_output=True, text=True, env=env, cwd=tmp_path,
                              creationflags=NO_WINDOW, check=False)

    missing = invoke()
    assert missing.returncode == sr.EXIT_NOT_CONFIRMED
    assert "structure_layout.py is missing" in missing.stdout
    shutil.copy(REPO_ROOT / "scripts" / "structure_layout.py", scripts)
    (tmp_path / ".fleet.toml").write_text("layer = 'x'\n", encoding="utf-8")
    present = invoke()
    assert present.returncode == sr.EXIT_PASS, present.stdout
    assert "not enabled" in present.stdout


def test_the_scaffold_records_its_layout_in_its_own_baseline() -> None:
    assert recorded_at_repo()["root_extras"] == []


def recorded_at_repo() -> dict[str, object]:
    data: dict[str, object] = json.loads((REPO_ROOT / sr.DEFAULT_BASELINE).read_text(encoding="utf-8"))
    return data
