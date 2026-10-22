"""Tests for the baseline-and-ratchet static-analysis stage (project-scaffolding#410).

Three layers, mirroring `test_classify_e2e.py` / `test_vendored_catalog.py`:

1. **Pure logic** against captured jscpd / ruff JSON shapes: config parsing, key
   stability when lines shift, the new-versus-baselined diff, every CLI mode
   (the detectors are stubbed here, so these run in milliseconds).
2. **The acceptance criteria, end to end** on throwaway trees with the *real*
   jscpd (pinned, via `npx`) and ruff: a newly introduced duplicate or unused
   import fails and is named, the same findings in the baseline pass, removing
   a baselined hit passes and `--update-baseline` shrinks the file. A missing
   prerequisite is a hard failure, never `pytest.skip` -- a skipped ratchet is
   how a regression ships looking green.
3. **Self-adoption** -- this repo's own declaration and gate wiring.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import static_ratchet as sr
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parent.parent
ROOT = REPO_ROOT  # parse_* only use it to relativise absolute paths


# ------------------------------------------------------------------ helpers

def dup(first: str, second: str, fragment: str, start: int = 1) -> dict[str, object]:
    return {
        "firstFile": {"name": first, "start": start},
        "secondFile": {"name": second, "start": 1},
        "fragment": fragment,
        "format": "python",
    }


def ruff_item(code: str, filename: str, message: str, row: int = 1) -> dict[str, object]:
    return {"code": code, "filename": filename, "message": message, "location": {"row": row, "column": 1}}


def finding(key: str, kind: str = "unused", files: tuple[str, ...] = ("a.py",)) -> sr.Finding:
    return sr.Finding(key, kind, files, "detail")


# ------------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert sr.parse_config('layer = "x"\n') is None
    assert sr.parse_config("[static_ratchet]\nenabled = false\n") is None
    assert sr.parse_config("[static_ratchet]\n") is None  # opting in is explicit


def test_enabled_table_gets_the_documented_defaults() -> None:
    cfg = sr.parse_config("[static_ratchet]\nenabled = true\n")
    assert cfg == sr.Config(".static-ratchet-baseline.json", 10, 100, ())


def test_enabled_table_honours_every_key() -> None:
    cfg = sr.parse_config(
        '[static_ratchet]\nenabled = true\nbaseline = "b.json"\nmin_lines = 7\n'
        'min_tokens = 55\nexclude = ["**/_vendored/**"]\n'
    )
    assert cfg == sr.Config("b.json", 7, 55, ("**/_vendored/**",))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("enabled = true\nmin_line = 7\n", id="typo-in-key"),
        pytest.param('enabled = "yes"\n', id="enabled-not-bool"),
        pytest.param("enabled = true\nmin_lines = 0\n", id="zero-lines"),
        pytest.param("enabled = true\nmin_tokens = true\n", id="bool-as-int"),
        pytest.param('enabled = true\nexclude = "x"\n', id="exclude-not-list"),
        pytest.param('enabled = true\nbaseline = ""\n', id="empty-baseline"),
    ],
)
def test_malformed_table_fails_loud(body: str) -> None:
    with pytest.raises(sr.ConfigError):
        sr.parse_config("[static_ratchet]\n" + body)


# ---------------------------------------------------------------- globs

@pytest.mark.parametrize(
    ("glob", "path", "expected"),
    [
        ("**/node_modules/**", "node_modules/x.js", True),
        ("**/node_modules/**", "web/node_modules/a/b.js", True),
        ("**/node_modules/**", "web/modules/b.js", False),
        ("**/*.min.js", "a.min.js", True),
        ("**/*.min.js", "static/a.min.js", True),
        ("**/*.min.js", "static/a.js", False),
        ("app/*.py", "app/x.py", True),
        ("app/*.py", "app/sub/x.py", False),
    ],
)
def test_glob_matching(glob: str, path: str, expected: bool) -> None:
    assert sr.is_excluded(path, (glob,)) is expected


# ----------------------------------------------------------------- jscpd keys

FRAGMENT = "def f():\n    x = compute(1)\n    return x"


def test_dup_key_survives_a_line_shift() -> None:
    before = sr.parse_jscpd({"duplicates": [dup("a.py", "b.py", FRAGMENT, start=3)]}, ROOT, ())
    after = sr.parse_jscpd({"duplicates": [dup("a.py", "b.py", FRAGMENT, start=250)]}, ROOT, ())
    assert [f.key for f in before] == [f.key for f in after]
    assert before[0].files == ("a.py", "b.py")


def test_dup_key_ignores_whitespace_but_not_content() -> None:
    base = sr.parse_jscpd({"duplicates": [dup("a.py", "b.py", FRAGMENT)]}, ROOT, ())
    reflowed = sr.parse_jscpd({"duplicates": [dup("a.py", "b.py", FRAGMENT.replace("\n    ", "\n\t\t"))]}, ROOT, ())
    edited = sr.parse_jscpd({"duplicates": [dup("a.py", "b.py", FRAGMENT.replace("compute(1)", "compute(2)"))]}, ROOT, ())
    assert base[0].key == reflowed[0].key
    assert base[0].key != edited[0].key  # strict: editing a clone is a new hit


def test_dup_key_is_the_sorted_pair() -> None:
    forward = sr.parse_jscpd({"duplicates": [dup("a.py", "b.py", FRAGMENT)]}, ROOT, ())
    backward = sr.parse_jscpd({"duplicates": [dup("b.py", "a.py", FRAGMENT)]}, ROOT, ())
    assert forward[0].key.endswith(":a.py|b.py")
    assert backward[0].key.endswith(":a.py|b.py")


def test_repeated_identical_dup_gets_an_ordinal() -> None:
    report = {"duplicates": [dup("a.py", "b.py", FRAGMENT, start=1), dup("a.py", "b.py", FRAGMENT, start=40)]}
    keys = [f.key for f in sr.parse_jscpd(report, ROOT, ())]
    assert len(keys) == 2
    assert keys[1] == keys[0] + "#2"


def test_dup_touching_an_excluded_file_is_dropped() -> None:
    report = {"duplicates": [dup("app/_vendored/x.js", "b.js", FRAGMENT)]}
    assert sr.parse_jscpd(report, ROOT, ("**/_vendored/**",)) == []


@pytest.mark.parametrize("report", [None, [], {}, {"duplicates": "x"}, {"duplicates": [{"firstFile": {}}]}])
def test_malformed_jscpd_report_is_not_confirmed(report: object) -> None:
    with pytest.raises(sr.NotConfirmed):
        sr.parse_jscpd(report, ROOT, ())


# ----------------------------------------------------------------- ruff keys

def test_unused_import_key_names_the_symbol() -> None:
    items = [ruff_item("F401", str(ROOT / "pkg" / "m.py"), "`os` imported but unused", row=3)]
    (f,) = sr.parse_ruff(items, ROOT, ())
    assert f.key == "unused:F401:pkg/m.py:os"
    assert f.files == ("pkg/m.py",)


def test_unused_key_survives_a_line_shift() -> None:
    a = sr.parse_ruff([ruff_item("F841", "m.py", "Local variable `x` is assigned to but never used", row=4)], ROOT, ())
    b = sr.parse_ruff([ruff_item("F841", "m.py", "Local variable `x` is assigned to but never used", row=90)], ROOT, ())
    assert a[0].key == b[0].key


def test_repeated_unused_symbol_in_one_file_gets_ordinals() -> None:
    msg = "Local variable `x` is assigned to but never used"
    keys = [f.key for f in sr.parse_ruff([ruff_item("F841", "m.py", msg, row=r) for r in (9, 2)], ROOT, ())]
    assert keys == ["unused:F841:m.py:x", "unused:F841:m.py:x#2"]


def test_message_without_a_backticked_name_falls_back_to_the_source_line(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("import os\n    import sys  \n", encoding="utf-8")
    (f,) = sr.parse_ruff([ruff_item("F401", "m.py", "imported but unused", row=2)], tmp_path, ())
    assert f.key == "unused:F401:m.py:import sys"


def test_unused_in_an_excluded_path_is_dropped() -> None:
    items = [ruff_item("F401", "web/node_modules/m.py", "`os` imported but unused")]
    assert sr.parse_ruff(items, ROOT, sr.BUILTIN_EXCLUDES) == []


@pytest.mark.parametrize("items", [None, {}, [{"code": "F401"}]])
def test_malformed_ruff_output_is_not_confirmed(items: object) -> None:
    with pytest.raises(sr.NotConfirmed):
        sr.parse_ruff(items, ROOT, ())


# ------------------------------------------------------- baseline file + diff

def test_baseline_round_trips_sorted_one_entry_per_line(tmp_path: Path) -> None:
    findings = {f.key: f for f in (finding("unused:F401:z.py:b", files=("z.py",)), finding("dup:abc:a.py|b.py", "dup", ("a.py", "b.py")))}
    text = sr.render_baseline(findings, {"jscpd": "x", "ruff": "y"})
    path = tmp_path / "b.json"
    path.write_text(text, encoding="utf-8")
    assert sr.read_baseline(path) == {"dup:abc:a.py|b.py": ("a.py", "b.py"), "unused:F401:z.py:b": ("z.py",)}
    entry_lines = [ln for ln in text.splitlines() if '"key"' in ln]
    assert [json.loads(ln.rstrip(","))["key"] for ln in entry_lines] == ["dup:abc:a.py|b.py", "unused:F401:z.py:b"]


def test_empty_baseline_renders_as_valid_json(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text(sr.render_baseline({}, {"jscpd": "x", "ruff": "y"}), encoding="utf-8")
    assert sr.read_baseline(path) == {}


@pytest.mark.parametrize(
    "text",
    ["not json", "[]", '{"version": 2, "entries": []}', '{"version": 1}', '{"version": 1, "entries": [{"key": 1}]}'],
)
def test_bad_baseline_file_raises_config_error(tmp_path: Path, text: str) -> None:
    path = tmp_path / "b.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(sr.ConfigError):
        sr.read_baseline(path)


def test_diff_splits_new_from_gone() -> None:
    current = {k: finding(k) for k in ("a", "b")}
    new, gone = sr.diff(current, {"b": ("a.py",), "c": ("a.py",)})
    assert [f.key for f in new] == ["a"]
    assert gone == ["c"]


# --------------------------------------------------------- CLI modes (stubbed)

@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A root with the stage enabled; detectors are stubbed via `current`."""
    (tmp_path / ".fleet.toml").write_text("[static_ratchet]\nenabled = true\n", encoding="utf-8")
    monkeypatch.setattr(sr, "tool_versions", lambda: {"jscpd": sr.JSCPD_VERSION, "ruff": "test"})
    return tmp_path


