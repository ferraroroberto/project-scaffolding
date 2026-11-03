"""Tests for the usage track ratchet.

Three layers, mirroring `test_conventions_ratchet.py`:

1. **Rules** on fixture sources: each rule fails by name on a seeded violation
   and passes on the compliant form, in HTML, in a JS string or template, and
   from `createElement`, plus the scoping each rule relies on (tracked parents,
   nav tabs, builders, module constants, exempt markers).
2. **Ratchet behaviour** on throwaway git repos: a fixture app missing ids fails
   and passes once they are added, every mode, the never-baselined wiring rule,
   and the "not confirmed" exit for anything that cannot be read through. A
   missing prerequisite is a hard failure, never `pytest.skip`.
3. **Self-adoption** -- this repo's own declaration and gate wiring.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import usage_track_ratchet as ut
from src.no_window import NO_WINDOW
from tests._git_repo import git, write
from tests._ratchet_not_confirmed import (
    GIT_FAILURES,
    assert_unlistable_git_not_confirmed,
    assert_unreadable_file_not_confirmed,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
ALL = ut.Config(ut.DEFAULT_BASELINE, ut.RULES)


def hits(src: str, path: str = "app/webapp/static/index.html", cfg: ut.Config = ALL) -> list[str]:
    """`rule:line` of every hit in one in-memory file."""
    found, _ = ut.scan_source(src, path, cfg)
    return [f"{h.rule}:{h.line}" for h in found]


def js(src: str, cfg: ut.Config = ALL, path: str = "app/webapp/static/app.js") -> list[str]:
    return hits(src, path, cfg)


# ------------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert ut.parse_config('layer = "x"\n') is None
    assert ut.parse_config("[usage_track_ratchet]\nenabled = false\n") is None
    assert ut.parse_config("[usage_track_ratchet]\n") is None  # opting in is explicit


def test_enabled_table_keeps_rule_order_and_defaults() -> None:
    cfg = ut.parse_config('[usage_track_ratchet]\nenabled = true\nrules = ["dynamic-id", "untracked-control"]\n')
    assert cfg == ut.Config(ut.DEFAULT_BASELINE, ("untracked-control", "dynamic-id"))
    assert cfg.paths == ("app/webapp/static/**", "app/webapp/templates/**")


def test_enabled_table_honours_every_key() -> None:
    cfg = ut.parse_config(
        '[usage_track_ratchet]\nenabled = true\nbaseline = "b.json"\nrules = ["untracked-sheet"]\n'
        'paths = ["web/**"]\nexclude = ["web/vendor/**"]\nbuilders = ["web/row.js:row"]\n'
    )
    assert cfg == ut.Config("b.json", ("untracked-sheet",), ("web/**",), ("web/vendor/**",), (("web/row.js", "row"),))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("enabled = true\nrules = ['dynamic-id']\nrule = []\n", id="typo-in-key"),
        pytest.param('enabled = "yes"\nrules = ["dynamic-id"]\n', id="enabled-not-bool"),
        pytest.param("enabled = true\n", id="no-rules"),
        pytest.param("enabled = true\nrules = ['untracked-button']\n", id="unknown-rule"),
        pytest.param("enabled = true\nrules = ['dynamic-id']\nbaseline = ''\n", id="empty-baseline"),
        pytest.param("enabled = true\nrules = ['dynamic-id']\npaths = []\n", id="no-paths"),
        pytest.param("enabled = true\nrules = ['dynamic-id']\nbuilders = ['row.js']\n", id="builder-without-name"),
        pytest.param("enabled = true\nrules = ['dynamic-id']\nbuilders = ['row.js:1x']\n", id="builder-bad-name"),
    ],
)
def test_malformed_table_fails_loud(body: str) -> None:
    with pytest.raises(ut.ConfigError):
        ut.parse_config("[usage_track_ratchet]\n" + body)


# --------------------------------------------------------- rules in HTML

@pytest.mark.parametrize(
    ("rule", "bad", "good"),
    [
        pytest.param("untracked-control", '<main>\n<button>Go</button>\n',
                     '<main>\n<button data-track="go">Go</button>\n', id="untracked-control"),
        pytest.param("untracked-sheet", '<main>\n<dialog id="d"></dialog>\n',
                     '<main>\n<dialog id="d" data-track-view="details"></dialog>\n', id="untracked-sheet"),
        pytest.param("dynamic-id", '<main>\n<button data-track="{{ item.name }}">x</button>\n',
                     '<main>\n<button data-track="item.open">x</button>\n', id="dynamic-id"),
    ],
)
def test_each_rule_fails_by_name_on_a_violation_and_passes_the_compliant_form(rule: str, bad: str, good: str) -> None:
    assert hits(bad) == [f"{rule}:2"]
    assert hits(good) == []


@pytest.mark.parametrize(
    "control",
    [
        pytest.param("<summary>More</summary>", id="summary"),
        pytest.param("<select><option>a</option></select>", id="select"),
        pytest.param('<input type="checkbox">', id="checkbox"),
        pytest.param('<input type="submit" value="Send">', id="submit"),
        pytest.param('<div role="tab">Tab</div>', id="role-tab"),
        pytest.param('<span role="switch"></span>', id="role-switch"),
        pytest.param('<a href="#">Open</a>', id="hash-link"),
        pytest.param('<a href="javascript:void(0)">Open</a>', id="script-link"),
    ],
)
def test_every_kind_of_control_is_held_to_the_rule(control: str) -> None:
    assert hits(control) == ["untracked-control:1"]


@pytest.mark.parametrize(
    "markup",
    [
        pytest.param('<a href="/docs">Docs</a>', id="navigation-link"),
        pytest.param('<input type="text" name="q">', id="text-input"),
        pytest.param("<p>Text <strong>only</strong></p>", id="passive-text"),
        pytest.param('<div class="page-foot">build abc</div>', id="page-foot"),
    ],
)
def test_navigation_links_inputs_and_passive_text_are_not_controls(markup: str) -> None:
    assert hits(markup) == []


def test_a_tracked_control_or_group_parent_covers_its_children() -> None:
    src = ('<div role="group" data-track="range">\n<button>Day</button>\n<button>Week</button>\n</div>\n'
           '<button data-track="refresh"><span>Refresh</span><svg></svg></button>\n')
    assert hits(src) == []


def test_a_tracked_plain_container_covers_nothing() -> None:
    assert hits('<main data-track="page">\n<button>Go</button>\n</main>\n') == ["untracked-control:2"]


def test_the_nearest_tracked_ancestor_decides() -> None:
    src = '<div role="toolbar" data-track="tools">\n<div data-track="row">\n<button>x</button>\n</div>\n</div>\n'
    assert hits(src) == ["untracked-control:3"], "the client resolves the plain row's id, not the toolbar's"


def test_a_nav_tab_is_a_view_not_a_tap() -> None:
    src = '<nav class="tabs">\n<button class="tab" data-tab="home">Home</button>\n<button>Theme</button>\n</nav>\n'
    assert hits(src) == ["untracked-control:3"]
    assert hits('<div><button data-tab="home">Home</button></div>') == ["untracked-control:1"]


def test_an_id_outside_the_pattern_is_not_a_constant() -> None:
    assert hits('<button data-track="open sheet">x</button>') == ["dynamic-id:1"]
    assert hits('<dialog data-track-view="">x</dialog>') == ["dynamic-id:1"]


def test_hit_lines_are_the_tags_own_lines_with_crlf_and_nested_markup() -> None:
    src = '<dialog>\r\n  <div>\r\n    <h2><svg><use href="#i"></use></svg> Title</h2>\r\n    <button>x</button>\r\n</dialog>\r\n'
    assert hits(src) == ["untracked-sheet:1", "untracked-control:4"]


def test_an_inline_script_is_read_as_js_on_its_own_lines() -> None:
    src = '<main>\n<script type="module">\nconst u = initUsageLog();\nu.trackView(tab);\n</script>\n'
    assert hits(src) == ["dynamic-id:4"]
    assert hits('<script type="application/json">{"x": "<button>"}</script>') == []
    assert hits('<script src="/app.js"></script>') == []


# ----------------------------------------------------------- rules in JS

def test_a_control_in_a_template_literal_needs_its_own_id() -> None:
    assert js("const a = `<button class=\"k\">Enter</button>`;\n") == ["untracked-control:1"]
    assert js("const a = `<button data-track=\"key.enter\">Enter</button>`;\n") == []
    assert js("const a = `\n  <div>\n    <button>${label}</button>`;\n") == ["untracked-control:3"]


def test_a_control_in_a_string_literal_reads_escaped_quotes() -> None:
    assert js("el.innerHTML = '<button data-track=\\\"mic\\\">Mic</button>';\n") == []
    assert js("el.innerHTML = '<button class=\"mic\">Mic</button>';\n") == ["untracked-control:1"]


def test_a_hole_in_an_id_is_dynamic() -> None:
    assert js("const a = `<button data-track=\"${id}\">x</button>`;\n") == ["dynamic-id:1"]


def test_a_created_control_is_tied_by_dataset_or_set_attribute_in_its_block() -> None:
    for tie in ("b.dataset.track = 'save';", "b.setAttribute('data-track', 'save');",
                "if (x) {\n    b.dataset.track = 'save';\n  }"):
        src = f"function f() {{\n  const b = document.createElement('button');\n  {tie}\n  return b;\n}}\n"
        assert js(src) == [], tie
    assert js("function f() {\n  const b = document.createElement('button');\n  return b;\n}\n") == [
        "untracked-control:2"]


def test_a_tie_in_another_function_does_not_count() -> None:
    src = ("function make() {\n  const b = document.createElement('button');\n  return b;\n}\n"
           "function use() {\n  const b = make();\n  b.dataset.track = 'x';\n}\n")
    assert js(src) == ["untracked-control:2"]


def test_a_created_element_is_a_control_only_by_tag_type_role_or_href() -> None:
    assert js("const i = document.createElement('input');\ni.type = 'text';\n") == []
    assert js("const i = document.createElement('input');\ni.type = 'checkbox';\n") == ["untracked-control:1"]
    assert js("const d = document.createElement('div');\nd.setAttribute('role', 'button');\n") == [
        "untracked-control:1"]
    assert js("const a = document.createElement('a');\na.href = '/docs';\n") == []
    assert js("const a = document.createElement('a');\na.href = '#';\n") == ["untracked-control:1"]
    assert js("parent.append(document.createElement('button'));\n") == ["untracked-control:1"]


def test_a_created_dialog_needs_a_view_id() -> None:
    assert js("const d = document.createElement('dialog');\ndocument.body.append(d);\n") == ["untracked-sheet:1"]
    assert js("const d = document.createElement('dialog');\nd.dataset.trackView = 'share';\n") == []


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        pytest.param("usage.track('upload.done');\n", [], id="literal"),
        pytest.param("const ID = 'upload.done';\nusage.track(ID);\n", [], id="module-const"),
        pytest.param("usage.track(`upload.done`);\n", [], id="plain-template"),
        pytest.param("function f(id) { usage.track(id); }\n", ["dynamic-id:1"], id="parameter"),
        pytest.param("function f() {\n  const ID = 'x';\n  usage.track(ID);\n}\n", ["dynamic-id:3"],
                     id="local-const"),
        pytest.param("usage.track('tap.' + kind);\n", ["dynamic-id:1"], id="concatenation"),
        pytest.param("usage.trackView(e.detail.tab);\n", ["dynamic-id:1"], id="property"),
        pytest.param("btn.dataset.track = IDS[state];\n", ["dynamic-id:1"], id="table-lookup"),
        pytest.param("btn.setAttribute('data-track', name);\n", ["dynamic-id:1"], id="set-attribute"),
        pytest.param("initNavTabs({ onChange: usage.trackView });\n", [], id="passed-by-reference"),
        pytest.param("placement.track();\n", [], id="another-api"),
    ],
)
def test_ids_are_literals_or_module_constants(src: str, expected: list[str]) -> None:
    assert js(src) == expected


BUILDER = ut.Config(ut.DEFAULT_BASELINE, ut.RULES, builders=(("app/webapp/static/row.js", "row"),))
ROW = ("export function row(opts = {}) {\n  const main = document.createElement('button');\n"
       "  if (opts.track) main.dataset.track = opts.track;\n  return main;\n}\n")


def test_a_declared_builder_is_tied_by_its_callers_track_key() -> None:
    assert js(ROW, BUILDER, "app/webapp/static/row.js") == [], "the builder's own body passes the id through"
    assert js("row({ label: 'Lights', track: 'lights.toggle' });\n", BUILDER) == []
    assert js("row({ label: 'Lights' });\n", BUILDER) == ["untracked-control:1"]
    assert js("row({ label: x, track: x.id });\n", BUILDER) == ["dynamic-id:1"]


def test_a_declared_builder_that_is_not_defined_is_a_config_error() -> None:
    with pytest.raises(ut.ConfigError, match="builder `row` is not defined"):
        ut.scan_source("export const x = 1;\n", "app/webapp/static/row.js", BUILDER)


def test_init_usage_log_is_seen_but_not_its_definition() -> None:
    assert ut.scan_source("const u = initUsageLog();\n", "app/webapp/static/app.js", ALL)[1] is True
    assert ut.scan_source("export function initUsageLog(opts) {}\n", "app/webapp/static/x.js", ALL)[1] is False


def test_comments_regexes_and_holes_never_confuse_the_scope() -> None:
    src = ("// <button>in a comment</button>\n/* { unbalanced in a comment */\nconst re = /[{]/;\n"
           "const t = `${ {a: 1}.a }`;\nfunction f() {\n  const b = document.createElement('button');\n"
           "  b.dataset.track = 'ok';\n}\n")
    assert js(src) == []


# ------------------------------------------------------------- exemptions

def test_a_reasoned_marker_exempts_one_hit_of_its_rule() -> None:
    assert hits("<!-- untracked-control-exempt: decorative copy button -->\n<button>Copy</button>\n") == []
    assert js("// dynamic-id-exempt: ids come from the fixed _TAP_IDS table\nbtn.dataset.track = IDS[s];\n") == []
    assert hits('<button>A</button> <!-- untracked-control-exempt: legacy -->\n<button>B</button>\n') == [
        "untracked-control:2"], "a marker covers its own line and the comment block above, nothing further"


def test_a_bare_marker_or_another_rules_marker_exempts_nothing() -> None:
    assert hits("<!-- untracked-control-exempt -->\n<button>Copy</button>\n") == ["untracked-control:2"]
    assert hits("<!-- untracked-sheet-exempt: wrong rule -->\n<button>Copy</button>\n") == [
        "untracked-control:2"]


# ------------------------------------------------------- not confirmed (JS)

@pytest.mark.parametrize(
    ("src", "says"),
    [
        pytest.param("const a = 'open;\n", "a string that never closes", id="string"),
        pytest.param("const a = `open ${x}\n", "a template literal that never closes", id="template"),
        pytest.param("const a = 1; /* open\n", "a `/*` comment that never closes", id="comment"),
        pytest.param("function f() {\n", "a `{` that never closes", id="open-brace"),
        pytest.param("}\n", "a `}` with no `{`", id="stray-brace"),
        pytest.param("const a = `${ f( `;\n", "never closes", id="hole"),
    ],
)
def test_js_that_does_not_close_is_not_confirmed(src: str, says: str) -> None:
    with pytest.raises(ut.NotConfirmed, match=re.escape(says)):
        ut.scan_source(src, "app/webapp/static/app.js", ALL)


# ------------------------------------------------------- ratchet on a git repo

FIXTURE_HTML = """<!doctype html>
<html><body>
<main class="app">
  <button id="refresh">Refresh</button>
  <dialog id="settings"><button value="cancel">Close</button></dialog>
