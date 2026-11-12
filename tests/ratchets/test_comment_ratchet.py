"""Tests for the `#NNN`-in-comments ratchet (project-scaffolding#411).

Three layers, mirroring `test_static_ratchet.py`:

1. **Counting**, per language, on fixture strings: what a real comment scanner
   counts and what it must not (strings, templates, regex literals, URLs...).
2. **Ratchet behaviour** on throwaway git repos: a risen count fails and names
   the file, a lowered one passes, every mode, exclusions, and the "not
   confirmed" exit for anything the scanner cannot finish. A missing
   prerequisite is a hard failure, never `pytest.skip`.
3. **Self-adoption** -- this repo's own declaration and gate wiring.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest

from scripts import comment_ratchet as cr
from tests._git_repo import git, write
from tests._ratchet_not_confirmed import (
    assert_unreadable_file_not_confirmed,
    git_failure_test,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def count(text: str, language: str) -> int:
    return len(cr.scan_text(text, language))


# ------------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert cr.parse_config('layer = "x"\n') is None
    assert cr.parse_config("[comment_ratchet]\nenabled = false\n") is None
    assert cr.parse_config("[comment_ratchet]\n") is None  # opting in is explicit


def test_enabled_table_gets_the_documented_defaults() -> None:
    assert cr.parse_config("[comment_ratchet]\nenabled = true\n") == cr.Config(".comment-ratchet-baseline.json", (), ())


def test_enabled_table_honours_every_key() -> None:
    cfg = cr.parse_config(
        '[comment_ratchet]\nenabled = true\nbaseline = "b.json"\ninclude = ["app/"]\nexclude = ["**/gen/**"]\n'
    )
    assert cfg == cr.Config("b.json", ("app/",), ("**/gen/**",))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("enabled = true\nbaselin = 'x'\n", id="typo-in-key"),
        pytest.param('enabled = "yes"\n', id="enabled-not-bool"),
        pytest.param("enabled = true\nbaseline = ''\n", id="empty-baseline"),
        pytest.param("enabled = true\ninclude = 'app/'\n", id="include-not-a-list"),
        pytest.param("enabled = true\nexclude = [1]\n", id="exclude-not-strings"),
    ],
)
def test_malformed_table_fails_loud(body: str) -> None:
    with pytest.raises(cr.ConfigError):
        cr.parse_config("[comment_ratchet]\n" + body)


def test_vendored_dests_are_read_from_the_adopters_own_table() -> None:
    toml = (
        '[vendored]\nnav = { src = "x", sha = "1", dest = "app/webapp/static/_vendored/nav" }\n'
        'single = { src = "y", dest = "app\\\\tray\\\\single_instance.py" }\nbare = { src = "z" }\n'
    )
    assert cr.vendored_dests(toml) == ("app/tray/single_instance.py", "app/webapp/static/_vendored/nav")
    assert cr.vendored_dests('layer = "x"\n') == ()


# ------------------------------------------------------------------ counting: Python

def test_python_comment_counts_and_string_forms_do_not() -> None:
    src = (
        'x = 1  # since #123\n'
        'y = "see #124"\n'
        "z = f'{x} #125'\n"
        'def f():\n'
        '    """Docstring mentioning #126."""\n'
        "    return '''\n#127\n'''\n"
    )
    refs = cr.scan_text(src, "py")
    assert [r.line for r in refs] == [1]


def test_several_references_on_one_line_count_separately() -> None:
    assert count("x = 1  # #12 then #13 and repo#14 and owner/repo#15\n", "py") == 4


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        ("# see https://example.com/page#123 for more", 0),
        ("# an entity &#39; is not a ref", 0),
        ("# hex #21262d and #fff", 0),
        ("# too long #123456", 0),
        ("# word#1234 glued", 1),
        ("# (#411)", 1),
        ("# ##12 double hash", 0),
        ("# #12, #13.", 2),
    ],
)
def test_reference_shape(comment: str, expected: int) -> None:
    assert count(comment + "\n", "py") == expected


def test_a_reference_in_a_url_does_not_hide_a_later_one() -> None:
    assert count("# https://example.com/#12 and #13\n", "py") == 1


def test_unparseable_python_is_not_confirmed() -> None:
    with pytest.raises(cr.NotConfirmed):
        cr.scan_text('x = """never closed\n# #12\n', "py")


# -------------------------------------------------------------------- counting: JS

def test_js_line_and_block_comments_count() -> None:
    src = "const a = 1; // since #10\n/* multi\n   line #11 */\nconst b = 2;\n"
    assert [r.line for r in cr.scan_text(src, "js")] == [1, 3]


def test_js_strings_templates_and_regex_literals_do_not_count() -> None:
    src = (
        "const a = 'see // #1';\n"
        'const b = "see /* #2 */";\n'
        "const c = `tpl // #3 ${ 'x' } #4 /* #5 */`;\n"
        "const d = `outer ${ `inner #6` } #7`;\n"
        "const e = /\\/\\/ #8/.test(s);\n"
        "const f = /[/]#9/.test(s);\n"
    )
    assert count(src, "js") == 0


