"""Tests for the file-size, function-length, flat-directory and layer ratchet.

Three layers, mirroring `test_docs_ratchet.py`:

1. **Measuring** on fixture strings: Python and JS function spans (nesting,
   methods, braces inside strings, templates, comments and regexes, an
   unterminated function), the layer import match, directory counts.
2. **Ratchet behaviour** on throwaway git repos, per check: a new offender
   fails, a baselined one at its size passes, growth fails, a shrink lowers the
   baseline, `--update-baseline` never adds, `--allow-additions` adds; every
   mode, and the "not confirmed" exit. A missing prerequisite is a hard
   failure, never `pytest.skip`.
3. **Self-adoption** -- this repo's own declaration, gate wiring and the layout
   doc the failure messages point at.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from scripts import docs_ratchet
from scripts import structure_ratchet as sr
from tests._git_repo import git, write

REPO_ROOT = Path(__file__).resolve().parent.parent


def py_function(name: str, lines: int, indent: str = "") -> str:
    """A Python function exactly `lines` long (its `def` line included)."""
    return f"{indent}def {name}():\n" + f"{indent}    x = 1\n" * (lines - 1)


def js_function(name: str, lines: int) -> str:
    """A JS function declaration exactly `lines` long (header and closing brace included)."""
    return f"function {name}() {{\n" + "  x();\n" * (lines - 2) + "}\n"


def spans(source: str) -> dict[str, int | None]:
    return {s.qualname: s.lines for s in sr.js_spans(source)}


def py_spans(source: str) -> dict[str, int | None]:
    return {s.qualname: s.lines for s in sr.python_spans(ast.parse(source))}


# ------------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert sr.parse_config('layer = "x"\n') is None
    assert sr.parse_config("[structure_ratchet]\nenabled = false\n") is None
    assert sr.parse_config("[structure_ratchet]\n") is None  # opting in is explicit


def test_enabled_table_gets_the_documented_defaults() -> None:
    assert sr.parse_config("[structure_ratchet]\nenabled = true\n") == sr.Config(
        ".structure-ratchet-baseline.json", 1000, 100, 40, (("src", "app"),), ()
    )


def test_enabled_table_honours_every_key() -> None:
    cfg = sr.parse_config(
        '[structure_ratchet]\nenabled = true\nbaseline = "b.json"\nmax_file_lines = 9\nmax_function_lines = 8\n'
        'max_dir_modules = 7\nlayers = [["lib/", "ui\\\\web"]]\nexclude = ["gen/**"]\n'
    )
    assert cfg == sr.Config("b.json", 9, 8, 7, (("lib", "ui/web"),), ("gen/**",))


def test_an_empty_layers_list_turns_the_layer_check_off() -> None:
    cfg = sr.parse_config("[structure_ratchet]\nenabled = true\nlayers = []\n")
    assert cfg is not None and cfg.layers == ()


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("enabled = true\nmax_file_line = 9\n", id="typo-in-key"),
        pytest.param('enabled = "yes"\n', id="enabled-not-bool"),
        pytest.param("enabled = true\nbaseline = ''\n", id="empty-baseline"),
        pytest.param("enabled = true\nmax_file_lines = 0\n", id="limit-zero"),
        pytest.param("enabled = true\nmax_function_lines = '100'\n", id="limit-not-int"),
        pytest.param("enabled = true\nmax_dir_modules = true\n", id="limit-bool"),
        pytest.param("enabled = true\nlayers = ['src', 'app']\n", id="layers-not-pairs"),
        pytest.param("enabled = true\nlayers = [['src']]\n", id="layer-pair-too-short"),
        pytest.param("enabled = true\nlayers = [['src', '/']]\n", id="layer-root-empty"),
        pytest.param("enabled = true\nexclude = 'gen/**'\n", id="exclude-not-a-list"),
    ],
)
def test_malformed_table_fails_loud(body: str) -> None:
    with pytest.raises(sr.ConfigError):
        sr.parse_config("[structure_ratchet]\n" + body)


def test_vendored_dests_are_read_from_the_adopters_own_table() -> None:
    toml = (
        '[vendored]\nnav = { src = "x", sha = "1", dest = "app/static/_vendored/nav/" }\n'
        'single = { src = "y", dest = "scripts\\\\docs_ratchet.py" }\nbare = { src = "z" }\n'
    )
    assert sr.vendored_dests(toml) == ("app/static/_vendored/nav", "scripts/docs_ratchet.py")
    assert sr.vendored_dests('layer = "x"\n') == ()


# --------------------------------------------------------- Python spans

def test_python_spans_cover_functions_methods_and_nested_functions() -> None:
    source = (
        "import x\n"
        "@decorator\n"
        "def outer():\n"
        "    def inner():\n"
        "        return 1\n"
        "    return inner\n"
        "class Box:\n"
        "    async def load(self):\n"
        "        pass\n"
        "    class Meta:\n"
        "        def tag(self): return 2\n"
    )
    assert py_spans(source) == {"outer": 4, "outer.inner": 2, "Box.load": 2, "Box.Meta.tag": 1}


def test_a_nested_function_counts_inside_its_outer_function() -> None:
    source = "def outer():\n" + py_function("inner", 50, "    ") + "    return inner\n"
    assert py_spans(source) == {"outer": 52, "outer.inner": 50}


def test_python_imports_are_absolute_module_names_only() -> None:
    tree = ast.parse("import a.b, c as d\nfrom e.f import g\nfrom . import h\nfrom .i import j\n")
    assert sr.python_imports(tree) == ["a.b", "c", "e.f"]


# ------------------------------------------------------------- JS spans

def test_js_spans_cover_declarations_methods_arrows_and_nesting() -> None:
    source = (
        "export async function load(a) {\n"
        "  return a;\n"
        "}\n"
        "class Box extends Base {\n"
        "  static make() { return 1; }\n"
        "  get size() {\n"
        "    return 2;\n"
        "  }\n"
        "  #secret(x) { if (x) { return 3; } }\n"
        "  async *walk() {}\n"
        "  [Symbol.iterator]() {}\n"
        "}\n"
        "export const mountHome = async (root) => {\n"
        "  const inner = function () {\n"
        "    return 1;\n"
        "  };\n"
        "  items.forEach((x) => { x(); });\n"
        "  return { save() { return 2; }, 'quoted': () => {} };\n"
        "};\n"
        "export default function () {\n"
        "}\n"
        "const one = x => { return x; };\n"
    )
    assert spans(source) == {
        "load": 3, "Box.make": 1, "Box.size": 3, "Box.#secret": 1, "Box.walk": 1, "Box.<computed>": 1,
        "mountHome.inner": 3, "mountHome.<anonymous>": 1, "mountHome.save": 1, "mountHome.quoted": 1,
        "mountHome": 7, "default": 2, "one": 1,
    }


def test_control_statements_and_plain_blocks_are_not_functions() -> None:
    source = (
        "if (a) {\n}\nfor (const x of y) {\n}\nwhile (b) {\n}\nswitch (c) {\n}\n"
        "try {\n} catch (e) {\n} finally {\n}\nconst o = { a: 1 };\n"
    )
    assert spans(source) == {}


def test_a_closure_of_several_hundred_lines_is_measured_as_a_whole() -> None:
    body = "".join(f"  function helper{i}() {{\n    return {i};\n  }}\n" for i in range(150))
    source = "export function mountBoard(root) {\n" + body + "}\n"
    measured = spans(source)
    assert measured["mountBoard"] == 452
    assert measured["mountBoard.helper0"] == 3


@pytest.mark.parametrize(
    "line",
    [
        pytest.param('const s = "}" + "{{";', id="double-quoted-string"),
        pytest.param("const s = '}}' + '{';", id="single-quoted-string"),
        pytest.param("const t = `}${'{'}{ ${a ? `}${b}{` : '}'} }`;", id="template-literal-nesting"),
        pytest.param("// } closing brace in a comment", id="line-comment"),
        pytest.param("/* } { */ const z = 1;", id="block-comment"),
        pytest.param("const r = /[}{]\\}/g;", id="regex-literal"),
        pytest.param("const r = x.replace(/}/g, '');", id="regex-after-paren"),
        pytest.param("if (a) return /{/.test(b);", id="regex-after-return"),
        pytest.param("const h = a / 2 / b; // }", id="division-is-not-a-regex"),
        pytest.param("const s = 'a\\'}';", id="escaped-quote"),
    ],
)
def test_braces_inside_strings_templates_comments_and_regexes_never_count(line: str) -> None:
    source = "function f() {\n  " + line + "\n  return 1;\n}\nfunction g() {\n}\n"
    assert spans(source) == {"f": 4, "g": 2}


def test_a_multi_line_template_or_comment_keeps_line_numbers_right() -> None:
    source = "function f() {\n  const t = `\n  {\n  `;\n  /*\n  }\n  */\n}\nfunction g() {\n}\n"
    assert spans(source) == {"f": 8, "g": 2}


def test_an_unterminated_function_is_recorded_as_unmeasured() -> None:
    source = "function ok() {\n}\nfunction broken() {\n  if (x) {\n"
    assert spans(source) == {"ok": 2, "broken": None}


def test_an_unterminated_comment_leaves_open_functions_unmeasured() -> None:
    assert spans("function f() {\n  /* never closed }\n") == {"f": None}


def test_a_class_named_as_a_property_key_is_not_a_class() -> None:
    assert spans("const o = { class: 'x', run() {\n} };\n") == {"run": 2}


# ------------------------------------------------------------ findings

def test_same_named_functions_rank_by_length() -> None:
    found = sr.function_findings("a.py", [sr.Span("f", 120), sr.Span("f", 3), sr.Span("f", 150)], 100)
    assert {f.key: f.value for f in found} == {"fn:a.py:f": 150, "fn:a.py:f~2": 120}


def test_unmeasured_functions_are_one_entry_per_file() -> None:
    found = sr.function_findings("a.js", [sr.Span("f", None), sr.Span("g", None)], 100)
    assert [(f.key, f.value) for f in found] == [("unmeasured:a.js", 2)]
    assert "f(), g()" in found[0].detail


@pytest.mark.parametrize(
    ("path", "source", "expected"),
    [
        pytest.param("src/m.py", "from app.x import y\n", {"layer:src/m.py:app.x": 1}, id="from-app-sub"),
        pytest.param("src/m.py", "import app\n", {"layer:src/m.py:app": 1}, id="import-app"),
        pytest.param("src/m.py", "import app.web as w\nfrom app.web import v\n", {"layer:src/m.py:app.web": 2},
                     id="counted-per-module"),
        pytest.param("src/sub/m.py", "def f():\n    from app import z\n", {"layer:src/sub/m.py:app": 1},
                     id="nested-and-deferred"),
        pytest.param("src/m.py", "import application\nimport apps.x\n", {}, id="similar-name"),
        pytest.param("src/m.py", "from src.app import x\nfrom . import app\nfrom .app import y\n", {},
                     id="not-the-app-package"),
        pytest.param("src/m.py", "s = 'import app'\n# from app import x\n", {}, id="string-and-comment"),
        pytest.param("app/m.py", "from app.x import y\n", {}, id="outside-src"),
        pytest.param("tests/m.py", "import app\n", {}, id="tests-may-import-app"),
        pytest.param("srcs/m.py", "import app\n", {}, id="prefix-is-a-whole-folder"),
    ],
)
def test_the_layer_check_flags_src_importing_app_and_nothing_else(
    path: str, source: str, expected: dict[str, int]
) -> None:
    found = sr.layer_findings(path, sr.python_imports(ast.parse(source)), sr.DEFAULT_LAYERS)
    assert {f.key: f.value for f in found} == expected


def test_directory_counts_are_direct_children_of_module_types_only() -> None:
    paths = [f"src/m{i}.py" for i in range(3)] + [
        "src/__init__.py", "src/notes.md", "src/page.html", "src/deep/x.py", "src/style.css", "root.js",
    ]
    found = sr.dir_findings(paths, 3)
    assert [(f.key, f.value) for f in found] == [("dir:src", 4)]
    assert "src/<domain>/" in found[0].advice
    assert sr.dir_findings(["a.py", "b.py"], 1)[0].advice.endswith(", <domain>/")


def test_count_lines_matches_an_editor() -> None:
    assert sr.count_lines(b"") == 0
    assert sr.count_lines(b"a\nb\n") == 2
    assert sr.count_lines(b"a\nb") == 2
    assert sr.count_lines(b"a\r\nb\r\n") == 2


def test_scope_and_generated_markers() -> None:
    cfg = sr.Config("b", 10, 5, 3, (), ("gen/**",))
    assert sr.in_scope("a/b.py", cfg, ())
    assert sr.in_scope("s/x.SQL", cfg, ())
    assert not sr.in_scope("a/b.md", cfg, ())
    assert not sr.in_scope("gen/x.py", cfg, ())
    assert not sr.in_scope("web/node_modules/x.js", cfg, ())
    assert not sr.in_scope("vend/x.js", cfg, ("vend",))
    assert sr.is_generated(b"// DO NOT EDIT\nx\n")
    assert sr.is_generated(b"# x\n# @generated\n")
    assert not sr.is_generated(b"# Do NOT edit per-app\n")
    assert not sr.is_generated(b"\n" * 6 + b"DO NOT EDIT\n")


# ------------------------------------------------------- ratchet on a git repo

CONFIG = "[structure_ratchet]\nenabled = true\nmax_file_lines = 10\nmax_function_lines = 5\nmax_dir_modules = 3\n"


def remove(root: Path, rel: str) -> None:
    git(root, "rm", "-q", "-f", rel)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the stage enabled at tiny limits (10 / 5 / 3) and one clean file."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(CONFIG, encoding="utf-8")
    write(tmp_path, "src/ok.py", "x = 1\n")
    return tmp_path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return sr.run(root, init=init, update=update, allow_additions=allow)


def baseline(root: Path) -> dict[str, int]:
    return sr.read_baseline(root / sr.DEFAULT_BASELINE)


#: Per check: (baselined state, grown state, shrunk state, a new offender elsewhere,
#: the key, its baselined value, its shrunk value).
Scenario = tuple[Callable[[Path], None], Callable[[Path], None], Callable[[Path], None], Callable[[Path], None],
                 str, int, int]


def _modules(root: Path, folder: str, n: int) -> None:
    for i in range(n):
        write(root, f"{folder}/m{i}.py", "x = 1\n")


SCENARIOS: dict[str, Scenario] = {
    "file-size": (
        lambda r: write(r, "big.ps1", "x\n" * 12),
        lambda r: write(r, "big.ps1", "x\n" * 13),
        lambda r: write(r, "big.ps1", "x\n" * 11),
        lambda r: write(r, "tests/test_big.py", "x = 1\n" * 11),
        "size:big.ps1", 12, 11,
    ),
    "function-length": (
        lambda r: write(r, "src/f.py", py_function("work", 8)),
        lambda r: write(r, "src/f.py", py_function("work", 9)),
        lambda r: write(r, "src/f.py", py_function("work", 7)),
        lambda r: write(r, "web/v.js", js_function("mountView", 6)),
        "fn:src/f.py:work", 8, 7,
    ),
    "flat-directory": (
        lambda r: _modules(r, "pkg", 5),
        lambda r: write(r, "pkg/extra.css", "a {}\n"),
        lambda r: remove(r, "pkg/m4.py"),
        lambda r: _modules(r, "other", 4),
        "dir:pkg", 5, 4,
    ),
    "layer-contract": (
        lambda r: write(r, "src/m.py", "import app.x\nfrom app.x import y\n"),
        lambda r: write(r, "src/m.py", "import app.x\nfrom app.x import y\nfrom app.x import z\n"),
        lambda r: write(r, "src/m.py", "import app.x\n"),
        lambda r: write(r, "src/n.py", "from app import y\n"),
        "layer:src/m.py:app.x", 2, 1,
    ),
}


@pytest.fixture(params=sorted(SCENARIOS))
def scenario(request: pytest.FixtureRequest) -> Scenario:
    return SCENARIOS[request.param]


def test_a_baselined_offender_at_its_recorded_size_passes(repo: Path, scenario: Scenario) -> None:
    scenario[0](repo)
    assert run_mode(repo, init=True) == sr.EXIT_PASS
    assert baseline(repo) == {scenario[4]: scenario[5]}
    assert run_mode(repo) == sr.EXIT_PASS


def test_a_baselined_offender_that_grows_fails(repo: Path, scenario: Scenario, capsys: pytest.CaptureFixture[str]) -> None:
    scenario[0](repo)
    run_mode(repo, init=True)
    scenario[1](repo)
    capsys.readouterr()
    assert run_mode(repo) == sr.EXIT_RISE
    assert f"baseline {scenario[5]}" in capsys.readouterr().out


def test_a_new_offender_fails(repo: Path, scenario: Scenario, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    scenario[3](repo)
    capsys.readouterr()
    assert run_mode(repo) == sr.EXIT_RISE
    assert "not baselined" in capsys.readouterr().out


def test_a_shrink_passes_and_update_lowers_the_recorded_value(
    repo: Path, scenario: Scenario, capsys: pytest.CaptureFixture[str]
) -> None:
    scenario[0](repo)
    run_mode(repo, init=True)
    scenario[2](repo)
    capsys.readouterr()
    assert run_mode(repo) == sr.EXIT_PASS
    assert "below the baseline" in capsys.readouterr().out
    assert run_mode(repo, update=True) == sr.EXIT_PASS
    assert baseline(repo) == {scenario[4]: scenario[6]}


def test_update_baseline_never_adds_and_writes_nothing(repo: Path, scenario: Scenario) -> None:
    run_mode(repo, init=True)
    before = (repo / sr.DEFAULT_BASELINE).read_text(encoding="utf-8")
    scenario[3](repo)
    assert run_mode(repo, update=True) == sr.EXIT_RISE
    assert (repo / sr.DEFAULT_BASELINE).read_text(encoding="utf-8") == before


def test_allow_additions_adds_and_then_the_check_passes(repo: Path, scenario: Scenario) -> None:
    scenario[0](repo)
    run_mode(repo, init=True)
    scenario[1](repo)
    assert run_mode(repo, update=True) == sr.EXIT_RISE
    assert run_mode(repo, update=True, allow=True) == sr.EXIT_PASS
    assert baseline(repo)[scenario[4]] > scenario[5]
    assert run_mode(repo) == sr.EXIT_PASS


@pytest.mark.parametrize(
    ("make", "title", "limit", "where", "anchor"),
    [
        pytest.param(lambda r: write(r, "big.js", "x;\n" * 11), "file size", "limit 10",
                     "new module beside it", "file-size", id="file-size"),
        pytest.param(lambda r: write(r, "src/f.py", py_function("work", 6)), "function length", "limit 5",
                     "named helpers", "function-length", id="function-length"),
        pytest.param(lambda r: _modules(r, "src", 4), "flat directory", "limit 3",
                     "src/<domain>/", "flat-directory", id="flat-directory"),
        pytest.param(lambda r: write(r, "src/m.py", "import app\n"), "layer contract", "none allowed under src/",
                     "src/ never imports app/", "layer-contract", id="layer-contract"),
        pytest.param(lambda r: write(r, "web/a.js", "function f() {\n"), "function length", "was not found",
                     "fix the syntax", "function-length", id="unmeasured"),
    ],
)
def test_each_failure_message_names_the_rule_the_limit_and_where_code_goes(
    repo: Path, make: Callable[[Path], None], title: str, limit: str, where: str, anchor: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    run_mode(repo, init=True)
    make(repo)
    capsys.readouterr()
    assert run_mode(repo) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert f"[{title}]" in out
    assert limit in out
    assert where in out
    assert f"docs/repo-layout.md#{anchor}" in out


def test_a_baselined_unmeasured_function_passes_and_a_new_one_fails(repo: Path) -> None:
    write(repo, "web/a.js", "function f() {\n")
    run_mode(repo, init=True)
    assert baseline(repo) == {"unmeasured:web/a.js": 1}
    assert run_mode(repo) == sr.EXIT_PASS
    write(repo, "web/a.js", "function f() {\nfunction g() {\n")
    assert run_mode(repo) == sr.EXIT_RISE


def test_code_inserted_above_a_baselined_function_does_not_re_flag_it(repo: Path) -> None:
    write(repo, "src/f.py", py_function("work", 8))
    run_mode(repo, init=True)
    write(repo, "src/f.py", "import os\n\n" + py_function("work", 8))  # 10 lines: still under the file limit
    assert run_mode(repo) == sr.EXIT_PASS


def test_init_writes_a_sorted_baseline_and_never_overwrites(repo: Path) -> None:
    write(repo, "src/f.py", py_function("zeta", 6) + py_function("alpha", 7))
    write(repo, "big.css", "a{}\n" * 11)
    assert run_mode(repo, init=True) == sr.EXIT_PASS
    assert (repo / sr.DEFAULT_BASELINE).read_text(encoding="utf-8") == (
        '{\n  "version": 1,\n  "entries": [\n'
        '    {"key": "fn:src/f.py:alpha", "lines": 7},\n'
        '    {"key": "fn:src/f.py:zeta", "lines": 6},\n'
        '    {"key": "size:big.css", "lines": 11},\n'
        '    {"key": "size:src/f.py", "lines": 13}\n  ]\n}\n'
    )
    assert run_mode(repo, init=True) == sr.EXIT_CONFIG


def test_missing_baseline_fails_instead_of_passing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo) == sr.EXIT_RISE
    assert "is missing" in capsys.readouterr().out


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"version": 2, "entries": []}',
        '{"version": 1}',
        '{"version": 1, "entries": [{"key": "size:a.py", "lines": 0}]}',
        '{"version": 1, "entries": [{"key": "size:a.py", "lines": true}]}',
        '{"version": 1, "entries": [{"key": "size:a.py", "modules": 3}]}',
        '{"version": 1, "entries": [{"key": "size:a.py", "lines": 3, "extra": 1}]}',
        '{"version": 1, "entries": [{"key": "bogus:a.py", "lines": 3}]}',
        '{"version": 1, "entries": [{"lines": 3}]}',
    ],
)
def test_unreadable_baseline_exits_two(repo: Path, text: str) -> None:
    (repo / sr.DEFAULT_BASELINE).write_text(text, encoding="utf-8")
    assert run_mode(repo) == sr.EXIT_CONFIG


def test_disabled_or_absent_stage_exits_zero_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path) == sr.EXIT_PASS
    assert "not enabled" in capsys.readouterr().out
    assert run_mode(tmp_path, init=True) == sr.EXIT_CONFIG


def test_malformed_table_or_toml_exits_two(tmp_path: Path) -> None:
    (tmp_path / ".fleet.toml").write_text("[structure_ratchet]\nenabled = true\nbogus = 1\n", encoding="utf-8")
    assert run_mode(tmp_path) == sr.EXIT_CONFIG
    (tmp_path / ".fleet.toml").write_text("[structure_ratchet\n", encoding="utf-8")
    assert run_mode(tmp_path) == sr.EXIT_CONFIG
    (tmp_path / ".fleet.toml").unlink()
    assert run_mode(tmp_path) == sr.EXIT_CONFIG


def test_vendored_destinations_are_excluded_automatically(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "app/static/_vendored/nav/nav.js", js_function("initNav", 40) + "x;\n" * 20)
    write(repo, "scripts/docs_ratchet.py", py_function("run", 30))
    assert run_mode(repo) == sr.EXIT_RISE
    (repo / ".fleet.toml").write_text(
        CONFIG + '[vendored]\nnav = { src = "x", dest = "app/static/_vendored/nav" }\n'
        'docs = { src = "y", dest = "scripts/docs_ratchet.py" }\n',
        encoding="utf-8",
    )
    assert run_mode(repo) == sr.EXIT_PASS


def test_generated_excluded_untracked_and_other_types_are_not_measured(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "gen/api.py", "# @generated\n" + py_function("big", 40))
    write(repo, "src/wip.py", py_function("big", 40), track=False)
    write(repo, "data/big.json", "1\n" * 40)
    write(repo, "notes.md", "x\n" * 40)
    write(repo, "fixtures/huge.sql", "x\n" * 40)
    (repo / ".fleet.toml").write_text(CONFIG + 'exclude = ["fixtures/**"]\n', encoding="utf-8")
    assert run_mode(repo) == sr.EXIT_PASS


def test_a_tracked_file_deleted_from_the_tree_is_skipped(repo: Path) -> None:
    run_mode(repo, init=True)
    (repo / "src" / "ok.py").unlink()
    assert run_mode(repo) == sr.EXIT_PASS


# ------------------------------------------------------- not confirmed

def test_an_unparsable_python_file_is_not_confirmed_in_every_mode(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_mode(repo, init=True)
    write(repo, "src/bad.py", "def broken(:\n")
    for kwargs in ({}, {"update": True}, {"update": True, "allow": True}):
        assert run_mode(repo, **kwargs) == sr.EXIT_NOT_CONFIRMED
        out = capsys.readouterr().out
        assert "NOT CONFIRMED" in out
        assert "src/bad.py" in out
    (repo / sr.DEFAULT_BASELINE).unlink()
    assert run_mode(repo, init=True) == sr.EXIT_NOT_CONFIRMED
    assert not (repo / sr.DEFAULT_BASELINE).exists()


def test_git_that_cannot_list_files_is_not_confirmed(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_mode(repo, init=True)
    monkeypatch.setenv("GIT_DIR", str(repo / "no-such-git-dir"))
    assert run_mode(repo) == sr.EXIT_NOT_CONFIRMED
    assert "git ls-files" in capsys.readouterr().out


def test_a_missing_git_binary_is_not_confirmed(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_mode(repo, init=True)
    monkeypatch.setenv("PATH", str(repo / "empty"))
    assert run_mode(repo) == sr.EXIT_NOT_CONFIRMED


def test_main_rejects_allow_additions_without_update(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        sr.main(["--allow-additions"])
    assert exc.value.code == 2
    assert "--allow-additions" in capsys.readouterr().err


# ------------------------------------------------------------- root layout

#: shape id -> (required root folders, other allowed root folders); pinned here on purpose, so a
#: change to a preset in the script is a deliberate edit in two places (and the doc table).
EXPECTED_SHAPES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "webapp-tray": (("app", "src", "tests", "docs"), ("scripts", "data", "brand")),
    "streamlit": (("app", "src", "tests"), ("scripts", "data", "brand")),
    "pipeline-cli": (("tests",), ("src", "common", "scripts", "config", "data")),
    "skills-governance": (("skills", "tests"), ("hooks", "scripts", "architecture")),
    "node": (("src",), ("test", "scripts")),
    "static-site": ((), ("css", "js", "assets", "games")),
}
SHAPE_IDS = list(EXPECTED_SHAPES)
SHAPES_WITH_REQUIRED = [(s, f) for s, (required, _allowed) in EXPECTED_SHAPES.items() for f in required]


def assert_layout_passes(root: Path, shape: str, capsys: pytest.CaptureFixture[str]) -> None:
    """The check passes AND says it checked the layout, so a stage that ignores `shape` cannot pass this."""
    capsys.readouterr()
    assert run_mode(root) == sr.EXIT_PASS
    assert f"layout matches {shape}" in capsys.readouterr().out


def shape_repo(root: Path, shape: str | None, folders: Iterable[str], extra_roots: Iterable[str] | None = None) -> Path:
    """A git repo declaring `shape` (and `extra_roots`), one tracked file in each folder, baseline initialised."""
    git(root, "init", "-q")
    head = f'shape = "{shape}"\n' if shape else ""
    if extra_roots is not None:
        head += f"extra_roots = {json.dumps(list(extra_roots))}\n"
    (root / ".fleet.toml").write_text(head + CONFIG, encoding="utf-8")
    for folder in folders:
        write(root, f"{folder}/keep.txt", "x\n")
    assert run_mode(root, init=True) == sr.EXIT_PASS
    return root


def test_the_script_carries_exactly_the_expected_presets() -> None:
    assert {s: (p.required, p.allowed) for s, p in sr.SHAPES.items()} == EXPECTED_SHAPES


@pytest.mark.parametrize("shape", SHAPE_IDS)
def test_a_repo_with_exactly_its_required_folders_passes_and_names_the_shape(
    tmp_path: Path, shape: str, capsys: pytest.CaptureFixture[str]
) -> None:
    shape_repo(tmp_path, shape, EXPECTED_SHAPES[shape][0])
    assert_layout_passes(tmp_path, shape, capsys)


@pytest.mark.parametrize("shape", SHAPE_IDS)
def test_every_allowed_folder_and_the_always_allowed_ones_pass(
    tmp_path: Path, shape: str, capsys: pytest.CaptureFixture[str]
) -> None:
    required, allowed = EXPECTED_SHAPES[shape]
    shape_repo(tmp_path, shape, (*required, *allowed, "docs", ".github", ".claude"))
    assert_layout_passes(tmp_path, shape, capsys)


@pytest.mark.parametrize(("shape", "missing"), SHAPES_WITH_REQUIRED)
def test_a_missing_required_folder_fails_by_name(
    tmp_path: Path, shape: str, missing: str, capsys: pytest.CaptureFixture[str]
) -> None:
    shape_repo(tmp_path, shape, [f for f in EXPECTED_SHAPES[shape][0] if f != missing])
    capsys.readouterr()
    assert run_mode(tmp_path) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert f"shape {shape}: required folder {missing}/" in out
    assert f"repo-layout.md#{shape}" in out


@pytest.mark.parametrize("shape", SHAPE_IDS)
def test_an_undeclared_root_fails_naming_the_shape_the_folder_and_both_fixes(
    tmp_path: Path, shape: str, capsys: pytest.CaptureFixture[str]
) -> None:
    shape_repo(tmp_path, shape, (*EXPECTED_SHAPES[shape][0], "utils2"))
    capsys.readouterr()
    assert run_mode(tmp_path) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert f"shape {shape}: utils2/ is not a folder this shape lists" in out
    assert "move its code into one of" in out
    assert "declare 'utils2' in `extra_roots`" in out


@pytest.mark.parametrize("shape", SHAPE_IDS)
def test_the_same_folder_declared_in_extra_roots_passes(
    tmp_path: Path, shape: str, capsys: pytest.CaptureFixture[str]
) -> None:
    shape_repo(tmp_path, shape, (*EXPECTED_SHAPES[shape][0], "utils2"), extra_roots=["utils2"])
    assert_layout_passes(tmp_path, shape, capsys)


def test_extra_roots_never_waive_a_required_folder(tmp_path: Path) -> None:
    shape_repo(tmp_path, "streamlit", ("app", "src"), extra_roots=["tests"])
    assert run_mode(tmp_path) == sr.EXIT_RISE


def test_layout_findings_are_never_baselined(tmp_path: Path) -> None:
    shape_repo(tmp_path, "streamlit", ("app", "src", "tests", "utils2"))
    assert not any(k.startswith("layout") for k in baseline(tmp_path)), "layout is not a baseline kind"
    assert run_mode(tmp_path) == sr.EXIT_RISE
    assert run_mode(tmp_path, update=True, allow=True) == sr.EXIT_PASS
    assert run_mode(tmp_path) == sr.EXIT_RISE, "--allow-additions raises the baseline, never the layout"


def test_layout_and_baseline_findings_are_both_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shape_repo(tmp_path, "streamlit", ("app", "src", "tests", "utils2"))
    write(tmp_path, "src/big.py", "x = 1\n" * 11)
    capsys.readouterr()
    assert run_mode(tmp_path) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert "[file size]" in out
    assert "[root layout]" in out


def test_untracked_folders_and_root_files_are_not_roots(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shape_repo(tmp_path, "streamlit", ("app", "src", "tests"))
    write(tmp_path, "scratch/x.txt", "x\n", track=False)
    write(tmp_path, "main.py", "x = 1\n")
    assert_layout_passes(tmp_path, "streamlit", capsys)


def test_no_shape_skips_the_layout_check_with_a_stated_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shape_repo(tmp_path, None, ("anything", "goes"))
    capsys.readouterr()
    assert run_mode(tmp_path) == sr.EXIT_PASS
    out = capsys.readouterr().out
    assert "layout check not applicable (no `shape` in .fleet.toml)" in out
    assert "layout matches" not in out, "a skip is never reported as a pass"


def test_no_shape_still_runs_the_other_four_checks(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    shape_repo(tmp_path, None, ("anything",))
    write(tmp_path, "anything/big.py", "x = 1\n" * 11)
    capsys.readouterr()
    assert run_mode(tmp_path) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert "[file size]" in out
    assert "not applicable" in out


@pytest.mark.parametrize("mode", ["check", "init"])
def test_an_unknown_shape_is_not_confirmed_never_a_skip(
    tmp_path: Path, mode: str, capsys: pytest.CaptureFixture[str]
) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text('shape = "monolith"\n' + CONFIG, encoding="utf-8")
    write(tmp_path, "src/ok.py", "x = 1\n")
    assert run_mode(tmp_path, init=mode == "init") == sr.EXIT_NOT_CONFIRMED
    out = capsys.readouterr().out
    assert "NOT CONFIRMED" in out
    assert "'monolith'" in out
    assert "webapp-tray" in out, "the message lists the allowed ids"


@pytest.mark.parametrize(
    "head",
    [
        pytest.param("shape = 3\n", id="shape-not-a-string"),
        pytest.param('extra_roots = "docs"\n', id="extra-roots-a-string"),
        pytest.param("extra_roots = [3]\n", id="extra-root-not-a-string"),
        pytest.param('extra_roots = [""]\n', id="extra-root-empty"),
        pytest.param('extra_roots = ["a/b"]\n', id="extra-root-nested"),
    ],
)
def test_a_malformed_shape_or_extra_roots_fails_loud(head: str) -> None:
    with pytest.raises(sr.ConfigError):
        sr.parse_config(head + CONFIG)


def test_shape_and_extra_roots_are_read_from_the_top_level() -> None:
    cfg = sr.parse_config('shape = "node"\nextra_roots = ["dist/", "web\\\\"]\n' + CONFIG)
    assert cfg is not None
    assert (cfg.shape, cfg.extra_roots) == ("node", ("dist", "web"))
    plain = sr.parse_config(CONFIG)
    assert plain is not None
    assert (plain.shape, plain.extra_roots) == (None, ())


def test_the_shape_fills_the_layer_pair_only_when_the_table_does_not_set_one() -> None:
    def layers(head: str, extra: str = "") -> tuple[tuple[str, str], ...]:
        cfg = sr.parse_config(head + CONFIG + extra)
        assert cfg is not None
        return cfg.layers

    assert layers('shape = "webapp-tray"\n') == (("src", "app"),)
    assert layers('shape = "streamlit"\n') == (("src", "app"),)
    for shape in ("pipeline-cli", "skills-governance", "node", "static-site"):
        assert layers(f'shape = "{shape}"\n') == ()
    assert layers('shape = "pipeline-cli"\n', 'layers = [["lib", "ui"]]\n') == (("lib", "ui"),)
    assert layers("") == sr.DEFAULT_LAYERS, "a repo with no shape keeps the default pair"


# ------------------------------------------------------------ self-adoption

def test_scaffold_adopts_the_stage_and_commits_a_parseable_baseline() -> None:
    cfg, _ = sr.load_config(REPO_ROOT)
    assert cfg is not None, "the scaffold adopts its own stage"
    assert (REPO_ROOT / cfg.baseline).is_file()
    sr.read_baseline(REPO_ROOT / cfg.baseline)


def test_gate_runs_the_stage_after_the_docs_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    docs, stage, mypy = (
        text.index(s) for s in ('Invoke-Stage "docs ratchet"', 'Invoke-Stage "structure ratchet"', 'Invoke-Stage "mypy')
    )
    assert docs < stage < mypy
    assert "scripts/structure_ratchet.py" in text


def test_the_script_is_catalogued_so_it_is_mypy_gated_and_drift_checked() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["structure_ratchet"] == {"src": "scripts/structure_ratchet.py"}


def test_the_scaffold_declares_its_shape_and_its_layout_passes() -> None:
    cfg, _ = sr.load_config(REPO_ROOT)
    assert cfg is not None
    assert (cfg.shape, cfg.extra_roots) == ("streamlit", ())
    assert sr.layout_findings(sr.tracked_files(REPO_ROOT), cfg) == []


def _doc_shape_table() -> dict[str, tuple[set[str], set[str], str]]:
    """The shape table of docs/structure-ratchet.md: id -> (required, allowed, layers cell)."""
    text = (REPO_ROOT / "docs" / "structure-ratchet.md").read_text(encoding="utf-8")
    rows = {}
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.fullmatch(r"`[a-z-]+`", cells[0]) and cells[0].strip("`") in sr.SHAPES:
            required, allowed = (set(re.findall(r"`(\w+)`", cell)) for cell in cells[1:3])
            rows[cells[0].strip("`")] = (required, allowed, cells[3])
    return rows


def test_the_doc_table_matches_the_presets_in_the_script() -> None:
    rows = _doc_shape_table()
    assert set(rows) == set(sr.SHAPES), "every shape has a row in docs/structure-ratchet.md"
    for shape, preset in sr.SHAPES.items():
        required, allowed, layers = rows[shape]
        assert required == set(preset.required), shape
        assert allowed == set(preset.allowed), shape
        want = "`" + json.dumps([list(p) for p in preset.layers]) + "`" if preset.layers else "none"
        assert layers == want, shape


def test_every_shape_id_is_a_section_of_the_layout_doc() -> None:
    text = (REPO_ROOT / "docs" / "repo-layout.md").read_text(encoding="utf-8")
    headings = {m.group(1).strip() for m in re.finditer(r"^## (.+)$", text, re.MULTILINE)}
    assert set(sr.SHAPES) <= headings, "the failure message links docs/repo-layout.md#<shape>"


def test_every_anchor_a_failure_message_names_exists_in_the_layout_doc() -> None:
    text = (REPO_ROOT / "docs" / "repo-layout.md").read_text(encoding="utf-8")
    headings = {
        re.sub(r"[^\w\- ]", "", m.group(1).strip().lower()).replace(" ", "-")
        for m in re.finditer(r"^#{2,4} (.+)$", text, re.MULTILINE)
    }
    for _field, _title, anchor in sr.KINDS.values():
        assert anchor in headings, f"docs/repo-layout.md has no heading for #{anchor}"


def test_the_layout_doc_states_the_limits_the_script_enforces() -> None:
    text = (REPO_ROOT / "docs" / "repo-layout.md").read_text(encoding="utf-8")
    assert f"**{sr.DEFAULT_MAX_FILE_LINES:,} lines**" in text
    assert f"**{sr.DEFAULT_MAX_FUNCTION_LINES} lines**" in text
    assert f"**{sr.DEFAULT_MAX_DIR_MODULES} modules**" in text


def test_the_new_doc_carries_no_history_marker() -> None:
    text = (REPO_ROOT / "docs" / "structure-ratchet.md").read_text(encoding="utf-8")
    assert docs_ratchet.scan_text(text) == []