</main>
<nav class="tabs"><button class="tab" data-tab="home">Home</button></nav>
<script type="module" src="/app.js"></script>
</body></html>
"""
FIXTURE_JS = """import { initUsageLog } from './_vendored/usage-log/usage-log.js';
const usage = initUsageLog();
export function addRow(list, label) {
  const b = document.createElement('button');
  b.textContent = label;
  list.append(b);
}
"""
FIXTURE_TABLE = '[usage_track_ratchet]\nenabled = true\nrules = ["untracked-control", "untracked-sheet", "dynamic-id"]\n'


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with one baselined untracked control."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(FIXTURE_TABLE, encoding="utf-8")
    write(tmp_path, "app/webapp/static/index.html", "<main>\n<button>Go</button>\n</main>\n")
    return tmp_path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return ut.run(root, init=init, update=update, allow_additions=allow)


def baseline_text(root: Path) -> str:
    return (root / ut.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_a_fixture_app_missing_ids_fails_then_passes_once_they_are_added(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(FIXTURE_TABLE, encoding="utf-8")
    (tmp_path / ut.DEFAULT_BASELINE).write_text(ut.render_baseline({}), encoding="utf-8")
    write(tmp_path, "app/webapp/static/index.html", FIXTURE_HTML)
    write(tmp_path, "app/webapp/static/app.js", FIXTURE_JS)
    assert run_mode(tmp_path) == ut.EXIT_RISE
    out = capsys.readouterr().out
    assert "app/webapp/static/index.html:4: [untracked-control]" in out
    assert "app/webapp/static/index.html:5: [untracked-sheet]" in out
    assert "app/webapp/static/index.html:5: [untracked-control]" in out
    assert "app/webapp/static/app.js:4: [untracked-control] createElement('button')" in out
    assert "data-tab" not in out and "index.html:7" not in out, "the nav tab is a view"

    write(tmp_path, "app/webapp/static/index.html", FIXTURE_HTML
          .replace('<button id="refresh">', '<button id="refresh" data-track="refresh">')
          .replace('<dialog id="settings">', '<dialog id="settings" data-track-view="settings">')
          .replace('<button value="cancel">', '<button value="cancel" data-track="settings.close">'))
    write(tmp_path, "app/webapp/static/app.js", FIXTURE_JS.replace(
        "  b.textContent = label;\n", "  b.textContent = label;\n  b.dataset.track = 'row.open';\n"))
    assert run_mode(tmp_path) == ut.EXIT_PASS


def test_init_records_real_counts_and_never_overwrites(repo: Path) -> None:
    assert run_mode(repo, init=True) == ut.EXIT_PASS
    assert '{"key": "app/webapp/static/index.html", "counts": {"untracked-control": 1}}' in baseline_text(repo)
    assert run_mode(repo, init=True) == ut.EXIT_CONFIG


def test_unchanged_tree_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    assert run_mode(repo) == ut.EXIT_PASS
    assert ("PASS (1 baselined hit(s) in 1 file(s), none new; "
            "rules: untracked-control, untracked-sheet, dynamic-id)") in capsys.readouterr().out


def test_a_new_violation_fails_by_rule_file_and_line(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "app/webapp/static/sheet.js", "\nconst d = document.createElement('dialog');\n")
    capsys.readouterr()
    assert run_mode(repo) == ut.EXIT_RISE
    out = capsys.readouterr().out
    assert "app/webapp/static/sheet.js: [untracked-sheet] 1 hit(s), baseline 0:" in out
    assert "app/webapp/static/sheet.js:2: [untracked-sheet] createElement('dialog') gets no data-track-view" in out


def test_a_second_violation_of_a_baselined_rule_in_the_same_file_fails(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "app/webapp/static/index.html", "<main>\n<button>Go</button>\n<button>Stop</button>\n</main>\n")
    assert run_mode(repo) == ut.EXIT_RISE


def test_a_fixed_violation_passes_with_a_shrink_hint(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "app/webapp/static/index.html", '<main>\n<button data-track="go">Go</button>\n</main>\n')
    assert run_mode(repo) == ut.EXIT_PASS
    assert "1 baselined hit(s) are gone" in capsys.readouterr().out


def test_update_baseline_shrinks_only(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "app/webapp/static/index.html", "<main></main>\n")
    assert run_mode(repo, update=True) == ut.EXIT_PASS
    assert '"entries": []' in baseline_text(repo)
    write(repo, "app/webapp/static/b.html", "<button>x</button>\n")
    assert run_mode(repo, update=True) == ut.EXIT_RISE
    assert "b.html" not in baseline_text(repo), "a refused update writes nothing"


def test_allow_additions_adds_to_the_baseline(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "app/webapp/static/b.html", "<button>x</button>\n")
    assert run_mode(repo, update=True, allow=True) == ut.EXIT_PASS
    assert '{"key": "app/webapp/static/b.html", "counts": {"untracked-control": 1}}' in baseline_text(repo)
    assert run_mode(repo) == ut.EXIT_PASS


def test_missing_baseline_fails_instead_of_passing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo) == ut.EXIT_RISE
    assert "baseline .usage-track-ratchet-baseline.json is missing" in capsys.readouterr().out


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"version": 9, "entries": []}',
        '{"version": 1, "entries": [{"key": "a"}]}',
        '{"version": 1, "entries": [{"key": "a", "counts": {"no-such-rule": 1}}]}',
        '{"version": 1, "entries": [{"key": "a", "counts": {"usage-log-wired": 1}}]}',
        '{"version": 1, "entries": [{"key": "a", "counts": {"dynamic-id": 0}}]}',
    ],
)
def test_unreadable_baseline_exits_two(repo: Path, text: str) -> None:
    (repo / ut.DEFAULT_BASELINE).write_text(text, encoding="utf-8")
    assert run_mode(repo) == ut.EXIT_CONFIG


def test_disabled_or_absent_stage_exits_zero_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path) == ut.EXIT_PASS
    assert "not enabled" in capsys.readouterr().out
    assert run_mode(tmp_path, init=True) == ut.EXIT_CONFIG


def test_out_of_scope_excluded_vendored_and_test_files_are_not_scanned(repo: Path) -> None:
    run_mode(repo, init=True)
    for rel in ("app/webapp/static/vend/x.html", "app/webapp/static/third/y.html",
                "app/webapp/static/lib/z.min.js", "tests/e2e/page.html", "docs/demo.html",
                "app/webapp/static/tests/fixture.html"):
        write(repo, rel, "<button>x</button>\n" if rel.endswith("html") else "x('<button>');\n")
    (repo / ".fleet.toml").write_text(
        FIXTURE_TABLE + 'exclude = ["app/webapp/static/third/**"]\n'
        '[vendored]\nx = { dest = "app/webapp/static/vend/" }\n',
        encoding="utf-8",
    )
    assert run_mode(repo) == ut.EXIT_PASS


def test_no_baseline_is_ever_read_as_evidence(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    git(repo, "add", "-f", ut.DEFAULT_BASELINE)
    write(repo, ".structure-ratchet-baseline.json", '{"note": "<button>x</button>"}\n')
    capsys.readouterr()
    assert run_mode(repo) == ut.EXIT_PASS
    assert "PASS (1 baselined hit(s) in 1 file(s), none new" in capsys.readouterr().out


def test_an_untracked_file_with_a_violation_fails(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "app/webapp/static/b.html", "<button>x</button>\n", track=False)
    assert run_mode(repo) == ut.EXIT_RISE


def test_an_ignored_file_is_still_skipped(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, ".gitignore", "app/webapp/static/ignored.html\n")
    write(repo, "app/webapp/static/ignored.html", "<button>x</button>\n", track=False)
    assert run_mode(repo) == ut.EXIT_PASS


def test_a_builder_naming_an_unlisted_file_is_a_config_error(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    (repo / ".fleet.toml").write_text(FIXTURE_TABLE + 'builders = ["app/webapp/static/row.js:row"]\n',
                                      encoding="utf-8")
    assert run_mode(repo) == ut.EXIT_CONFIG
    assert "which git does not list" in capsys.readouterr().out


# ------------------------------------------------------- wiring (never baselined)

WIRED_TABLE = FIXTURE_TABLE.replace('"dynamic-id"]', '"dynamic-id", "usage-log-wired"]')
VENDORED = ('[vendored]\nusage-log = { dest = "app/webapp/static/_vendored/usage-log" }\n'
            'usage_log = { dest = "src/usage_log.py" }\n')


def test_an_app_that_does_not_reach_its_usage_log_fails_whatever_the_baseline(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (repo / ".fleet.toml").write_text(WIRED_TABLE, encoding="utf-8")
    assert run_mode(repo, init=True) == ut.EXIT_PASS, "--init records the per-file rules; the wiring is never in it"
    assert "usage-log-wired" not in baseline_text(repo)
    capsys.readouterr()
    assert run_mode(repo) == ut.EXIT_RISE
    out = capsys.readouterr().out
    assert "`[vendored]` does not declare `usage-log` (the client)" in out
    assert "`[vendored]` does not declare `usage_log` (the server)" in out
    assert "no file in `paths` calls `initUsageLog(`" in out
    assert "no tracked Python file calls `usage_router(`" in out


def test_a_wired_app_passes_and_the_vendored_copies_are_not_scanned(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(WIRED_TABLE + VENDORED, encoding="utf-8")
    write(repo, "app/webapp/static/_vendored/usage-log/usage-log.js", "export function initUsageLog() {}\n")
    write(repo, "src/usage_log.py", "def usage_router(path):\n    return path\n")
    run_mode(repo, init=True)
    assert run_mode(repo) == ut.EXIT_RISE, "the definitions alone are not a call"
    write(repo, "app/webapp/static/app.js", "const usage = initUsageLog();\n")
    write(repo, "app/webapp/server.py", "app.include_router(usage_router(db))\n")
    assert run_mode(repo) == ut.EXIT_PASS


# ------------------------------------------------------- not confirmed

@pytest.mark.parametrize(
    ("rel", "body", "says"),
    [
        pytest.param("app/webapp/static/bad.js", b"const a = 'open;\n", "a string that never closes", id="js"),
        pytest.param("app/webapp/static/bad.html", b"<button>caf\xe9</button>\n", "is not UTF-8", id="not-utf8"),
        pytest.param("app/webapp/static/inline.html", b"<script>\nfunction f() {\n</script>\n",
                     "never closes", id="inline-script"),
    ],
)
def test_a_file_that_cannot_be_read_through_is_not_confirmed_in_every_mode(
    repo: Path, rel: str, body: bytes, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_unreadable_file_not_confirmed(ut, run_mode, repo, rel, body, says, capsys)


@pytest.mark.parametrize(("var", "value", "says"), GIT_FAILURES)
def test_git_that_cannot_list_the_tree_is_not_confirmed(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], var: str, value: str, says: str
) -> None:
    assert_unlistable_git_not_confirmed(ut, run_mode, repo, monkeypatch, capsys, var, value, says)


def test_a_ratchet_vendored_without_its_reader_is_not_confirmed(tmp_path: Path) -> None:
    alone = tmp_path / "scripts" / "usage_track_ratchet.py"
    alone.parent.mkdir()
    shutil.copyfile(REPO_ROOT / "scripts" / "usage_track_ratchet.py", alone)
    done = subprocess.run([sys.executable, "-P", str(alone)], capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONUTF8": "1"}, creationflags=NO_WINDOW, timeout=60, check=False)
    assert done.returncode == ut.EXIT_NOT_CONFIRMED
    assert "usage_track_scan.py is missing beside this script" in done.stdout


def test_main_rejects_allow_additions_without_update(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        ut.main(["--allow-additions"])
    assert exc.value.code == 2
    assert "--allow-additions" in capsys.readouterr().err


# ------------------------------------------------------------ self-adoption

def test_scaffold_adopts_the_stage_and_commits_a_parseable_baseline() -> None:
    cfg, _, _ = ut.load_config(REPO_ROOT)
    assert cfg is not None, "the scaffold adopts its own stage first"
    assert ut.WIRED not in cfg.rules, "the scaffold is not a web app, so it does not claim the wiring"
    assert (REPO_ROOT / cfg.baseline).is_file()
    ut.read_baseline(REPO_ROOT / cfg.baseline)


def test_gate_runs_the_stage_after_the_runtime_write_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    before, stage, mypy = (
        text.index(s) for s in ('Invoke-Stage "runtime write ratchet"', 'Invoke-Stage "usage track ratchet"',
                                'Invoke-Stage "mypy')
    )
    assert before < stage < mypy
    assert "scripts/usage_track_ratchet.py" in text


def test_the_script_is_catalogued_so_it_is_mypy_gated_and_drift_checked() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["usage_track_ratchet"] == {"src": "scripts/usage_track_ratchet.py"}


def test_every_rule_is_documented() -> None:
    doc = (REPO_ROOT / "docs" / "usage-track-ratchet.md").read_text(encoding="utf-8")
    spec = " ".join((ut.__doc__ or "").split())
    for rule in ut.RULES:
        assert f"### `{rule}`" in doc, f"docs/usage-track-ratchet.md has no section for {rule}"
        assert f"`{rule}`" in spec, f"the module docstring omits {rule}"
