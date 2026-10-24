"""Tests for the dead-code ratchet.

Three layers, mirroring `test_doc_refs_ratchet.py`:

1. **Detection** on fixture sources: what counts as a reference, which
   definitions are entry points (routes, exports, tests, hooks, components,
   `allow`), and what lowers a finding's confidence below the floor.
2. **Ratchet behaviour** on throwaway git repos: a newly added uncalled function
   fails and names the file, line and definition; every mode; and the "not
   confirmed" exit for anything that cannot be read through. A missing
   prerequisite is a hard failure, never `pytest.skip`.
3. **Self-adoption** -- this repo's own declaration and gate wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import dead_code_ratchet as dc
from tests._git_repo import git, write

REPO_ROOT = Path(__file__).resolve().parent.parent
ENABLED = dc.Config(dc.DEFAULT_BASELINE, (), (), dc.DEFAULT_MIN_CONFIDENCE, (), ())


def dead(files: dict[str, str], cfg: dc.Config = ENABLED, *, components: tuple[str, ...] = (),
         mentions: frozenset[str] = frozenset()) -> dict[str, list[str]]:
    """{path: [qualname, ...]} of what `judge` reports for in-memory sources."""
    scans = {path: dc.scan_source(src, path) for path, src in files.items()}
    names = frozenset(n for s in scans.values() for n in s.names)
    strings = frozenset(w for s in scans.values() for w in s.strings) | mentions
    classes = {k: v for s in scans.values() for k, v in s.classes.items()}
    found = dc.judge(scans, dc.Usage(names, strings, classes), cfg, set(scans), components)
    return {path: [f.definition.qualname for f in fs] for path, fs in found.items()}


# ------------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert dc.parse_config('layer = "x"\n') is None
    assert dc.parse_config("[dead_code_ratchet]\nenabled = false\n") is None
    assert dc.parse_config("[dead_code_ratchet]\n") is None  # opting in is explicit


def test_enabled_table_gets_the_documented_defaults() -> None:
    assert dc.parse_config("[dead_code_ratchet]\nenabled = true\n") == ENABLED


def test_enabled_table_honours_every_key() -> None:
    cfg = dc.parse_config(
        '[dead_code_ratchet]\nenabled = true\nbaseline = "b.json"\ninclude = ["src/"]\nexclude = ["src/gen/**"]\n'
        'min_confidence = 60\nentry_decorators = ["bus.subscribe"]\nallow = ["app/menu.py:on_*"]\n'
    )
    assert cfg == dc.Config("b.json", ("src/",), ("src/gen/**",), 60, ("bus.subscribe",), ("app/menu.py:on_*",))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("enabled = true\nallowed = ['x']\n", id="typo-in-key"),
        pytest.param('enabled = "yes"\n', id="enabled-not-bool"),
        pytest.param("enabled = true\nbaseline = ''\n", id="empty-baseline"),
        pytest.param("enabled = true\nmin_confidence = 101\n", id="floor-above-100"),
        pytest.param("enabled = true\nmin_confidence = true\n", id="floor-not-int"),
        pytest.param("enabled = true\ninclude = 'src/'\n", id="include-not-a-list"),
        pytest.param("enabled = true\nentry_decorators = [1]\n", id="decorators-not-strings"),
    ],
)
def test_malformed_table_fails_loud(body: str) -> None:
    with pytest.raises(dc.ConfigError):
        dc.parse_config("[dead_code_ratchet]\n" + body)


# ---------------------------------------------------------------- detection

def test_an_uncalled_function_class_and_method_are_dead() -> None:
    src = (
        "def used():\n    pass\n\n"
        "def unused():\n    pass\n\n"
        "class Orphan:\n    pass\n\n"
        "class Kept:\n    def run(self):\n        pass\n    def spare(self):\n        pass\n\n"
        "used()\nKept().run()\n"
    )
    assert dead({"src/a.py": src}) == {"src/a.py": ["unused", "Orphan", "Kept.spare"]}


@pytest.mark.parametrize(
    "use",
    [
        pytest.param("cb = target\n", id="passed-as-a-value"),
        pytest.param("x: target\n", id="annotation"),
        pytest.param("import m\nm.target()\n", id="attribute"),
        pytest.param("from src.a import target\n", id="import"),
        pytest.param("obj.target = 1\n", id="attribute-store-runs-a-setter"),
    ],
)
def test_any_read_of_the_name_anywhere_counts_as_a_reference(use: str) -> None:
    assert dead({"src/a.py": "def target():\n    pass\n", "src/b.py": use}) == {}


def test_a_nested_function_nobody_calls_is_dead_by_its_qualname() -> None:
    src = "def outer():\n    def inner():\n        pass\n    return 1\n\nouter()\n"
    assert dead({"src/a.py": src}) == {"src/a.py": ["outer.inner"]}


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("@app.get('/x')\ndef handler():\n    pass\n", id="route-decorator"),
        pytest.param("@router.post\nasync def handler():\n    pass\n", id="async-route-no-call"),
        pytest.param("@pytest.fixture\ndef handler():\n    pass\n", id="fixture"),
        pytest.param("@field_validator('x')\ndef handler(cls, v):\n    pass\n", id="validator"),
        pytest.param("@mcp.tool()\ndef handler():\n    pass\n", id="mcp-tool"),
        pytest.param("@atexit.register\ndef handler():\n    pass\n", id="register"),
        pytest.param("__all__ = ['handler']\ndef handler():\n    pass\n", id="__all__"),
        pytest.param("def pytest_configure(config):\n    pass\n", id="pytest-hook-in-a-plugin"),
        pytest.param("class C:\n    def __repr__(self):\n        return ''\nC()\n", id="dunder"),
    ],
)
def test_route_handlers_exports_and_hooks_are_entry_points(src: str) -> None:
    assert dead({"src/a.py": src}) == {}


def test_a_route_less_handler_is_dead() -> None:
    src = "@app.get('/x')\ndef routed():\n    pass\n\ndef lost_its_route():\n    pass\n"
    assert dead({"app/routes.py": src}) == {"app/routes.py": ["lost_its_route"]}


def test_entry_decorators_and_allow_extend_the_built_ins() -> None:
    src = "@bus.subscribe('e')\ndef on_event():\n    pass\n\ndef on_quit():\n    pass\n\ndef gone():\n    pass\n"
    cfg = dc.Config(dc.DEFAULT_BASELINE, (), (), 100, ("bus.subscribe",), ("app/tray/*.py:on_*",))
    assert dead({"app/tray/menu.py": src}) == {"app/tray/menu.py": ["on_event", "on_quit", "gone"]}
    assert dead({"app/tray/menu.py": src}, cfg) == {"app/tray/menu.py": ["gone"]}


def test_tests_are_entry_points_but_an_unused_test_helper_is_not() -> None:
    src = (
        "import unittest\n"
        "def test_a():\n    pass\n\n"
        "class TestB:\n    def test_c(self):\n        pass\n    def setup_method(self):\n        pass\n\n"
        "class Cases(unittest.TestCase):\n    def setUp(self):\n        pass\n    def test_d(self):\n        pass\n\n"
        "class _Mixin:\n    def test_inherited(self):\n        pass\n\n"
        "def _helper():\n    pass\n"
    )
    for name in ("tests/test_x.py", "tests/test01_x.py", "tests/x_test.py"):
        assert dead({name: src}) == {name: ["_Mixin", "_helper"]}
    assert dead({"src/x.py": src})["src/x.py"][0] == "test_a", "test naming is an entry point only in a test module"


def test_a_component_publishes_its_public_top_level_names_only() -> None:
    src = "def api():\n    pass\n\ndef _private():\n    pass\n\nclass Pub:\n    def spare(self):\n        pass\n"
    assert dead({"src/comp.py": src}, components=("src/comp.py",)) == {"src/comp.py": ["_private", "Pub.spare"]}


TARGET = "def target():\n    pass\n"


@pytest.mark.parametrize(
    ("files", "mentions"),
    [
        pytest.param({"src/a.py": TARGET, "src/b.py": "getattr(obj, 'target')()\n"}, frozenset(), id="string-literal"),
        pytest.param({"src/a.py": TARGET, "src/b.py": "JS = 'window.api.target(next);'\n"}, frozenset(),
                     id="code-in-a-string"),
        pytest.param({"src/a.py": TARGET}, frozenset({"target"}), id="non-python-file"),
        pytest.param({"src/a.py": TARGET + "def go(obj, name):\n    return getattr(obj, name)\ngo(1, 'x')\n"},
                     frozenset(), id="computed-getattr-in-its-module"),
    ],
)
def test_possible_dynamic_use_lowers_confidence_below_the_default_floor(
    files: dict[str, str], mentions: frozenset[str]
) -> None:
    assert dead(files, mentions=mentions) == {}
    low = dc.Config(dc.DEFAULT_BASELINE, (), (), 60, (), ())
    assert "target" in dead(files, low, mentions=mentions)["src/a.py"]


def test_a_docstring_mentioning_the_name_does_not_hide_it() -> None:
    src = '"""Call target() when needed."""\ndef target():\n    """target does it."""\n'
    assert dead({"src/a.py": src}) == {"src/a.py": ["target"]}


def test_a_method_on_a_framework_subclass_is_low_confidence() -> None:
    src = (
        "import threading\n"
        "class Base(threading.Thread):\n    pass\n\n"
        "class Worker(Base):\n    def run(self):\n        pass\n\n"
        "class Plain:\n    def run2(self):\n        pass\n\n"
        "Worker()\nPlain()\n"
    )
    assert dead({"src/a.py": src}) == {"src/a.py": ["Plain.run2"]}


def test_a_file_that_does_not_parse_is_not_confirmed() -> None:
    with pytest.raises(dc.NotConfirmed, match="does not parse"):
        dc.scan_source(b"def broken(:\n", "src/a.py")
    with pytest.raises(dc.NotConfirmed, match="does not parse"):
        dc.scan_source(b"x = 'caf\xe9'\n", "src/latin.py")


def test_scope_reports_only_included_python_outside_vendored_and_excluded() -> None:
    cfg = dc.Config(dc.DEFAULT_BASELINE, ("src/",), ("src/gen/**",), 100, (), ())
    picked = [p for p in ("src/a.py", "src/gen/b.py", "src/vend/c.py", "app/d.py", "src/e.txt")
              if dc.in_scope(p, cfg, ("src/vend",))]
    assert picked == ["src/a.py"]


# ------------------------------------------------------- ratchet on a git repo

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the stage enabled, one live and one dead function."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text("[dead_code_ratchet]\nenabled = true\n", encoding="utf-8")
    write(tmp_path, "src/a.py", "def live():\n    pass\n\ndef old_helper():\n    pass\n\nlive()\n")
    return tmp_path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return dc.run(root, init=init, update=update, allow_additions=allow)


def baseline_text(root: Path) -> str:
    return (root / dc.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_init_records_each_dead_definition_and_never_overwrites(repo: Path) -> None:
    assert run_mode(repo, init=True) == dc.EXIT_PASS
    assert '{"key": "src/a.py", "names": ["old_helper"]}' in baseline_text(repo)
    assert run_mode(repo, init=True) == dc.EXIT_CONFIG


def test_unchanged_tree_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    assert run_mode(repo) == dc.EXIT_PASS
    assert "PASS (1 baselined dead definition(s) in 1 file(s), none new" in capsys.readouterr().out


def test_a_newly_added_uncalled_function_fails_by_name(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "src/b.py", "x = 1\n\ndef forgotten_helper():\n    return x\n")
    capsys.readouterr()
    assert run_mode(repo) == dc.EXIT_RISE
    assert "src/b.py:3: function `forgotten_helper` is never referenced (confidence 100)" in capsys.readouterr().out


def test_swapping_one_dead_definition_for_another_fails(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/a.py", "def live():\n    pass\n\ndef other_helper():\n    pass\n\nlive()\n")
    assert run_mode(repo) == dc.EXIT_RISE


def test_route_handlers_and_exports_do_not_trip_the_gate(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "app/routes.py", "@router.get('/x')\ndef page():\n    pass\n")
    write(repo, "src/pkg.py", "__all__ = ['public']\n\ndef public():\n    pass\n")
    assert run_mode(repo) == dc.EXIT_PASS


def test_a_deleted_dead_definition_passes_with_a_shrink_hint(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "src/a.py", "def live():\n    pass\n\nlive()\n")
    assert run_mode(repo) == dc.EXIT_PASS
    assert "1 baselined definition(s) are now referenced or gone" in capsys.readouterr().out


def test_update_baseline_shrinks_only(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/a.py", "def live():\n    pass\n\nlive()\n")
    assert run_mode(repo, update=True) == dc.EXIT_PASS
    assert '"entries": []' in baseline_text(repo)
    write(repo, "src/b.py", "def new_dead():\n    pass\n")
    assert run_mode(repo, update=True) == dc.EXIT_RISE
    assert "new_dead" not in baseline_text(repo), "a refused update writes nothing"


def test_allow_additions_adds_to_the_baseline(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/b.py", "def new_dead():\n    pass\n")
    assert run_mode(repo, update=True, allow=True) == dc.EXIT_PASS
    assert "new_dead" in baseline_text(repo)
    assert run_mode(repo) == dc.EXIT_PASS


def test_missing_baseline_fails_instead_of_passing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo) == dc.EXIT_RISE
    assert "baseline .dead-code-ratchet-baseline.json is missing" in capsys.readouterr().out


@pytest.mark.parametrize("text", ["not json", '{"version": 9, "entries": []}', '{"version": 1, "entries": [{"key": "a"}]}'])
def test_unreadable_baseline_exits_two(repo: Path, text: str) -> None:
    (repo / dc.DEFAULT_BASELINE).write_text(text, encoding="utf-8")
    assert run_mode(repo) == dc.EXIT_CONFIG


def test_disabled_or_absent_stage_exits_zero_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path) == dc.EXIT_PASS
    assert "not enabled" in capsys.readouterr().out
    assert run_mode(tmp_path, init=True) == dc.EXIT_CONFIG


def test_untracked_and_vendored_files_are_not_reported(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/scratch.py", "def untracked_dead():\n    pass\n", track=False)
    write(repo, "src/vend/x.py", "def vendored_dead():\n    pass\n")
    (repo / ".fleet.toml").write_text(
        '[dead_code_ratchet]\nenabled = true\n[vendored]\nx = { dest = "src/vend/" }\n', encoding="utf-8"
    )
    assert run_mode(repo) == dc.EXIT_PASS


def test_a_tracked_baseline_does_not_count_as_a_reference_to_its_entries(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_mode(repo, init=True)
    git(repo, "add", "-f", dc.DEFAULT_BASELINE)
    capsys.readouterr()
    assert run_mode(repo) == dc.EXIT_PASS
    assert "PASS (1 baselined dead definition(s) in 1 file(s), none new" in capsys.readouterr().out
    assert run_mode(repo, update=True) == dc.EXIT_PASS
    assert '{"key": "src/a.py", "names": ["old_helper"]}' in baseline_text(repo)


def test_a_reference_from_an_excluded_file_still_counts(repo: Path) -> None:
    (repo / ".fleet.toml").write_text('[dead_code_ratchet]\nenabled = true\nexclude = ["tools/**"]\n', encoding="utf-8")
    write(repo, "tools/use.py", "from src.a import old_helper\n")
    write(repo, "tools/dead.py", "def excluded_dead():\n    pass\n")
    assert run_mode(repo, init=True) == dc.EXIT_PASS
    assert '"entries": []' in baseline_text(repo)


# ------------------------------------------------------- not confirmed

MODES = ({}, {"update": True}, {"update": True, "allow": True})


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
    run_mode(repo, init=True)
    (repo / "src" / "bad.py").write_bytes(body)
    git(repo, "add", "src/bad.py")
    for kwargs in MODES:
        assert run_mode(repo, **kwargs) == dc.EXIT_NOT_CONFIRMED
        out = capsys.readouterr().out
        assert "NOT CONFIRMED: src/bad.py" in out and says in out
    (repo / dc.DEFAULT_BASELINE).unlink()
    assert run_mode(repo, init=True) == dc.EXIT_NOT_CONFIRMED
    assert not (repo / dc.DEFAULT_BASELINE).exists(), "--init writes nothing it could not confirm"


@pytest.mark.parametrize(
    ("var", "value", "says"),
    [("GIT_DIR", "no-such-git-dir", "git ls-files"), ("PATH", "empty", "git could not start")],
)
def test_git_that_cannot_list_the_tree_is_not_confirmed(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], var: str, value: str, says: str
) -> None:
    run_mode(repo, init=True)
    monkeypatch.setenv(var, str(repo / value))
    assert run_mode(repo) == dc.EXIT_NOT_CONFIRMED
    assert says in capsys.readouterr().out


def test_main_rejects_allow_additions_without_update(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        dc.main(["--allow-additions"])
    assert exc.value.code == 2
    assert "--allow-additions" in capsys.readouterr().err


# ------------------------------------------------------------ self-adoption

def test_scaffold_adopts_the_stage_and_commits_a_parseable_baseline() -> None:
    cfg, _, _ = dc.load_config(REPO_ROOT)
    assert cfg is not None, "the scaffold adopts its own stage first"
    assert (REPO_ROOT / cfg.baseline).is_file()
    dc.read_baseline(REPO_ROOT / cfg.baseline)


def test_gate_runs_the_stage_after_the_doc_refs_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    before, stage, mypy = (
        text.index(s) for s in ('Invoke-Stage "doc refs ratchet"', 'Invoke-Stage "dead code ratchet"', 'Invoke-Stage "mypy')
    )
    assert before < stage < mypy
    assert "scripts/dead_code_ratchet.py" in text


def test_the_script_is_catalogued_so_it_is_mypy_gated_and_drift_checked() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["dead_code_ratchet"] == {"src": "scripts/dead_code_ratchet.py"}