def test_js_comment_after_a_template_substitution_still_counts() -> None:
    src = "const a = `x ${ y } z`; // #20\nconst b = `${ { k: 1 }.k }`; // #21\n"
    assert [r.line for r in cr.scan_text(src, "js")] == [1, 2]


def test_js_division_is_not_a_regex() -> None:
    src = "const a = b / c; // #30\nconst d = e / f / g; // #31\nlet i = 0; i++ / 2; // #32\n"
    assert count(src, "js") == 3


def test_js_regex_after_a_keyword_or_operator() -> None:
    src = "if (x) { return /'/.test(s); } // #40\nconst r = a || /\"/.test(s); // #41\n"
    assert count(src, "js") == 2


def test_js_regex_directly_after_a_paren_reads_as_division() -> None:
    # The documented blind spot: `if (x) /re/.test(y)`. A benign case keeps its count...
    assert count("if (x) /re/.test(y); // #50\n", "js") == 1
    # ...and the realistic failure is exit 3, never a wrong count.
    with pytest.raises(cr.NotConfirmed):
        cr.scan_text("if (x) /'/.test(y); // #51\n", "js")


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("const a = 'never closed;\n// #1\n", id="string"),
        pytest.param("const a = `never closed ${ 1 }\n// #1\n", id="template"),
        pytest.param("/* never closed\n#1\n", id="block-comment"),
        pytest.param("const a = /never closed;\n// #1\n", id="regex"),
    ],
)
def test_unterminated_js_is_not_confirmed(src: str) -> None:
    with pytest.raises(cr.NotConfirmed):
        cr.scan_text(src, "js")


def test_js_string_line_continuation_keeps_line_numbers() -> None:
    src = "const a = 'one \\\ntwo';\n// #60\n"
    assert [r.line for r in cr.scan_text(src, "js")] == [3]


# ------------------------------------------------------------------- counting: CSS

def test_css_comments_count_and_declarations_do_not() -> None:
    src = (
        "/* since #70 */\n"
        ".a { color: #fff; background: #21262d; }\n"
        "#main { content: '/* #71 */'; }\n"
        ".b { background: url(a/*#72*/b.png); }\n"
        '.c { background: url("x/*#73*/.png"); }\n'
        "/* two\n   #74 */\n"
    )
    assert [r.line for r in cr.scan_text(src, "css")] == [1, 7]


def test_css_digit_only_hex_colour_in_a_comment_is_the_documented_false_positive() -> None:
    assert count("/* grey #333 */\n", "css") == 1
    assert count(".a { color: #333; }\n", "css") == 0  # a declaration never counts


@pytest.mark.parametrize("src", ["/* never closed\n#1\n", ".a { content: 'open;\n}\n"])
def test_unterminated_css_is_not_confirmed(src: str) -> None:
    with pytest.raises(cr.NotConfirmed):
        cr.scan_text(src, "css")


# ------------------------------------------------------------- counting: PowerShell

def test_powershell_line_and_block_comments_count() -> None:
    src = "$a = 1  # since #80\n<# block\n   #81 #>\nGet-Item x ; # #82\n"
    assert [r.line for r in cr.scan_text(src, "ps")] == [1, 3, 4]


def test_powershell_strings_and_here_strings_do_not_count() -> None:
    src = (
        "$a = 'see #90'\n"
        "$b = 'it''s #91'\n"
        '$c = "see #92 and `" #93"\n'
        '$d = "x $(Get-Date) #94"\n'
        "$e = @'\n# #95\n'@\n"
        '$f = @"\n# #96 $x\n"@\n'
        "$g = $x#97\n"
        "${odd#98name} = 1\n"
    )
    assert count(src, "ps") == 0


def test_powershell_comment_inside_a_subexpression_counts() -> None:
    src = '$a = "start $(\n  Get-Date # real #99\n) end #100"\n'
    assert [r.line for r in cr.scan_text(src, "ps")] == [2]


def test_powershell_comment_after_a_string_still_counts() -> None:
    assert count("$a = 'x'  # #110\n$b = \"y\" # #111\n", "ps") == 2


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("$a = 'never closed\n# #1\n", id="single-quoted"),
        pytest.param('$a = "never closed\n# #1\n', id="double-quoted"),
        pytest.param("$a = @'\nnever closed\n# #1\n", id="here-string"),
        pytest.param("<# never closed\n#1\n", id="block-comment"),
    ],
)
def test_unterminated_powershell_is_not_confirmed(src: str) -> None:
    with pytest.raises(cr.NotConfirmed):
        cr.scan_text(src, "ps")


# ------------------------------------------------------------------- counting: YAML