def stub_findings(monkeypatch: pytest.MonkeyPatch, *keys: str) -> None:
    monkeypatch.setattr(sr, "collect", lambda root, cfg: {k: finding(k) for k in keys})


def write_baseline(root: Path, *keys: str) -> Path:
    path = root / sr.DEFAULT_BASELINE
    path.write_text(sr.render_baseline({k: finding(k) for k in keys}, {"jscpd": "x", "ruff": "y"}), encoding="utf-8")
    return path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return sr.run(root, init=init, update=update, allow_additions=allow)


def test_disabled_stage_exits_zero_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path) == sr.EXIT_PASS
    assert "not enabled" in capsys.readouterr().out


def test_init_and_update_on_a_disabled_stage_are_errors(tmp_path: Path) -> None:
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path, init=True) == sr.EXIT_CONFIG
    assert run_mode(tmp_path, update=True) == sr.EXIT_CONFIG


def test_bad_config_exits_two(tmp_path: Path) -> None:
    (tmp_path / ".fleet.toml").write_text("[static_ratchet]\nenabled = true\nbogus = 1\n", encoding="utf-8")
    assert run_mode(tmp_path) == sr.EXIT_CONFIG


def test_missing_baseline_fails_instead_of_passing(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    stub_findings(monkeypatch)  # a clean tree must still fail without a baseline
    assert run_mode(repo) == sr.EXIT_NEW
    assert "--init" in capsys.readouterr().out


def test_new_finding_fails_and_is_named(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    write_baseline(repo, "k1")
    stub_findings(monkeypatch, "k1", "k2")
    assert run_mode(repo) == sr.EXIT_NEW
    assert "1 NEW" in capsys.readouterr().out


def test_baselined_findings_pass(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_baseline(repo, "k1", "k2")
    stub_findings(monkeypatch, "k1", "k2")
    assert run_mode(repo) == sr.EXIT_PASS


def test_gone_baselined_finding_passes_with_a_shrink_hint(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    write_baseline(repo, "k1", "k2")
    stub_findings(monkeypatch, "k1")
    assert run_mode(repo) == sr.EXIT_PASS
    assert "--update-baseline" in capsys.readouterr().out


def test_update_baseline_shrinks(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_baseline(repo, "k1", "k2")
    stub_findings(monkeypatch, "k1")
    assert run_mode(repo, update=True) == sr.EXIT_PASS
    assert list(sr.read_baseline(path)) == ["k1"]


def test_update_baseline_refuses_additions_and_writes_nothing(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_baseline(repo, "k1")
    before = path.read_text(encoding="utf-8")
    stub_findings(monkeypatch, "k1", "k2")
    assert run_mode(repo, update=True) == sr.EXIT_NEW
    assert path.read_text(encoding="utf-8") == before


def test_allow_additions_adds(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_baseline(repo, "k1")
    stub_findings(monkeypatch, "k1", "k2")
    assert run_mode(repo, update=True, allow=True) == sr.EXIT_PASS
    assert sorted(sr.read_baseline(path)) == ["k1", "k2"]


def test_init_writes_a_baseline_and_never_overwrites(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_findings(monkeypatch, "k1")
    assert run_mode(repo, init=True) == sr.EXIT_PASS
    path = repo / sr.DEFAULT_BASELINE
    assert list(sr.read_baseline(path)) == ["k1"]
    stub_findings(monkeypatch, "k1", "k2")
    assert run_mode(repo, init=True) == sr.EXIT_CONFIG
    assert list(sr.read_baseline(path)) == ["k1"]


def test_unreadable_baseline_exits_two(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (repo / sr.DEFAULT_BASELINE).write_text("{oops", encoding="utf-8")
    stub_findings(monkeypatch)
    assert run_mode(repo) == sr.EXIT_CONFIG


@pytest.mark.parametrize("mode", [{}, {"update": True}, {"update": True, "allow": True}])
def test_detector_that_cannot_run_is_its_own_state_in_every_mode(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], mode: dict[str, bool],
) -> None:
    path = write_baseline(repo, "k1")
    before = path.read_text(encoding="utf-8")

    def boom(root: Path, cfg: sr.Config) -> dict[str, sr.Finding]:
        raise sr.NotConfirmed("npx not found")

    monkeypatch.setattr(sr, "collect", boom)
    assert run_mode(repo, **mode) == sr.EXIT_NOT_CONFIRMED
    assert "NOT CONFIRMED" in capsys.readouterr().out
    assert path.read_text(encoding="utf-8") == before  # never rewritten on an unknown


def test_main_rejects_allow_additions_without_update(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        sr.main(["--allow-additions"])
    assert exc.value.code == 2


def test_no_npx_is_not_confirmed(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(sr.NotConfirmed):
        sr.run_jscpd(repo, sr.Config(sr.DEFAULT_BASELINE, 10, 100, ()))


# ------------------------------------------- acceptance criteria, real tools

def py_block(tag: str, size: int = 14) -> str:
    """A clone-sized, lint-clean Python block (a call per line, nothing unused)."""
    return "".join(f"    out.append(compute_{tag}({i}) + other_value({i}, 'label_{i}'))\n" for i in range(size))


def js_block(size: int = 14) -> str:
    return "".join(f"  out.push(items.map((x) => x * {i}).filter(Boolean));\n" for i in range(size))


def py_module(name: str, block: str, extra: str = "") -> str:
    return f"{extra}\n\ndef {name}(out: list[int]) -> list[int]:\n{block}    return out\n"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / ".fleet.toml").write_text("[static_ratchet]\nenabled = true\n", encoding="utf-8")
    (tmp_path / "one.py").write_text(py_module("one", py_block("alpha")), encoding="utf-8")
    (tmp_path / "two.py").write_text(py_module("two", py_block("beta")), encoding="utf-8")
    (tmp_path / "one.js").write_text("function one(out, items) {\n" + js_block() + "}\n", encoding="utf-8")
    return tmp_path


def ratchet(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """The real CLI as the gate runs it: a subprocess, real jscpd + ruff."""
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "static_ratchet.py"), "--root", str(root), *args],
        capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, check=False, creationflags=NO_WINDOW,
        env={**os.environ, "PYTHONUTF8": "1"},
    )


def test_real_tool_prerequisites_are_present() -> None:
    """Hard failure, not a skip: without these the ratchet proves nothing."""
    assert shutil.which("npx"), "Node/npx is required by the duplication check (see docs/static-ratchet.md)"
    out = subprocess.run([sys.executable, "-m", "ruff", "--version"], capture_output=True, text=True, check=False, creationflags=NO_WINDOW)
    assert out.returncode == 0, "ruff must be installed in the venv"


def test_clean_tree_inits_an_empty_baseline_and_passes(tree: Path) -> None:
    assert ratchet(tree, "--init").returncode == 0
    assert sr.read_baseline(tree / sr.DEFAULT_BASELINE) == {}
    result = ratchet(tree)
    assert result.returncode == 0, result.stdout
    assert "PASS" in result.stdout


def test_a_new_python_duplicate_fails_and_names_both_files(tree: Path) -> None:
    assert ratchet(tree, "--init").returncode == 0
    (tree / "three.py").write_text(py_module("three", py_block("alpha")), encoding="utf-8")  # clones one.py
    result = ratchet(tree)
    assert result.returncode == sr.EXIT_NEW, result.stdout
    assert "duplicate block" in result.stdout
    assert "one.py" in result.stdout
    assert "three.py" in result.stdout


def test_a_new_javascript_duplicate_fails_and_names_both_files(tree: Path) -> None:
    assert ratchet(tree, "--init").returncode == 0
    (tree / "two.js").write_text("function two(out, items) {\n" + js_block() + "  return out;\n}\n", encoding="utf-8")
    result = ratchet(tree)
    assert result.returncode == sr.EXIT_NEW, result.stdout
    assert "one.js" in result.stdout
    assert "two.js" in result.stdout


def test_a_new_unused_import_fails_by_name(tree: Path) -> None:
    assert ratchet(tree, "--init").returncode == 0
    (tree / "two.py").write_text(py_module("two", py_block("beta"), extra="import json"), encoding="utf-8")
    result = ratchet(tree)
    assert result.returncode == sr.EXIT_NEW, result.stdout
    assert "F401" in result.stdout
    assert "json" in result.stdout


def test_a_new_unused_variable_fails_by_name(tree: Path) -> None:
    assert ratchet(tree, "--init").returncode == 0
    (tree / "four.py").write_text("def f() -> None:\n    leftover = 1\n", encoding="utf-8")
    result = ratchet(tree)
    assert result.returncode == sr.EXIT_NEW, result.stdout
    assert "F841" in result.stdout
    assert "leftover" in result.stdout


def test_baselined_findings_pass_and_removing_one_shrinks_the_baseline(tree: Path) -> None:
    # Debt that exists when the stage is adopted: a clone pair and an unused import.
    (tree / "three.py").write_text(py_module("three", py_block("alpha"), extra="import json"), encoding="utf-8")
    assert ratchet(tree, "--init").returncode == 0
    baseline = sr.read_baseline(tree / sr.DEFAULT_BASELINE)
    assert any(k.startswith("dup:") for k in baseline)
    assert "unused:F401:three.py:json" in baseline

    passed = ratchet(tree)
    assert passed.returncode == 0, passed.stdout  # baselined debt does not fail the gate

    (tree / "three.py").write_text(py_module("three", py_block("gamma")), encoding="utf-8")  # fix both
    shrunk = ratchet(tree)
    assert shrunk.returncode == 0, shrunk.stdout  # a vanished hit is a hint, not a failure
    assert "--update-baseline" in shrunk.stdout

    assert ratchet(tree, "--update-baseline").returncode == 0
    assert sr.read_baseline(tree / sr.DEFAULT_BASELINE) == {}


def test_editing_a_baselined_clone_reads_as_a_new_hit(tree: Path) -> None:
    (tree / "three.py").write_text(py_module("three", py_block("alpha")), encoding="utf-8")
    assert ratchet(tree, "--init").returncode == 0
    lines = (tree / "three.py").read_text(encoding="utf-8").splitlines(keepends=True)
    lines[3] = "    out.append(compute_alpha(1) + other_value(1, 'edited'))\n"  # still a clone of one.py: 13 of 14 lines
    (tree / "three.py").write_text("".join(lines), encoding="utf-8")
    result = ratchet(tree)
    assert result.returncode == sr.EXIT_NEW, result.stdout  # the strict content key


def test_inserting_code_above_a_baselined_clone_does_not_reflag_it(tree: Path) -> None:
    (tree / "three.py").write_text(py_module("three", py_block("alpha")), encoding="utf-8")
    assert ratchet(tree, "--init").returncode == 0
    original = (tree / "three.py").read_text(encoding="utf-8")
    (tree / "three.py").write_text("# a\n# b\n# c\nVALUE = 1\n\n" + original, encoding="utf-8")
    result = ratchet(tree)
    assert result.returncode == 0, result.stdout


def test_update_baseline_will_not_add_but_allow_additions_does(tree: Path) -> None:
    assert ratchet(tree, "--init").returncode == 0
    (tree / "four.py").write_text("def f() -> None:\n    leftover = 1\n", encoding="utf-8")
    refused = ratchet(tree, "--update-baseline")
    assert refused.returncode == sr.EXIT_NEW
    assert sr.read_baseline(tree / sr.DEFAULT_BASELINE) == {}
    assert ratchet(tree, "--update-baseline", "--allow-additions").returncode == 0
    assert "unused:F841:four.py:leftover" in sr.read_baseline(tree / sr.DEFAULT_BASELINE)


def test_exclude_glob_silences_a_path(tree: Path) -> None:
    (tree / ".fleet.toml").write_text('[static_ratchet]\nenabled = true\nexclude = ["gen/**"]\n', encoding="utf-8")
    assert ratchet(tree, "--init").returncode == 0
    (tree / "gen").mkdir()
    (tree / "gen" / "x.py").write_text("import json\n", encoding="utf-8")
    assert ratchet(tree).returncode == 0


def test_a_vendored_duplicate_is_not_reported_but_a_native_one_still_is(tree: Path) -> None:
    (tree / ".fleet.toml").write_text(
        '[static_ratchet]\nenabled = true\n\n[vendored.copy]\nsrc = "scripts/x.py"\ndest = "three.py"\n',
        encoding="utf-8",
    )
    assert ratchet(tree, "--init").returncode == 0
    (tree / "three.py").write_text(py_module("three", py_block("alpha")), encoding="utf-8")  # clones one.py
    result = ratchet(tree)
    assert result.returncode == 0, result.stdout
    (tree / "four.py").write_text(py_module("four", py_block("alpha")), encoding="utf-8")  # same clone, not vendored
    result = ratchet(tree)
    assert result.returncode == sr.EXIT_NEW, result.stdout
    assert "four.py" in result.stdout
    assert "three.py" not in result.stdout


def test_a_vendored_folder_is_left_out_of_duplicates_and_unused_code(tree: Path) -> None:
    (tree / ".fleet.toml").write_text(
        '[static_ratchet]\nenabled = true\n\n[vendored.pkg]\nsrc = "pkg"\ndest = "vendor/pkg/"\n',
        encoding="utf-8",
    )
    assert ratchet(tree, "--init").returncode == 0
    (tree / "vendor" / "pkg").mkdir(parents=True)
    (tree / "vendor" / "pkg" / "dup.py").write_text(py_module("dup", py_block("alpha"), "import json"), encoding="utf-8")
    result = ratchet(tree)
    assert result.returncode == 0, result.stdout


def test_vendored_dests_extend_the_exclusions_of_the_loaded_config(tmp_path: Path) -> None:
    (tmp_path / ".fleet.toml").write_text(
        '[static_ratchet]\nenabled = true\nexclude = ["gen/**"]\n\n'
        '[vendored.a]\ndest = "scripts\\\\a.py"\n[vendored.b]\ndest = "app/vendor/"\n[vendored.c]\nsrc = "no-dest"\n',
        encoding="utf-8",
    )
    cfg = sr.load_config(tmp_path)
    assert cfg is not None
    assert sr.is_excluded("gen/x.py", cfg.exclude)
    assert sr.is_excluded("scripts/a.py", cfg.exclude)
    assert sr.is_excluded("app/vendor/deep/x.js", cfg.exclude)
    assert not sr.is_excluded("scripts/a.pyc", cfg.exclude)
    assert not sr.is_excluded("app/vendor_other/x.js", cfg.exclude)


def test_an_unreadable_fleet_toml_is_a_config_error_never_a_pass(tmp_path: Path) -> None:
    assert run_mode(tmp_path) == sr.EXIT_CONFIG  # no .fleet.toml at all
    (tmp_path / ".fleet.toml").write_text("[vendored\n", encoding="utf-8")
    assert run_mode(tmp_path) == sr.EXIT_CONFIG


# ------------------------------------------------------------ self-adoption

def test_scaffold_adopts_the_stage_and_commits_a_parseable_baseline() -> None:
    cfg = sr.load_config(REPO_ROOT)
    assert cfg is not None, "the scaffold adopts its own stage first (#410)"
    assert (REPO_ROOT / cfg.baseline).is_file()
    sr.read_baseline(REPO_ROOT / cfg.baseline)


def test_gate_runs_the_stage_between_ruff_and_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    ruff, stage, mypy = (text.index(s) for s in ('Invoke-Stage "ruff"', 'Invoke-Stage "static ratchet"', 'Invoke-Stage "mypy'))
    assert ruff < stage < mypy
    assert "scripts/static_ratchet.py" in text


def test_the_script_is_catalogued_so_it_is_mypy_gated_and_drift_checked() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["static_ratchet"] == {"src": "scripts/static_ratchet.py"}
