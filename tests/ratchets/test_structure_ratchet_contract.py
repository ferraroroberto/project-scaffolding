"""Tests for the repo-shape contract: root files, folder types, homes for every shape, redundant exceptions.

Three layers:

1. **Matching** on path lists: what each preset allows and what it counts.
2. **Ratchet behaviour** on throwaway git repos: each check is recorded by `--init`, a new finding fails
   naming its doc anchor, `--update-baseline` never adds and `--allow-additions` does, and a baseline
   written before the contract existed passes, records, then ratchets.
3. **Docs**: each shape's contract table in docs/repo-layout.md, the common sets and the type table match the script.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts import structure_layout as layout
from scripts import structure_ratchet as sr
from tests._git_repo import git, write

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = "[structure_ratchet]\nenabled = true\n"
STREAMLIT = ("app/app.py", "app/views/home.py", "src/core.py", "tests/test_core.py", "docs/a.md", "README.md")


def fleet_toml(root: Path, shape: str, *, extra_roots: tuple[str, ...] = (), extra_files: tuple[str, ...] = (),
               tail: str = "") -> None:
    (root / ".fleet.toml").write_text(
        f'shape = "{shape}"\nextra_roots = {json.dumps(list(extra_roots))}\n'
        f"extra_root_files = {json.dumps(list(extra_files))}\n{CONFIG}{tail}",
        encoding="utf-8",
    )


def make_repo(root: Path, shape: str, files: tuple[str, ...], **declared: tuple[str, ...]) -> Path:
    git(root, "init", "-q")
    fleet_toml(root, shape, **declared)
    for rel in files:
        write(root, rel, "x\n")
    assert sr.run(root, init=True, update=False, allow_additions=False) == sr.EXIT_PASS
    return root


def run(root: Path, *, update: bool = False, allow: bool = False) -> int:
    return sr.run(root, init=False, update=update, allow_additions=allow)


def contract(root: Path) -> dict[str, object]:
    data = json.loads((root / sr.DEFAULT_BASELINE).read_text(encoding="utf-8"))
    recorded: dict[str, object] = data["shape_contract"]
    return recorded


# --------------------------------------------------------------- root files

@pytest.mark.parametrize(
    ("shape", "name"),
    [
        ("streamlit", "README.md"), ("streamlit", ".structure-ratchet-baseline.json"), ("node", "package-lock.json"),
        ("webapp-tray", "requirements-dev.txt"), ("webapp-tray", "tray.bat"), ("streamlit", "launch_app.sh"),
        ("pipeline-cli", "launch_scan.bat"), ("static-site", "about.html"), ("service", "run_hub.sh"),
        ("skills-governance", "install.ps1"),
    ],
)
def test_a_root_file_the_common_set_or_the_shape_lists_is_allowed(shape: str, name: str) -> None:
    assert layout.loose_root_files([name, "src/x.py"], shape) == []


@pytest.mark.parametrize(
    ("shape", "name"),
    [
        ("streamlit", "main.py"), ("streamlit", "tray.bat"), ("pipeline-cli", "main_scan.py"), ("node", "about.html"),
        ("webapp-tray", ".env.sample"), ("skills-governance", "design.md"), ("streamlit", "readme.md"),
    ],
)
def test_any_other_root_file_is_loose(shape: str, name: str) -> None:
    assert layout.loose_root_files([name, "src/x.py"], shape) == [name]


def test_redundant_entries_are_the_ones_the_preset_already_allows() -> None:
    names = layout.redundant_names("webapp-tray", ("webapp", "docs", "spike"), ("tray.bat", "README.md", "odd.py"))
    assert names == ["README.md", "docs/", "tray.bat", "webapp/"]
    assert layout.redundant_names("static-site", ("scripts", "images"), ("index.html", "wrangler.toml")) == [
        "index.html", "scripts/",
    ]


def test_extra_root_files_are_read_from_the_top_level_and_normalised() -> None:
    cfg = sr.parse_config('shape = "node"\nextra_root_files = ["b.py", "a.py/"]\n' + CONFIG)
    assert cfg is not None
    assert cfg.extra_root_files == ("a.py", "b.py")


@pytest.mark.parametrize("value", ['"a.py"', "[1]", '[""]', '["dir/a.py"]'])
def test_a_malformed_extra_root_files_is_a_config_error(tmp_path: Path, value: str) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(f'shape = "node"\nextra_root_files = {value}\n{CONFIG}', encoding="utf-8")
    assert run(tmp_path) == sr.EXIT_CONFIG


# ------------------------------------------------------------- folder types

@pytest.mark.parametrize(
    ("shape", "path"),
    [
        ("streamlit", "docs/a.md"), ("streamlit", "docs/img/shot.PNG"), ("streamlit", "docs/map.mmd"),
        ("streamlit", "tests/fixtures/sample.xlsx"), ("streamlit", "tests/fixtures/deep/blob"),
        ("streamlit", "src/pkg/README.md"), ("streamlit", "docs/.gitkeep"), ("streamlit", "app/.streamlit/config.toml"),
        ("streamlit", "app/styles/base.css"), ("streamlit", "data/raw.bin"), ("streamlit", "scripts/run.ps1"),
        ("webapp-tray", "app/webapp/static/icons/a.png"), ("webapp-tray", "app/webapp/player/index.html"),
        ("service", "launchers/start.sh"), ("static-site", "css/site.css"), ("skills-governance", "skills/a/SKILL.md"),
        ("streamlit", "config/app.json.example"),
    ],
)
def test_a_file_its_folder_type_takes_is_not_mistyped(shape: str, path: str) -> None:
    assert layout.mistyped([path], shape) == {}


@pytest.mark.parametrize(
    ("shape", "path", "folder", "suffix"),
    [
        ("streamlit", "docs/tool.py", "docs", ".py"), ("streamlit", "src/notebook.ipynb", "src", ".ipynb"),
        ("streamlit", "tests/data/a.csv", "tests/data", ".csv"), ("streamlit", "app/styles/x.png", "app/styles", ".png"),
        ("streamlit", "app/index.html", "app", ".html"), ("webapp-tray", "app/cli/logo.png", "app/cli", ".png"),
        ("service", "launchers/start.py", "launchers", ".py"), ("static-site", "js/app.css", "js", ".css"),
        ("node", "test/snap", "test", "(none)"),
    ],
)
def test_a_file_its_folder_type_does_not_take_is_counted_per_folder(
    shape: str, path: str, folder: str, suffix: str
) -> None:
    assert layout.mistyped([path], shape) == {folder: (1, (suffix,))}


def test_the_longest_typed_folder_sets_the_type() -> None:
    assert layout.folder_type("tests/fixtures/a/b.bin", "streamlit") == "any"
    assert layout.folder_type("tests/unit/a.py", "streamlit") == "code+shell"
    assert layout.folder_type("app/webapp/static/a.css", "webapp-tray") == "web"
    assert layout.folder_type("app/tray/a.py", "webapp-tray") == "code"
    assert layout.folder_type("assets/a.png", "webapp-tray") is None


def test_every_folder_type_names_a_known_type() -> None:
    for shape in layout.SHAPES.values():
        assert set(shape.all_folder_types.values()) <= set(layout.TYPES)


# --------------------------------------------------------- homes per shape

@pytest.mark.parametrize(
    ("shape", "inside", "outside"),
    [
        ("streamlit", ["app/app.py", "app/views/a.py", "app/styles/a.css", "app/.streamlit/config.toml"],
         {"app/helpers/x.py": "app/helpers", "app/views.txt": "app"}),
        ("skills-governance", ["skills/issue-start/SKILL.md", "skills/_lib/pkg/x.py"], {"skills/loose.py": "skills"}),
        ("service", ["app_web/server.py", "app_web/routers/a.py", "app_web/static/i.html", "tray/tray.py"],
         {"app_web/templates/a.html": "app_web/templates", "tray/sub/x.py": "tray/sub"}),
    ],
)
def test_each_shape_with_homes_holds_files_to_them(shape: str, inside: list[str], outside: dict[str, str]) -> None:
    assert layout.misplaced(inside, shape) == {}
    for path, folder in outside.items():
        assert layout.misplaced([path], shape) == {folder: 1}, path


def test_a_glob_segment_home_spells_out_as_a_name() -> None:
    assert layout.placement_advice("skills-governance") == "move it into one of this shape's homes (skills/<name>/)"
    assert "domain subpackage of src/" in layout.placement_advice("webapp-tray")


# ------------------------------------------------------------ ratchet: init

def test_init_records_every_contract_finding_and_the_check_passes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path, "streamlit", (*STREAMLIT, "main.py", "docs/tool.py", "app/helpers/x.py"),
              extra_roots=("config",), extra_files=("main.py",))
    assert contract(tmp_path) == {"root_files": ["main.py"], "redundant": ["config/"], "folder_types": {"docs": 1}}
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_PASS
    out = capsys.readouterr().out
    assert "1 root file(s), 1 mistyped folder(s), 1 redundant exception(s)" in out
    assert "1 misplaced folder(s)" in out


def test_a_clean_repo_records_an_empty_contract(tmp_path: Path) -> None:
    make_repo(tmp_path, "streamlit", STREAMLIT)
    assert contract(tmp_path) == {"root_files": [], "redundant": [], "folder_types": {}}


# ---------------------------------------------------------- ratchet: checks

def test_a_new_loose_root_file_fails_by_name_and_allow_additions_records_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path, "streamlit", STREAMLIT)
    write(tmp_path, "build_report.py", "x = 1\n")
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert "[root file] build_report.py is a root file outside the streamlit tree (is not declared); not baselined" in out
    assert "docs/repo-layout.md#root-files" in out
    assert run(tmp_path, update=True) == sr.EXIT_RISE
    fleet_toml(tmp_path, "streamlit", extra_files=("build_report.py",))
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_RISE
    assert "(is declared in `extra_root_files`)" in capsys.readouterr().out
    assert run(tmp_path, update=True, allow=True) == sr.EXIT_PASS
    assert contract(tmp_path)["root_files"] == ["build_report.py"]
    assert run(tmp_path) == sr.EXIT_PASS


def test_moving_a_loose_root_file_passes_and_update_drops_it(tmp_path: Path) -> None:
    make_repo(tmp_path, "streamlit", (*STREAMLIT, "main.py"))
    (tmp_path / "scripts").mkdir()
    git(tmp_path, "mv", "main.py", "scripts/main.py")
    assert run(tmp_path) == sr.EXIT_PASS
    assert run(tmp_path, update=True) == sr.EXIT_PASS
    assert contract(tmp_path)["root_files"] == []


def test_a_mistyped_file_fails_naming_its_folder_and_type_and_a_second_one_raises_the_count(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path, "streamlit", (*STREAMLIT, "docs/tool.py"))
    assert run(tmp_path) == sr.EXIT_PASS
    write(tmp_path, "docs/other.ps1", "x\n")
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert "[folder type] docs/ holds 2 file(s) of a type its folder (doc) does not take: .ps1, .py; baseline 1" in out
    assert "docs/repo-layout.md#folder-types" in out
    assert run(tmp_path, update=True, allow=True) == sr.EXIT_PASS
    assert contract(tmp_path)["folder_types"] == {"docs": 2}


def test_a_vendored_or_excluded_file_is_never_typed(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    fleet_toml(tmp_path, "streamlit", tail='exclude = ["tests/golden/**"]\n[vendored.notify]\ndest = "src/notify"\n')
    for rel in (*STREAMLIT, "src/notify/notes.txt", "tests/golden/a.csv", "src/other/notes.txt", "tests/x.png"):
        write(tmp_path, rel, "x\n")
    assert sr.run(tmp_path, init=True, update=False, allow_additions=False) == sr.EXIT_PASS
    # The same extensions outside the exclusions are typed: no extension escapes for not being measured for size.
    assert contract(tmp_path)["folder_types"] == {"src/other": 1, "tests": 1}


def test_a_published_component_source_is_never_typed_or_placed(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    fleet_toml(tmp_path, "streamlit", tail='[components]\nnav = { src = "app/webapp/static/_vendored/nav" }\n')
    for rel in (*STREAMLIT, "app/webapp/static/_vendored/nav/nav.html", "app/webapp/static/_vendored/README.md"):
        write(tmp_path, rel, "x\n")
    assert sr.run(tmp_path, init=True, update=False, allow_additions=False) == sr.EXIT_PASS
    assert contract(tmp_path)["folder_types"] == {}
    entries = json.loads((tmp_path / sr.DEFAULT_BASELINE).read_text(encoding="utf-8"))["entries"]
    assert [e["key"] for e in entries] == ["place:app/webapp/static/_vendored"], "a file no component owns stays held"


def test_a_new_redundant_entry_fails_and_deleting_it_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, "webapp-tray", ("app/a.py", "src/b.py", "tests/t.py", "docs/a.md", "webapp/t.yml"))
    fleet_toml(tmp_path, "webapp-tray", extra_roots=("webapp",))
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert "[redundant exception] webapp/ is declared in `extra_roots`, but the webapp-tray preset already allows it" in out
    assert "delete it from `extra_roots` in .fleet.toml" in out
    assert "docs/repo-layout.md#extra-roots" in out
    fleet_toml(tmp_path, "webapp-tray")
    assert run(tmp_path) == sr.EXIT_PASS


def test_a_new_home_violation_fails_in_a_shape_that_gained_homes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, "skills-governance", ("skills/a/SKILL.md", "tests/t.py"))
    write(tmp_path, "skills/loose.py", "x = 1\n")
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_RISE
    assert "[placement] skills/ holds 1 file(s) outside the homes of the skills-governance tree" in capsys.readouterr().out


# ------------------------------------------------------------ old baselines

def _drop_contract(root: Path) -> dict[str, object]:
    data: dict[str, object] = json.loads((root / sr.DEFAULT_BASELINE).read_text(encoding="utf-8"))
    del data["shape_contract"]
    (root / sr.DEFAULT_BASELINE).write_text(json.dumps(data), encoding="utf-8")
    return data


def test_a_baseline_from_before_the_contract_passes_then_records_then_ratchets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path, "streamlit", (*STREAMLIT, "main.py", "docs/tool.py", "app/helpers/x.py"),
              extra_roots=("config",))
    data = _drop_contract(tmp_path)
    data["entries"] = []  # the placement entries a streamlit baseline never had before streamlit gained homes
    (tmp_path / sr.DEFAULT_BASELINE).write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert run(tmp_path) == sr.EXIT_PASS
    assert "root files, folder types, redundant exceptions and the homes of every shape are not recorded" in (
        capsys.readouterr().out
    )
    assert run(tmp_path, update=True) == sr.EXIT_PASS
    assert contract(tmp_path) == {"root_files": ["main.py"], "redundant": ["config/"], "folder_types": {"docs": 1}}
    write(tmp_path, "setup.py", "x = 1\n")
    assert run(tmp_path) == sr.EXIT_RISE


def test_a_recorded_placement_count_may_not_grow_while_the_contract_is_unrecorded(tmp_path: Path) -> None:
    make_repo(tmp_path, "webapp-tray", ("app/a.py", "src/b.py", "tests/t.py", "docs/a.md", "app/helpers/x.py"))
    _drop_contract(tmp_path)
    assert run(tmp_path) == sr.EXIT_PASS
    write(tmp_path, "app/helpers/y.py", "x = 1\n")
    assert run(tmp_path) == sr.EXIT_RISE


@pytest.mark.parametrize(
    "value",
    [
        '"x"', '{"root_files": [], "redundant": []}', '{"root_files": [1], "redundant": [], "folder_types": {}}',
        '{"root_files": [], "redundant": [""], "folder_types": {}}',
        '{"root_files": [], "redundant": [], "folder_types": {"docs": 0}}',
    ],
)
def test_a_malformed_shape_contract_is_a_baseline_error(tmp_path: Path, value: str) -> None:
    make_repo(tmp_path, "streamlit", STREAMLIT)
    data = json.loads((tmp_path / sr.DEFAULT_BASELINE).read_text(encoding="utf-8"))
    data["shape_contract"] = json.loads(value)
    (tmp_path / sr.DEFAULT_BASELINE).write_text(json.dumps(data), encoding="utf-8")
    assert run(tmp_path) == sr.EXIT_CONFIG


def test_a_contract_kind_inside_entries_is_a_baseline_error(tmp_path: Path) -> None:
    make_repo(tmp_path, "streamlit", STREAMLIT)
    data = json.loads((tmp_path / sr.DEFAULT_BASELINE).read_text(encoding="utf-8"))
    data["entries"] = [{"key": "type:docs", "files": 1}]
    (tmp_path / sr.DEFAULT_BASELINE).write_text(json.dumps(data), encoding="utf-8")
    assert run(tmp_path) == sr.EXIT_CONFIG


# --------------------------------------------------------------------- docs

def _layout_doc() -> str:
    return (REPO_ROOT / "docs" / "repo-layout.md").read_text(encoding="utf-8")


def _contract_rows(shape: str) -> dict[str, str]:
    """The contract table of a shape's section in docs/repo-layout.md: row title -> cell."""
    section = re.split(r"^## ", _layout_doc(), flags=re.MULTILINE)
    body = next(part for part in section if part.split("\n", 1)[0].strip() == shape)
    rows = {}
    for line in body.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0] in ("Root folders", "Root files", "Folder types", "Homes"):
            rows[cells[0]] = cells[1]
    return rows


