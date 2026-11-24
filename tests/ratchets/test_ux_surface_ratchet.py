"""Tests for the UX surface ratchet.

Three layers, mirroring `test_usage_track_ratchet.py`:

1. **Readers** on in-memory sources: the code reader finds `data-surface` ids and
   unmarked surface roots in HTML, inline scripts, JS strings and templates and
   `createElement` blocks; the YAML map reader finds entries, root-less ones,
   invalid ids and dangling links; the cross-check names a missing entry, a
   stale entry and a duplicate id. (The YAML subset and the generator have
   their own tests, `test_ux_surface_map.py`.)
2. **Ratchet behaviour** on throwaway git repos: each named failure is red
   first and green once fixed, every mode, and the "not confirmed" exit for
   anything that cannot be read through. A missing prerequisite is a hard
   failure, never `pytest.skip`.
3. **Self-declaration** -- this repo's table, gate wiring, catalog row and docs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import ux_surface_map as um
from scripts import ux_surface_ratchet as us
from src.no_window import NO_WINDOW
from tests._git_repo import git, write
from tests._ratchet_not_confirmed import (
    GIT_FAILURES,
    assert_unlistable_git_not_confirmed,
    assert_unreadable_file_not_confirmed,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
HTML = "app/webapp/static/index.html"
JS = "app/webapp/static/app.js"


def code(src: str, path: str = HTML) -> tuple[list[str], list[str]]:
    """(`rule:line` of every hit, `id:line` of every declared id) in one in-memory file."""
    hits, sites = us.scan_code(src, path, us.RULES)
    return [f"{h.rule}:{h.line}" for h in hits], [f"{s.id}:{s.line}" for s in sites]


MAP_HEAD = ("app: test\nwalk:\n  date: 2026-01-01\n  build: abc\n  widths: [390]\n  themes: [light]\n"
            "areas:\n  - id: home\n    title: Home\nsurfaces:\n")


def entry(ident: str, *, root: str = "data-surface", links: tuple[str, ...] = (), before: str = "") -> str:
    """One surface in the YAML map, in area `home`; `before` is a comment block above it."""
    text = f"{before}  - id: {ident}\n    area: home\n    title: {ident}\n"
    text += f"    root: {root}\n" if root == "data-surface" else f"    root:\n      none: {root}\n"
    if links:
        text += "    links:\n" + "".join(f"      - to: {to}\n" for to in links)
    return text


def yaml_map(*surfaces: str) -> str:
    return MAP_HEAD + "".join(surfaces)


def entries(text: str) -> list[str]:
    sites, hits = us.read_map(um.load(text, "docs/ux-surfaces.yaml"), "docs/ux-surfaces.yaml")
    return [f"{s.id}:{s.line}{' rootless' if s.rootless else ''}" for s in sites] + [
        f"{h.rule}:{h.line}" for h in hits]


# ------------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert us.parse_config('layer = "x"\n') is None
    assert us.parse_config("[ux_surface_ratchet]\nenabled = false\n") is None
    assert us.parse_config("[ux_surface_ratchet]\n") is None  # opting in is explicit


def test_enabled_table_defaults_to_every_rule_and_honours_every_key() -> None:
    assert us.parse_config("[ux_surface_ratchet]\nenabled = true\n") == us.Config()
    assert us.Config().map == "docs/ux-surfaces.yaml" and us.Config().page == "docs/ux-surface-map.md"
    cfg = us.parse_config(
        '[ux_surface_ratchet]\nenabled = true\nbaseline = "b.json"\nmap = "docs/map.yaml"\npage = "docs/m.md"\n'
        'rules = ["stale-entry", "unmapped-surface"]\npaths = ["web/**"]\nexclude = ["web/vendor/**"]\n'
    )
    assert cfg == us.Config("b.json", ("unmapped-surface", "stale-entry"), "docs/map.yaml", ("web/**",),
                            ("web/vendor/**",), "docs/m.md")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("enabled = true\nrule = []\n", id="typo-in-key"),
        pytest.param('enabled = "yes"\n', id="enabled-not-bool"),
        pytest.param("enabled = true\nrules = []\n", id="no-rules"),
        pytest.param("enabled = true\nrules = ['missing-entry']\n", id="unknown-rule"),
        pytest.param("enabled = true\nmap = ''\n", id="empty-map"),
        pytest.param("enabled = true\npaths = []\n", id="no-paths"),
        pytest.param("enabled = true\nmap = 'docs/ux-surface-map.md'\n", id="markdown-map"),
        pytest.param("enabled = true\nmap = 'a.yaml'\npage = 'a.yaml'\n", id="page-is-map"),
    ],
)
def test_a_malformed_table_is_a_config_error(body: str) -> None:
    with pytest.raises(us.ConfigError):
        us.parse_config(f"[ux_surface_ratchet]\n{body}")


# -------------------------------------------------------------- code reader

def test_html_declares_ids_and_flags_unmarked_surface_roots() -> None:
    src = ('<main data-surface="home.list">\n<dialog>\n</dialog>\n<div role="menu"></div>\n'
           '<div popover></div>\n<section role="tabpanel" data-surface="home.tab"></section>\n'
           '<div role="alertdialog" data-surface="home.confirm"></div>\n</main>\n')
    assert code(src) == (["unmarked-surface:2", "unmarked-surface:4", "unmarked-surface:5"],
                         ["home.list:1", "home.tab:6", "home.confirm:7"])


def test_an_inline_script_is_read_as_js_on_its_own_lines() -> None:
    src = "<p>x</p>\n<script>\nconst d = document.createElement('dialog');\nd.dataset.surface = 'x.sheet';\n" \
          "const m = document.createElement('div');\nm.setAttribute('role', 'menu');\n</script>\n"
    assert code(src) == (["unmarked-surface:5"], ["x.sheet:4"])


def test_js_strings_and_templates_are_read_as_markup() -> None:
    src = "const a = '<dialog data-surface=\"a.one\"></dialog>';\nconst b = `\n<div role=\"menu\">\n</div>`;\n" \
          "const c = `<div data-surface=\"row.${kind}\"></div>`;\n"
    assert code(src, JS) == (["unmarked-surface:3", "invalid-surface-id:5"], ["a.one:1"])


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        pytest.param("el.dataset.surface = 'a.b';\n", ([], ["a.b:1"]), id="dataset-literal"),
        pytest.param("el.setAttribute('data-surface', \"a.b\");\n", ([], ["a.b:1"]), id="set-attribute"),
        pytest.param("const ID = 'a.b';\nel.dataset.surface = ID;\n", ([], ["a.b:2"]), id="module-const"),
        pytest.param("el.dataset.surface = `a.b`;\n", ([], ["a.b:1"]), id="holeless-template"),
        pytest.param("el.dataset.surface = name;\n", (["invalid-surface-id:1"], []), id="variable"),
        pytest.param("el.dataset.surface = 'a.' + kind;\n", (["invalid-surface-id:1"], []), id="concatenation"),
        pytest.param("el.dataset.surface = 'has space';\n", (["invalid-surface-id:1"], []), id="bad-pattern"),
        pytest.param("function f() { const ID = 'a.b'; el.dataset.surface = ID; }\n",
                     (["invalid-surface-id:1"], []), id="block-const-is-not-module-const"),
    ],
)
def test_ids_are_literals_or_module_constants(src: str, expected: tuple[list[str], list[str]]) -> None:
    assert code(src, JS) == expected


def test_a_created_surface_root_is_tied_to_its_id_in_its_block() -> None:
    src = ("function a() {\n  const d = document.createElement('dialog');\n  d.dataset.surface = 'a.d';\n}\n"
           "function b() {\n  const p = document.createElement('div');\n  p.popover = 'auto';\n}\n"
           "function c() {\n  const m = document.createElement('ul');\n}\n"
           "function d() {\n  const x = document.createElement('dialog');\n}\nfunction e() { x.dataset.surface = 'e.x'; }\n")
    assert code(src, JS) == (["unmarked-surface:6", "unmarked-surface:13"], ["a.d:3", "e.x:15"])


def test_a_reasoned_marker_exempts_one_hit_and_a_bare_one_exempts_nothing() -> None:
    src = ("<!-- unmarked-surface-exempt: the browser's own confirm, never shown -->\n<dialog></dialog>\n"
           "<!-- unmarked-surface-exempt -->\n<dialog></dialog>\n")
    assert code(src) == (["unmarked-surface:4"], [])


@pytest.mark.parametrize(
    ("body", "says"),
    [
        pytest.param("const a = 'open;\n", "a string that never closes", id="string"),
        pytest.param("function f() {\n", "never closes", id="brace"),
    ],
)
def test_js_that_does_not_close_is_not_confirmed(body: str, says: str) -> None:
    with pytest.raises(us.NotConfirmed, match=says):
        us.scan_code(body, JS, us.RULES)


# --------------------------------------------------------------- map reader

def test_map_entries_carry_their_item_line_and_rootless_needs_a_reason() -> None:
    text = yaml_map(entry("home.list"), entry("keys.global", root="keys act on the page"),
                    "  - id: state.bare\n    area: home\n    title: Bare\n    root:\n      none:\n",
                    entry("Bad Id"))
    assert entries(text) == ["home.list:11", "keys.global:15 rootless", "state.bare:20", "Bad Id:25",
                             "invalid-surface-id:25"]


def test_a_link_to_an_id_no_entry_lists_is_a_dangling_link_on_the_link_line() -> None:
    text = yaml_map(entry("home.list", links=("home.list", "home.gone")))
    assert entries(text) == ["home.list:11", "dangling-link:17"]


def test_the_shipped_template_loads_and_has_a_rootless_entry() -> None:
    text = (REPO_ROOT / "docs" / "templates" / "ux-surfaces.yaml").read_text(encoding="utf-8")
    sites, hits = us.read_map(um.load(text, "docs/ux-surfaces.yaml"), "docs/ux-surfaces.yaml")
    assert not hits
    assert {s.id for s in sites} == {"chrome.nav", "home.list", "settings.sheet", "keys.global"}
    assert [s.id for s in sites if s.rootless] == ["keys.global"]


# ------------------------------------------------------------- cross-check

def _sites(*pairs: tuple[str, str]) -> list[us.Site]:
    return [us.Site(ident, path, n) for n, (ident, path) in enumerate(pairs, start=1)]


def test_cross_check_names_a_missing_entry_a_stale_entry_and_a_duplicate_id() -> None:
    in_code = _sites(("a.one", HTML), ("a.two", HTML), ("a.two", JS))
    in_map = _sites(("a.one", "m.md"), ("a.gone", "m.md")) + [us.Site("keys", "m.md", 9, rootless=True)]
    hits = us.cross_check(in_code, in_map, us.RULES)
    assert sorted(f"{h.rule}:{h.path}:{h.line}" for h in hits) == [
        f"duplicate-surface:{JS}:3", f"duplicate-surface:{HTML}:2", "stale-entry:m.md:2",
        f"unmapped-surface:{JS}:3", f"unmapped-surface:{HTML}:2",
    ]


def test_the_stale_entry_hint_and_docstring_name_the_yaml_rootless_form() -> None:
    """The hint is printed on every failure; it must spell the form the YAML map schema accepts."""
    (hit,) = us.cross_check([], _sites(("a.gone", "m.yaml")), ("stale-entry",))
    source = (REPO_ROOT / "scripts" / "ux_surface_ratchet.py").read_text(encoding="utf-8")
    for text in (hit.message, source):
        assert "none: <reason>" in text
        assert "*Root" not in text
    sites, hits = us.read_map(um.load(yaml_map(entry("a.gone", root="<reason>")), "m.yaml"), "m.yaml")
    assert not hits and [s.rootless for s in sites] == [True]


def test_an_id_listed_twice_in_the_map_is_a_duplicate() -> None:
    hits = us.cross_check(_sites(("a", HTML)), _sites(("a", "m.md"), ("a", "m.md")), ("duplicate-surface",))
    assert [f"{h.rule}:{h.line}" for h in hits] == ["duplicate-surface:1", "duplicate-surface:2"]


# ---------------------------------------------------------- ratchet on repos

TABLE = "[ux_surface_ratchet]\nenabled = true\n"
MAP = "docs/ux-surfaces.yaml"
PAGE = "docs/ux-surface-map.md"
GOOD_MAP = yaml_map(entry("home.list"))
GOOD_HTML = '<main data-surface="home.list">\n<p>hi</p>\n</main>\n'
#: The line of the next entry appended to GOOD_MAP.
NEXT_ENTRY = GOOD_MAP.count("\n") + 1


def write_map(root: Path, text: str) -> None:
    """The map and the page it generates, both tracked."""
    write(root, MAP, text)
    write(root, PAGE, um.render(um.load(text, MAP), MAP))


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo whose one surface matches its one map entry, with the page generated."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(TABLE, encoding="utf-8")
    write(tmp_path, HTML, GOOD_HTML)
    write_map(tmp_path, GOOD_MAP)
    return tmp_path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return us.run(root, init=init, update=update, allow_additions=allow)


def test_a_matching_app_inits_empty_and_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo, init=True) == us.EXIT_PASS
    assert '"entries": []' in (repo / us.DEFAULT_BASELINE).read_text(encoding="utf-8")
    assert run_mode(repo) == us.EXIT_PASS
    assert "PASS (0 baselined hit(s)" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("rel", "text", "rule", "where", "fix"),
    [
        pytest.param(HTML, GOOD_HTML + '<dialog data-surface="home.add"></dialog>\n', "unmapped-surface",
                     f"{HTML}:4", (MAP, GOOD_MAP + entry("home.add")), id="missing-entry"),
        pytest.param(MAP, GOOD_MAP + entry("home.gone"), "stale-entry", f"{MAP}:{NEXT_ENTRY}", (MAP, GOOD_MAP),
                     id="stale-entry"),
        pytest.param(JS, "const s = document.createElement('section');\ns.dataset.surface = 'home.list';\n",
                     "duplicate-surface", f"{JS}:2", (JS, "const s = document.createElement('section');\n"),
                     id="duplicate-id"),
        pytest.param(MAP, yaml_map(entry("home.list", links=("home.gone",))), "dangling-link",
                     f"{MAP}:16", (MAP, yaml_map(entry("home.list", links=("home.list",)))),  # the `- to:` line
                     id="dangling-link"),
    ],
)
def test_each_named_failure_is_red_then_green_once_fixed(
    repo: Path, capsys: pytest.CaptureFixture[str], rel: str, text: str, rule: str, where: str,
    fix: tuple[str, str],
) -> None:
    assert run_mode(repo, init=True) == us.EXIT_PASS
    (write_map if rel == MAP else lambda r, t: write(r, rel, t))(repo, text)
    assert run_mode(repo) == us.EXIT_RISE
    out = capsys.readouterr().out
    assert f"{where}: [{rule}]" in out
    (write_map if fix[0] == MAP else lambda r, t: write(r, fix[0], t))(repo, fix[1])
    assert run_mode(repo) == us.EXIT_PASS


def test_a_hand_edited_or_missing_page_is_stale_generated_until_regenerated(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run_mode(repo, init=True) == us.EXIT_PASS
    page = (repo / PAGE).read_text(encoding="utf-8")
    write(repo, PAGE, page.replace("# UX surface map: test", "# UX surface map: hand-edited"))
    assert run_mode(repo) == us.EXIT_RISE
    assert f"{PAGE}:3: [stale-generated]" in capsys.readouterr().out
    write(repo, MAP, GOOD_MAP + entry("home.more", root="drawn inside the list"))
    write(repo, PAGE, page)
    assert run_mode(repo) == us.EXIT_RISE, "a map edited without regenerating the page"
    (repo / PAGE).unlink()
    assert run_mode(repo) == us.EXIT_RISE
    assert f"{PAGE}:1: [stale-generated] the page is missing" in capsys.readouterr().out
    assert um.main(["--root", str(repo)]) == um.EXIT_OK
    assert run_mode(repo) == us.EXIT_PASS


def test_a_page_checked_out_with_crlf_line_endings_is_not_stale(repo: Path) -> None:
    assert run_mode(repo, init=True) == us.EXIT_PASS
    page = (repo / PAGE).read_text(encoding="utf-8")
    (repo / PAGE).write_bytes(page.replace("\n", "\r\n").encode("utf-8"))
    assert run_mode(repo) == us.EXIT_PASS


def test_a_reasoned_yaml_comment_above_an_entry_exempts_its_hit(repo: Path) -> None:
    assert run_mode(repo, init=True) == us.EXIT_PASS
    write_map(repo, GOOD_MAP + entry("home.gone", before="  # stale-entry-exempt\n"))
    assert run_mode(repo) == us.EXIT_RISE, "a bare marker exempts nothing"
    write_map(repo, GOOD_MAP + entry("home.gone", before="  # note\n  # stale-entry-exempt: built by a plugin\n"))
    assert run_mode(repo) == us.EXIT_PASS


def test_a_map_outside_the_subset_fails_and_names_its_line(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo, init=True) == us.EXIT_PASS
    write(repo, MAP, GOOD_MAP + "    why: &anchor no\n")
    assert run_mode(repo) == us.EXIT_RISE
    assert f"the surface map is invalid: {MAP}:{NEXT_ENTRY}:" in capsys.readouterr().out


def test_baselined_debt_passes_and_a_second_hit_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, HTML, GOOD_HTML + "<dialog></dialog>\n")
    assert run_mode(repo, init=True) == us.EXIT_PASS
    assert run_mode(repo) == us.EXIT_PASS
    write(repo, HTML, GOOD_HTML + "<dialog></dialog>\n<div role=\"menu\"></div>\n")
    assert run_mode(repo) == us.EXIT_RISE
    assert f"{HTML}: [unmarked-surface] 2 hit(s), baseline 1" in capsys.readouterr().out


def test_update_baseline_shrinks_only_and_allow_additions_adds(repo: Path) -> None:
    write(repo, HTML, GOOD_HTML + "<dialog></dialog>\n")
    run_mode(repo, init=True)
    write(repo, HTML, GOOD_HTML + "<div popover></div>\n<div popover></div>\n")
    before = (repo / us.DEFAULT_BASELINE).read_text(encoding="utf-8")
    assert run_mode(repo, update=True) == us.EXIT_RISE
    assert (repo / us.DEFAULT_BASELINE).read_text(encoding="utf-8") == before, "a refused update writes nothing"
    assert run_mode(repo, update=True, allow=True) == us.EXIT_PASS
    assert '"unmarked-surface": 2' in (repo / us.DEFAULT_BASELINE).read_text(encoding="utf-8")
    write(repo, HTML, GOOD_HTML)
    assert run_mode(repo, update=True) == us.EXIT_PASS
    assert '"entries": []' in (repo / us.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_init_never_overwrites_and_a_missing_baseline_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo) == us.EXIT_RISE
    assert "is missing" in capsys.readouterr().out
    run_mode(repo, init=True)
    assert run_mode(repo, init=True) == us.EXIT_CONFIG


def test_a_missing_map_fails_and_names_the_template(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    (repo / MAP).unlink()
    git(repo, "add", "-A")
    assert run_mode(repo) == us.EXIT_RISE
    assert "docs/templates/ux-surfaces.yaml" in capsys.readouterr().out


def test_disabled_or_absent_stage_exits_zero_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path) == us.EXIT_PASS
    assert "not enabled" in capsys.readouterr().out
    assert run_mode(tmp_path, init=True) == us.EXIT_CONFIG


def test_out_of_scope_excluded_vendored_and_test_files_are_not_scanned(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(
        TABLE + 'exclude = ["app/webapp/static/vendor/**"]\n\n[vendored]\nmodal = { dest = "app/webapp/static/_v" }\n',
        encoding="utf-8")
    run_mode(repo, init=True)
    for rel in ("app/webapp/static/vendor/x.html", "app/webapp/static/_v/modal.html",
                "app/webapp/static/tests/t.html", "other/page.html", "app/webapp/static/x.min.js"):
        write(repo, rel, "<dialog></dialog>\n")
    assert run_mode(repo) == us.EXIT_PASS


def test_an_id_a_vendored_component_stamps_keeps_its_map_entry_from_being_stale(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(TABLE + '\n[vendored]\nbw = { dest = "app/webapp/static/_v/bw" }\n',
                                      encoding="utf-8")
    run_mode(repo, init=True)
    write_map(repo, GOOD_MAP + entry("app.banner"))
    assert run_mode(repo) == us.EXIT_RISE, "no element carries the id yet"
    write(repo, "app/webapp/static/_v/bw/bw.js",
          "const el = document.createElement('div');\nel.dataset.surface = 'app.banner';\n"
          "const d = document.createElement('dialog');\n")
    assert run_mode(repo) == us.EXIT_PASS, "the vendored stamp counts; its unmarked dialog is not the app's hit"


@pytest.mark.parametrize(
    ("rel", "body", "says"),
    [
        pytest.param("app/webapp/static/bad.js", b"const a = 'open;\n", "a string that never closes", id="js"),
        pytest.param("app/webapp/static/bad.html", b"<p>caf\xe9</p>\n", "is not UTF-8", id="not-utf8"),
    ],
)
def test_a_file_that_cannot_be_read_through_is_not_confirmed_in_every_mode(
    repo: Path, rel: str, body: bytes, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_unreadable_file_not_confirmed(us, run_mode, repo, rel, body, says, capsys)


@pytest.mark.parametrize(("var", "value", "says"), GIT_FAILURES)
def test_git_that_cannot_list_the_tree_is_not_confirmed(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], var: str, value: str, says: str
) -> None:
    assert_unlistable_git_not_confirmed(us, run_mode, repo, monkeypatch, capsys, var, value, says)


def test_a_ratchet_vendored_without_its_tokenizer_is_not_confirmed(tmp_path: Path) -> None:
    alone = tmp_path / "scripts" / "ux_surface_ratchet.py"
    alone.parent.mkdir()
    shutil.copyfile(REPO_ROOT / "scripts" / "ux_surface_ratchet.py", alone)
    done = subprocess.run([sys.executable, "-P", str(alone)], capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONUTF8": "1"}, creationflags=NO_WINDOW, timeout=60, check=False)
    assert done.returncode == us.EXIT_NOT_CONFIRMED
    assert "usage_track_scan.py is missing beside this script" in done.stdout


def test_main_rejects_allow_additions_without_update(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        us.main(["--allow-additions"])
    assert exc.value.code == 2
    assert "--allow-additions" in capsys.readouterr().err


# --------------------------------------------------------- self-declaration

def test_the_scaffold_declares_the_stage_off_because_it_has_no_app() -> None:
    cfg, _ = us.load_config(REPO_ROOT)
    assert cfg is None, "the scaffold serves no web app, so it has no surface map to hold"


def test_gate_runs_the_stage_after_the_usage_track_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    before, stage, mypy = (
        text.index(s) for s in ('Invoke-Stage "usage track ratchet"', 'Invoke-Stage "ux surface ratchet"',
                                'Invoke-Stage "mypy')
    )
    assert before < stage < mypy


def test_the_script_is_catalogued_with_its_siblings() -> None:
    from scripts.vendored_catalog import load_catalog

    catalog = load_catalog(REPO_ROOT)
    assert catalog["ux_surface_ratchet"]["src"] == "scripts/ux_surface_ratchet.py"
    assert catalog["ux_surface_map"]["src"] == "scripts/ux_surface_map.py"
    toml = (REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8")
    assert 'requires = ["usage_track_scan", "ux_surface_map", "ratchet_baseline"]' in toml


def test_every_rule_is_documented() -> None:
    doc = (REPO_ROOT / "docs" / "ux-surface-ratchet.md").read_text(encoding="utf-8")
    spec = " ".join((us.__doc__ or "").split())
    for rule in us.RULES:
        assert f"### `{rule}`" in doc, f"docs/ux-surface-ratchet.md has no section for {rule}"
        assert f"`{rule}`" in spec, f"the module docstring omits {rule}"