def test_yaml_line_comments_count() -> None:
    src = "# since #120\nname: ci  # trailing #121\nkey: value\n"
    assert [r.line for r in cr.scan_text(src, "yaml")] == [1, 2]


def test_yaml_requires_whitespace_or_line_start_before_hash() -> None:
    # `a#130` is a plain scalar (no comment); `a #131` is a comment (project-scaffolding#500).
    assert count("key: a#130\n", "yaml") == 0
    assert count("key: a #131\n", "yaml") == 1


def test_yaml_quoted_scalars_do_not_count() -> None:
    src = (
        "a: 'see #140'\n"
        "b: 'it''s #141'\n"
        'c: "see #142"\n'
        'd: "escaped \\" still open #143"\n'
    )
    assert count(src, "yaml") == 0


@pytest.mark.parametrize(
    "src",
    [
        "description: the customer's first store\n",
        "description: a \"quoted\" word and it's fine\n",
        "- the customer's store\n",
        "key: [the customer's store, other]\n",
        "key: {a: it's}\n",
        "description: >\n  the customer's first store\n  and the shop's neighbour\n",
    ],
)
def test_yaml_quote_inside_a_plain_scalar_is_not_a_quoted_scalar(src: str) -> None:
    # An apostrophe or double quote mid-value is a plain-scalar character, so it must
    # neither raise NotConfirmed nor swallow a following comment.
    cr.scan_text(src, "yaml")
    assert count(src + "key: v # real #151\n", "yaml") == 1


@pytest.mark.parametrize(
    "src",
    [
        "a: 'see #160'\n",
        "- 'see #161'\n",
        "? 'see #162'\n: v\n",
        "'k #163': v\n",
        "a: !!str 'see #164'\n",
        "a: &anchor 'see #165'\n",
        "a: ['see #166', 'b']\n",
        "a: {k: 'see #167'}\n",
        "a:\n  'see #168'\n",
        "a: 'it''s #169'\n",
    ],
)
def test_yaml_quoted_scalar_at_a_value_start_still_hides_a_hash(src: str) -> None:
    assert count(src, "yaml") == 0


@pytest.mark.parametrize("src", ["a: 'never closed\n#1\n", 'a: "never closed\n#1\n', "- 'never closed\n#1\n"])
def test_unterminated_yaml_scalar_is_not_confirmed(src: str) -> None:
    with pytest.raises(cr.NotConfirmed):
        cr.scan_text(src, "yaml")


# ------------------------------------------------------------------- scope

@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/a.py", True),
        ("app/webapp/static/app.js", True),
        ("app/webapp/static/app.css", True),
        ("scripts/x.ps1", True),
        (".github/workflows/ci.yml", True),
        ("config/x.yaml", True),
        (".github/workflows/ci.yml.template", True),  # project-scaffolding#500
        (".github/workflows/ci.yaml.template", True),
        ("README.md", False),
        ("data/x.json", False),
        ("tray.bat.template", False),
        ("tests/test_a.py", False),
        ("tests/e2e/helper.py", False),
        ("src/test_thing.py", False),
        ("src/thing_test.py", False),
        ("src/conftest.py", False),
        ("web/a.test.js", False),
        ("web/a.min.js", False),
        ("web/node_modules/x/y.js", False),
        ("app/webapp/static/_vendored/nav/nav-tabs.js", True),  # excluded only via [vendored]
    ],
)
def test_default_scope(path: str, expected: bool) -> None:
    assert cr.in_scope(path, cr.Config(cr.DEFAULT_BASELINE, (), ()), ()) is expected


def test_include_exclude_and_vendored_narrow_the_scope() -> None:
    cfg = cr.Config(cr.DEFAULT_BASELINE, ("app/",), ("**/gen/**",))
    vendored = ("app/vendored", "app/single.py")
    assert cr.in_scope("app/a.py", cfg, vendored)
    assert not cr.in_scope("src/a.py", cfg, vendored)
    assert not cr.in_scope("app/gen/a.py", cfg, vendored)
    assert not cr.in_scope("app/vendored/a.js", cfg, vendored)
    assert not cr.in_scope("app/single.py", cfg, vendored)
    assert cr.in_scope("app/vendored_other/a.js", cfg, vendored)


def test_generated_marker_in_the_first_lines() -> None:
    assert cr.is_generated("# DO NOT EDIT\nx = 1\n")
    assert cr.is_generated("// @generated by tool\n")
    assert not cr.is_generated("\n" * 10 + "# DO NOT EDIT\n")
    # Prose in a vendored file's header ("Do NOT edit this file per-app") is not a generated marker.
    assert not cr.is_generated("/* VENDORED VERBATIM. Do NOT edit this file per-app\n")
    assert not cr.is_generated('"""CANONICAL. Do **not** edit this file per-app\n')