def _ticks(cell: str) -> list[str]:
    return re.findall(r"`([^`]+)`", cell)


def _pairs(cell: str) -> dict[str, str]:
    return {folder: kind for folder, kind in re.findall(r"`([^`]+)/` `([^`]+)`", cell)}


@pytest.mark.parametrize("shape_id", list(layout.SHAPES))
def test_each_shapes_contract_table_matches_its_preset(shape_id: str) -> None:
    shape, rows = layout.SHAPES[shape_id], _contract_rows(shape_id)
    required, _, allowed = rows["Root folders"].partition(";")
    assert set(_ticks(required)) == set(shape.required), shape_id
    assert set(_ticks(allowed)) == set(shape.allowed), shape_id
    assert rows["Root files"].startswith("the common set"), shape_id
    assert set(_ticks(rows["Root files"])) == set(shape.root_files), shape_id
    assert rows["Folder types"].startswith("the common set"), shape_id
    assert _pairs(rows["Folder types"]) == dict(shape.folder_types), shape_id
    homes = set(shape.homes) | {f"{parent}/<package>/" for parent in shape.surface_parents}
    if homes:
        assert set(_ticks(rows["Homes"])) == homes, shape_id
    else:
        assert rows["Homes"].startswith("none: ") and not _ticks(rows["Homes"]), "a shape without homes says why"