# ------------------------------------------------------- ratchet on a git repo

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the stage enabled and one reference in `src/a.py`."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text("[comment_ratchet]\nenabled = true\n", encoding="utf-8")
    write(tmp_path, "src/a.py", "x = 1  # since #1\n")
    return tmp_path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return cr.run(root, init=init, update=update, allow_additions=allow)


def baseline_text(root: Path) -> str:
    return (root / cr.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_init_writes_a_per_file_baseline_and_never_overwrites(repo: Path) -> None:
    write(repo, "app/b.js", "// a #2 and #3\n")
    assert run_mode(repo, init=True) == cr.EXIT_PASS
    assert baseline_text(repo) == (
        '{\n  "version": 1,\n  "entries": [\n'
        '    {"key": "app/b.js", "count": 2},\n    {"key": "src/a.py", "count": 1}\n  ]\n}\n'
    )
    assert run_mode(repo, init=True) == cr.EXIT_CONFIG


def test_unchanged_tree_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    assert run_mode(repo) == cr.EXIT_PASS
    assert "PASS" in capsys.readouterr().out


def test_a_new_reference_fails_and_names_file_and_counts(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "src/a.py", "x = 1  # since #1\ny = 2  # because #2\n")
    assert run_mode(repo) == cr.EXIT_RISE
    out = capsys.readouterr().out
    assert "src/a.py: 2 (baseline 1)" in out
    assert "line 2: #2" in out


def test_a_new_file_with_a_reference_fails_even_if_another_file_shrank(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "src/a.py", "x = 1\n")  # one removed here...
    write(repo, "src/b.py", "y = 1  # #5\n")  # ...cannot pay for one added there
    assert run_mode(repo) == cr.EXIT_RISE
    assert "src/b.py: 1 (baseline none" in capsys.readouterr().out


def test_a_new_file_without_references_passes(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/b.py", "y = 1  # a present-tense why\n")
    assert run_mode(repo) == cr.EXIT_PASS


def test_a_removed_reference_passes_with_a_shrink_hint(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "src/a.py", "x = 1\n")
    assert run_mode(repo) == cr.EXIT_PASS
    assert "--update-baseline" in capsys.readouterr().out


def test_update_baseline_lowers_and_drops(repo: Path) -> None:
    write(repo, "src/b.py", "y = 1  # #5 #6\n")
    run_mode(repo, init=True)
    write(repo, "src/a.py", "x = 1\n")
    write(repo, "src/b.py", "y = 1  # #5\n")
    assert run_mode(repo, update=True) == cr.EXIT_PASS
    assert baseline_text(repo).count('"key"') == 1
    assert '{"key": "src/b.py", "count": 1}' in baseline_text(repo)


def test_update_baseline_refuses_a_rise_and_writes_nothing(repo: Path) -> None:
    run_mode(repo, init=True)
    before = baseline_text(repo)
    write(repo, "src/a.py", "x = 1  # #1 #2\n")
    assert run_mode(repo, update=True) == cr.EXIT_RISE
    assert baseline_text(repo) == before


def test_allow_additions_raises_the_baseline(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/a.py", "x = 1  # #1 #2\n")
    write(repo, "src/b.py", "y = 1  # #3\n")
    assert run_mode(repo, update=True, allow=True) == cr.EXIT_PASS
    assert run_mode(repo) == cr.EXIT_PASS
    assert '{"key": "src/a.py", "count": 2}' in baseline_text(repo)
    assert '{"key": "src/b.py", "count": 1}' in baseline_text(repo)


def test_missing_baseline_fails_instead_of_passing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo) == cr.EXIT_RISE
    assert "--init" in capsys.readouterr().out


@pytest.mark.parametrize("text", ["not json", "[]", '{"version": 2, "entries": []}', '{"version": 1, "entries": [{"key": "a"}]}',
                                  '{"version": 1, "entries": [{"key": "a", "count": 0}]}'])
def test_unreadable_baseline_exits_two(repo: Path, text: str) -> None:
    (repo / cr.DEFAULT_BASELINE).write_text(text, encoding="utf-8")
    assert run_mode(repo) == cr.EXIT_CONFIG


def test_disabled_or_absent_stage_exits_zero_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path) == cr.EXIT_PASS  # no git needed: nothing is inferred
    assert "not enabled" in capsys.readouterr().out
    assert run_mode(tmp_path, init=True) == cr.EXIT_CONFIG
    assert run_mode(tmp_path, update=True) == cr.EXIT_CONFIG


def test_malformed_table_or_toml_exits_two(tmp_path: Path) -> None:
    (tmp_path / ".fleet.toml").write_text("[comment_ratchet]\nenabled = true\nbogus = 1\n", encoding="utf-8")
    assert run_mode(tmp_path) == cr.EXIT_CONFIG
    (tmp_path / ".fleet.toml").write_text("[comment_ratchet\n", encoding="utf-8")
    assert run_mode(tmp_path) == cr.EXIT_CONFIG
    (tmp_path / ".fleet.toml").unlink()
    assert run_mode(tmp_path) == cr.EXIT_CONFIG


def test_tests_vendored_generated_and_other_files_are_not_counted(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(
        '[comment_ratchet]\nenabled = true\n[vendored]\nnav = { src = "x", sha = "1", dest = "app/_vendored/nav" }\n',
        encoding="utf-8",
    )
    write(repo, "tests/test_a.py", "# #1\n")
    write(repo, "src/thing_test.py", "# #1\n")
    write(repo, "app/_vendored/nav/nav.js", "// #1\n")
    write(repo, "src/gen.py", "# DO NOT EDIT\n# #1\n")
    write(repo, "docs/notes.md", "# heading #1\n")
    write(repo, "src/string.py", 'x = "#1"\n')
    assert run_mode(repo, init=True) == cr.EXIT_PASS
    assert baseline_text(repo).count('"key"') == 1  # only src/a.py


def test_include_limits_the_tree(repo: Path) -> None:
    (repo / ".fleet.toml").write_text('[comment_ratchet]\nenabled = true\ninclude = ["app/"]\n', encoding="utf-8")
    write(repo, "app/b.py", "# #2\n")
    run_mode(repo, init=True)
    assert baseline_text(repo).count('"key"') == 1
    assert '"app/b.py"' in baseline_text(repo)


def test_crlf_and_bom_files_are_counted_like_lf(repo: Path) -> None:
    (repo / "src" / "crlf.ps1").write_bytes(b"\xef\xbb\xbf$a = 1 # #1\r\n<# x\r\n#2 #>\r\n")
    git(repo, "add", "src/crlf.ps1")
    run_mode(repo, init=True)
    assert '{"key": "src/crlf.ps1", "count": 2}' in baseline_text(repo)


def test_a_tracked_file_deleted_from_the_tree_is_skipped(repo: Path) -> None:
    run_mode(repo, init=True)
    (repo / "src" / "a.py").unlink()
    assert run_mode(repo) == cr.EXIT_PASS


@pytest.mark.parametrize(
    ("rel", "body", "says"),
    [
        pytest.param("web/app.js", b"const a = 'never closed;\n// #1\n", "unterminated", id="unterminated-js-string"),
        pytest.param("web/app.css", b"/* never closed\n", "unterminated", id="unterminated-css-comment"),
        pytest.param("src/bad.py", b'x = """never closed\n', "python tokenizer rejected the file", id="unparseable-python"),
        pytest.param("scripts/x.ps1", b"$a = @'\nnever closed\n", "unterminated", id="unterminated-here-string"),
        pytest.param("src/latin.py", b"# caf\xe9 #1\n", "is not valid UTF-8", id="not-utf8"),
    ],
)
def test_a_file_the_scanner_cannot_finish_is_not_confirmed_in_every_mode(
    repo: Path, rel: str, body: bytes, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_unreadable_file_not_confirmed(cr, run_mode, repo, rel, body, says, capsys)


test_git_that_cannot_list_the_tree_is_not_confirmed = git_failure_test(cr, run_mode)


def test_main_rejects_allow_additions_without_update(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cr.main(["--allow-additions"])
    assert exc.value.code == 2
    assert "--allow-additions" in capsys.readouterr().err


# --------------------------------------------- docstring references and history phrases

DOC_CFG = cr.Config(cr.DEFAULT_BASELINE, (), (), docstrings=True)
HIST_CFG = cr.Config(cr.DEFAULT_BASELINE, (), (), history_phrases=True)
BOTH_CFG = cr.Config(cr.DEFAULT_BASELINE, (), (), docstrings=True, history_phrases=True)


def scan(text: str, language: str, cfg: cr.Config) -> dict[str, int]:
    return {key: len(refs) for key, refs in cr.scan_file(text, language, cfg).items()}


def test_new_rules_are_off_unless_the_adopter_opts_in() -> None:
    cfg = cr.parse_config("[comment_ratchet]\nenabled = true\n")
    assert cfg is not None and not cfg.docstrings and not cfg.history_phrases
    src = 'def f():\n    """Fixed in #12. It used to be slow."""\n'
    assert scan(src, "py", cfg) == {}


def test_config_reads_the_two_flags_and_rejects_non_booleans() -> None:
    cfg = cr.parse_config("[comment_ratchet]\nenabled = true\ndocstrings = true\nhistory_phrases = true\n")
    assert cfg is not None and cfg.docstrings and cfg.history_phrases
    for body in ('docstrings = "yes"\n', "history_phrases = 1\n"):
        with pytest.raises(cr.ConfigError):
            cr.parse_config("[comment_ratchet]\nenabled = true\n" + body)


def test_docstring_refs_are_counted_in_module_class_function_and_async_docstrings() -> None:
    src = (
        '"""Module story (#10)."""\n'
        "class C:\n"
        '    """Class story #11."""\n'
        "    def m(self) -> None:\n"
        '        """Method story #12 and repo#13."""\n'
        "async def f() -> None:\n"
        '    """Async story #14."""\n'
    )
    refs = cr.scan_file(src, "py", DOC_CFG)[cr.DOCSTRING_SUFFIX]
    assert [r.line for r in refs] == [1, 3, 5, 5, 7]


def test_docstring_rule_counts_only_docstrings_never_plain_strings_or_comments() -> None:
    src = (
        'x = "see #20"\n'
        "y = 1  # since #21\n"
        "def f() -> str:\n"
        '    s = """not a docstring #22"""\n'
        "    return s\n"
    )
    found = cr.scan_file(src, "py", DOC_CFG)
    assert cr.DOCSTRING_SUFFIX not in found
    assert [r.line for r in found[""]] == [2]  # the comment rule keeps its own key


@pytest.mark.parametrize(
    ("doc", "expected"),
    [
        ("step #1 of the flow", 1),  # a single digit counts: the stricter of the two local forks
        ("an entity &#39; and ##12", 0),
        ("see https://example.com/page#123", 0),
        ("number #123456", 0),
        ("#12, #13 and owner/repo#14", 3),
    ],
)
def test_docstring_reference_shape_matches_the_comment_rule(doc: str, expected: int) -> None:
    src = f'def f() -> None:\n    """{doc}"""\n'
    assert scan(src, "py", DOC_CFG).get(cr.DOCSTRING_SUFFIX, 0) == expected


def test_docstring_rule_ignores_non_python_files() -> None:
    assert scan("/** since #12 */\nconst a = 1;\n", "js", DOC_CFG) == {"": 1}


def test_unparseable_python_is_not_confirmed_when_docstrings_are_on() -> None:
    with pytest.raises(cr.NotConfirmed):
        cr.scan_file("def f(:\n", "py", DOC_CFG)


@pytest.mark.parametrize(
    "phrase",
    ["used to be", "formerly", "extracted verbatim", "pure code move", "previously recorded", "had drifted"],
)
def test_each_curated_phrase_counts_in_a_comment_and_a_docstring(phrase: str) -> None:
    assert scan(f"x = 1  # this {phrase} elsewhere\n", "py", HIST_CFG) == {cr.HISTORY_SUFFIX: 1}
    assert scan(f'def f() -> None:\n    """This {phrase.upper()} elsewhere."""\n', "py", HIST_CFG) == {cr.HISTORY_SUFFIX: 1}


def test_history_phrases_count_in_js_css_powershell_and_yaml_comments() -> None:
    assert scan("// it used to be a table\n", "js", HIST_CFG) == {cr.HISTORY_SUFFIX: 1}
    assert scan("/* extracted verbatim from base.css */\n", "css", HIST_CFG) == {cr.HISTORY_SUFFIX: 1}
    assert scan("# pure code move\n", "ps", HIST_CFG) == {cr.HISTORY_SUFFIX: 1}
    assert scan("# had drifted\n", "yaml", HIST_CFG) == {cr.HISTORY_SUFFIX: 1}


def test_history_phrases_in_code_strings_and_ordinary_prose_do_not_count() -> None:
    src = (
        'MARKERS = ["used to be", "had drifted"]\n'
        'print("formerly known as x")\n'
        "x = 1  # a present-tense why: it is used to bound the retry loop\n"
        "z = 3  # words like unformerly or reused tobe never match a whole phrase\n"
    )
    assert scan(src, "py", HIST_CFG) == {}


def test_a_docstring_phrase_wrapped_over_two_lines_still_counts() -> None:
    assert scan('"""It used\n  to be a loop."""\n', "py", HIST_CFG) == {cr.HISTORY_SUFFIX: 1}


def test_a_phrase_wrapped_over_two_comment_lines_is_the_documented_blind_spot() -> None:
    assert scan("# it used to\n# be a loop\n", "py", HIST_CFG) == {}


def test_both_new_rules_and_the_comment_rule_keep_separate_counts() -> None:
    src = (
        '"""Fixed in #12; it used to be slow."""\n'
        "x = 1  # see #13 and note it had drifted\n"
    )
    found = cr.scan_file(src, "py", BOTH_CFG)
    assert {k: len(v) for k, v in found.items()} == {"": 1, cr.DOCSTRING_SUFFIX: 1, cr.HISTORY_SUFFIX: 2}
    assert [r.line for r in found[cr.HISTORY_SUFFIX]] == [1, 2]


def test_parsing_an_adopters_file_never_leaks_its_syntax_warnings() -> None:
    src = 'import re\nPAT = re.compile("\\d+")\n'  # an invalid escape in the adopter's source, not ours to report
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert scan(src, "py", DOC_CFG) == {}


@pytest.fixture
def repo_new_rules(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(
        "[comment_ratchet]\nenabled = true\ndocstrings = true\nhistory_phrases = true\n", encoding="utf-8"
    )
    write(tmp_path, "src/a.py", 'def f() -> None:\n    """Story #5; it used to be slow."""\n')
    return tmp_path


def test_init_writes_suffixed_keys_per_rule(repo_new_rules: Path) -> None:
    assert run_mode(repo_new_rules, init=True) == cr.EXIT_PASS
    assert baseline_text(repo_new_rules) == (
        '{\n  "version": 1,\n  "entries": [\n'
        '    {"key": "src/a.py::docstring", "count": 1},\n    {"key": "src/a.py::history", "count": 1}\n  ]\n}\n'
    )


def test_a_new_docstring_ref_fails_and_names_the_rule(repo_new_rules: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo_new_rules, init=True)
    write(repo_new_rules, "src/a.py", 'def f() -> None:\n    """Story #5 and #6; it used to be slow."""\n')
    assert run_mode(repo_new_rules) == cr.EXIT_RISE
    out = capsys.readouterr().out
    assert "src/a.py::docstring: 2 (baseline 1)" in out
    assert "src/a.py::history" not in out


def test_a_new_history_phrase_fails_even_when_a_docstring_ref_was_removed(
    repo_new_rules: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    run_mode(repo_new_rules, init=True)
    write(repo_new_rules, "src/a.py", 'def f() -> None:\n    """It used to be slow; it had drifted."""\n')
    assert run_mode(repo_new_rules) == cr.EXIT_RISE  # one ref removed cannot pay for one phrase added
    assert "src/a.py::history: 2 (baseline 1)" in capsys.readouterr().out


def test_rewording_lowers_the_new_rule_baselines(repo_new_rules: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo_new_rules, init=True)
    write(repo_new_rules, "src/a.py", 'def f() -> None:\n    """Fast path."""\n')
    assert run_mode(repo_new_rules) == cr.EXIT_PASS
    assert "--update-baseline" in capsys.readouterr().out
    assert run_mode(repo_new_rules, update=True) == cr.EXIT_PASS
    assert baseline_text(repo_new_rules).count('"key"') == 0


def test_a_baseline_written_before_the_new_rules_still_passes_with_them_off(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/b.py", 'def f() -> None:\n    """Story #5; it used to be slow."""\n')
    assert run_mode(repo) == cr.EXIT_PASS  # the flags are opt-in: re-vendoring changes nothing


def test_enabling_a_rule_on_an_existing_baseline_demands_baselining_its_debt(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/b.py", 'def f() -> None:\n    """Story #5."""\n')
    (repo / ".fleet.toml").write_text("[comment_ratchet]\nenabled = true\ndocstrings = true\n", encoding="utf-8")
    assert run_mode(repo) == cr.EXIT_RISE
    assert run_mode(repo, update=True, allow=True) == cr.EXIT_PASS
    assert run_mode(repo) == cr.EXIT_PASS


def test_unparseable_python_is_not_confirmed_for_the_new_rules(repo_new_rules: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert_unreadable_file_not_confirmed(cr, run_mode, repo_new_rules, "src/bad.py", b"def f(:\n", "rejected the file", capsys)


# ------------------------------------------- shared history patterns and per-repo extras

@pytest.mark.parametrize(
    "narration",
    [
        pytest.param("see epic §4.2 for the split", id="epic-section"),
        pytest.param("the step-6 decision keeps one queue", id="step-n-decision"),
        pytest.param("the limit was chosen in step 3", id="decided-in-step"),
        pytest.param("each used to carry its own copy", id="each-used-to"),
        pytest.param("the menu surface (owner's decision 2026-10-13): one elevation", id="decision-then-date"),
        pytest.param("2026-10-13: owner decided on one elevation", id="date-then-decision"),
    ],
)
def test_each_shared_history_pattern_counts_in_a_comment_and_a_docstring(narration: str) -> None:
    assert scan(f"x = 1  # {narration}\n", "py", HIST_CFG) == {cr.HISTORY_SUFFIX: 1}
    assert scan(f'def f() -> None:\n    """{narration.upper()}."""\n', "py", HIST_CFG) == {cr.HISTORY_SUFFIX: 1}
    assert scan(f"/* {narration} */\n", "css", HIST_CFG) == {cr.HISTORY_SUFFIX: 1}


@pytest.mark.parametrize(
    "prose",
    [
        pytest.param("Step 1: fetch the page, then parse it", id="procedural-step"),
        pytest.param("phase 2 of the moon drives the tide table", id="domain-phase"),
        pytest.param("per YAML 1.2 §7.3.3 a plain scalar ends here", id="spec-section"),
        pytest.param("bind the Cloudflare D1 database", id="private-id-shape"),
        pytest.param("run with --since 2026-01-01 to backfill", id="cli-date"),
        pytest.param("the decision table is keyed by user, and rows written on 2026-01-01 are migrated", id="date-far"),
    ],
)
def test_broad_shapes_the_sweep_rejected_never_count(prose: str) -> None:
    assert scan(f"x = 1  # {prose}\n", "py", HIST_CFG) == {}


def test_extra_patterns_are_compiled_case_insensitively_and_need_history_phrases() -> None:
    cfg = cr.parse_config(
        '[comment_ratchet]\nenabled = true\nhistory_phrases = true\nextra_history_patterns = ["\\\\bstep \\\\d+\\\\b"]\n'
    )
    assert cfg is not None and [p.pattern for p in cfg.extra_history_patterns] == [r"\bstep \d+\b"]
    assert cfg.extra_history_patterns[0].search("STEP 4")
    with pytest.raises(cr.ConfigError, match="needs history_phrases"):
        cr.parse_config('[comment_ratchet]\nenabled = true\nextra_history_patterns = ["x"]\n')
    for bad in ('extra_history_patterns = "x"\n', 'extra_history_patterns = [""]\n', 'extra_history_patterns = ["a*"]\n'):
        with pytest.raises(cr.ConfigError):
            cr.parse_config("[comment_ratchet]\nenabled = true\nhistory_phrases = true\n" + bad)


def test_a_repo_local_pattern_counts_under_the_history_key() -> None:
    cfg = cr.Config(cr.DEFAULT_BASELINE, (), (), history_phrases=True,
                    extra_history_patterns=(re.compile(r"\bD\d+\b", re.IGNORECASE),))
    src = 'x = 1  # per D7 we keep two queues\ndef f() -> None:\n    """Settled by d12."""\n'
    assert [r.line for r in cr.scan_file(src, "py", cfg)[cr.HISTORY_SUFFIX]] == [1, 3]
    assert scan(src, "py", HIST_CFG) == {}  # without the extra, the shared rule leaves the repo's ids alone


def test_a_repo_pattern_overlapping_a_shared_phrase_counts_once() -> None:
    cfg = cr.Config(cr.DEFAULT_BASELINE, (), (), history_phrases=True,
                    extra_history_patterns=(re.compile(r"used to", re.IGNORECASE),))
    assert scan("x = 1  # it used to be slow\n", "py", cfg) == {cr.HISTORY_SUFFIX: 1}


def test_an_invalid_extra_pattern_is_not_confirmed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(
        '[comment_ratchet]\nenabled = true\nhistory_phrases = true\nextra_history_patterns = ["step (\\\\d+"]\n',
        encoding="utf-8",
    )
    write(tmp_path, "src/a.py", "x = 1\n")
    assert run_mode(tmp_path, init=True) == cr.EXIT_NOT_CONFIRMED
    out = capsys.readouterr().out
    assert "NOT CONFIRMED" in out and "extra_history_patterns[0]" in out
    assert not (tmp_path / cr.DEFAULT_BASELINE).exists()


def test_a_repo_local_pattern_hit_fails_the_ratchet(repo_new_rules: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo_new_rules, init=True)
    (repo_new_rules / ".fleet.toml").write_text(
        "[comment_ratchet]\nenabled = true\ndocstrings = true\nhistory_phrases = true\n"
        'extra_history_patterns = ["\\\\bstep \\\\d+\\\\b"]\n',
        encoding="utf-8",
    )
    write(repo_new_rules, "src/b.py", "x = 1  # done in step 4\n")
    assert run_mode(repo_new_rules) == cr.EXIT_RISE
    assert "src/b.py::history: 1 (baseline none" in capsys.readouterr().out


# ------------------------------------------------------------ self-adoption

def test_scaffold_adopts_the_stage_and_commits_a_parseable_baseline() -> None:
    cfg, _ = cr.load_config(REPO_ROOT)
    assert cfg is not None, "the scaffold adopts its own stage first (#411)"
    assert (REPO_ROOT / cfg.baseline).is_file()
    cr.read_baseline(REPO_ROOT / cfg.baseline)


def test_gate_runs_the_stage_between_ruff_and_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    ruff, stage, mypy = (text.index(s) for s in ('Invoke-Stage "ruff"', 'Invoke-Stage "comment ratchet"', 'Invoke-Stage "mypy'))
    assert ruff < stage < mypy
    assert "scripts/comment_ratchet.py" in text


def test_the_script_is_catalogued_so_it_is_mypy_gated_and_drift_checked() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["comment_ratchet"] == {"src": "scripts/comment_ratchet.py"}


def test_an_untracked_file_with_a_violation_fails(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/b.py", 'y = 1  # #5\n', track=False)
    assert run_mode(repo) == cr.EXIT_RISE


def test_an_ignored_file_is_still_skipped(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, ".gitignore", "src/ignored.py\n")
    write(repo, "src/ignored.py", 'y = 1  # #5\n', track=False)
    assert run_mode(repo) == cr.EXIT_PASS