def test_the_common_sets_and_the_type_table_match_the_script() -> None:
    text = _layout_doc()
    files_row = text.split("| Common root files (every shape) |\n|---|\n", 1)[1].split("\n", 1)[0]
    assert _ticks(files_row) == list(layout.COMMON_ROOT_FILES)
    types_row = text.split("| Common folder types (every shape) |\n|---|\n", 1)[1].split("\n", 1)[0]
    assert _pairs(types_row) == dict(layout.COMMON_FOLDER_TYPES)
    rows = dict(re.findall(r"^\| `([a-z+]+)` \| (.+) \|$", text, re.MULTILINE))
    assert set(rows) == set(layout.TYPES)
    for name, takes in layout.TYPES.items():
        if takes is None:
            assert rows[name] == "anything"
            continue
        named = set(_ticks(rows[name]))
        listed = {t for t in named if t.startswith(".")}
        for other in named - listed:  # a type built from another, e.g. `code+shell` = `code` plus shell
            listed |= layout.TYPES[other] or set()
        assert listed == takes, name


def test_the_scaffold_declares_its_root_file_exception_and_records_its_contract() -> None:
    cfg, _ = sr.load_config(REPO_ROOT)
    assert cfg is not None and cfg.extra_root_files == ("tray.bat.template",)
    assert contract(REPO_ROOT)["root_files"] == ["tray.bat.template"]
    assert contract(REPO_ROOT)["redundant"] == []
