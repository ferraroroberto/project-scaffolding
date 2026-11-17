"""Tests for the UX surface map reader and page generator (`scripts/ux_surface_map.py`).

1. **The YAML subset:** what it reads, and that everything outside it is an
   error naming its line rather than a silent misread.
2. **The schema:** required and unknown keys, areas, roots, links.
3. **The generator:** the shipped template renders, a second run is
   byte-identical, one diagram per area with cross-area stubs, and the CLI's
   write and `--check` modes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import ux_surface_map as um

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "docs" / "templates" / "ux-surfaces.yaml"
HEAD = ("app: demo\nwalk:\n  date: 2026-01-01\n  build: abc\n  widths: [390, 1280]\n  themes: [light, dark]\n"
        "areas:\n  - id: home\n    title: Home\n  - id: more\n    title: More\nsurfaces:\n")


# -------------------------------------------------------------- YAML subset

def test_the_subset_reads_mappings_sequences_scalars_and_comments() -> None:
    text = (
        "# a comment\n"
        "plain: a value, with commas # and a trailing comment\n"
        "single: 'it''s: quoted'\n"
        'double: "tab\\there \\u00e9 \\"q\\""  # comment\n'
        "flow: [390, 'a, b', \"c\"]  # comment\n"
        "empty_flow: []\n"
        "items:\n"
        "- same-indent item\n"
        "- key: one\n"
        "  other: two\n"
        "nested:\n"
        "  deeper:\n"
        "    - x\n"
        "literal: |\n"
        "  line one\n"
        "    kept indent\n"
        "\n"
        "  # not a comment\n"
        "folded: >-\n"
        "  joined\n"
        "  words\n"
        "\n"
        "  new paragraph\n"
        "nothing:\n"
    )
    doc = um.read_yaml(text, "m.yaml")
    assert doc == {
        "plain": "a value, with commas", "single": "it's: quoted", "double": 'tab\there \u00e9 "q"',
        "flow": ["390", "a, b", "c"], "empty_flow": [], "items": ["same-indent item", {"key": "one", "other": "two"}],
        "nested": {"deeper": ["x"]}, "literal": "line one\n  kept indent\n\n# not a comment\n",
        "folded": "joined words\nnew paragraph", "nothing": None,
    }
    assert doc.key_lines["items"] == 7
    assert doc["items"].item_lines == [8, 9]


@pytest.mark.parametrize(
    ("text", "line", "says"),
    [
        pytest.param("a: 1\n\tb: 2\n", 2, "tab", id="tab-indent"),
        pytest.param("a: &x 1\n", 1, "must be quoted", id="anchor"),
        pytest.param("a: *x\n", 1, "must be quoted", id="alias"),
        pytest.param("a: !tag x\n", 1, "must be quoted", id="tag"),
        pytest.param("a: {b: 1}\n", 1, "must be quoted", id="flow-mapping"),
        pytest.param("a: `code` first\n", 1, "must be quoted", id="backtick-first"),
        pytest.param("a: b: c\n", 1, "quote this value", id="colon-space"),
        pytest.param("a: yes\n", 1, "non-text value", id="yaml-boolean"),
        pytest.param("a: ~\n", 1, "non-text value", id="yaml-null"),
        pytest.param("a: one\n  two\n", 2, "unexpected indentation", id="multi-line-plain"),
        pytest.param("a: 'open\n", 1, "close on its own line", id="unclosed-quote"),
        pytest.param('a: "\\x41"\n', 1, "unsupported escape", id="bad-escape"),
        pytest.param("a: 'x' y\n", 1, "after a quoted value", id="text-after-quote"),
        pytest.param("a: [1, [2]]\n", 1, "nested flow", id="nested-flow"),
        pytest.param("a: [1, 2\n", 1, "must close", id="unclosed-flow"),
        pytest.param("a: [1, , 2]\n", 1, "empty item", id="empty-flow-item"),
        pytest.param("a: 1\na: 2\n", 2, "duplicate key", id="duplicate-key"),
        pytest.param("---\na: 1\n", 1, "document markers", id="document-marker"),
        pytest.param("a: >\n  one\n    two\n", 3, "more-indented", id="folded-more-indented"),
        pytest.param("a: |+\n  x\n", 1, "block scalar header", id="keep-chomping"),
        pytest.param("a: |\nb: 1\n", 1, "empty block scalar", id="empty-block"),
        pytest.param("- a\n", 1, "mapping starting at column 0", id="top-sequence"),
        pytest.param("\n# only comments\n", 1, "empty", id="empty"),
        pytest.param("bad key: 1\n", 1, "mapping starting at column 0", id="spaced-key"),
        pytest.param("a:\n  - x\n  y: 1\n", 3, "unexpected indentation", id="mixed-block"),
    ],
)
def test_anything_outside_the_subset_is_an_error_naming_its_line(text: str, line: int, says: str) -> None:
    with pytest.raises(um.MapError, match=says) as exc:
        um.read_yaml(text, "m.yaml")
    assert exc.value.line == line
    assert str(exc.value).startswith(f"m.yaml:{line}: ")


# ------------------------------------------------------------------ schema

def surface(ident: str, area: str = "home", extra: str = "") -> str:
    return f"  - id: {ident}\n    area: {area}\n    title: T {ident}\n    root: data-surface\n{extra}"


@pytest.mark.parametrize(
    ("text", "says"),
    [
        pytest.param(HEAD.replace("app: demo\n", ""), "needs `app`", id="no-app"),
        pytest.param(HEAD + "  - id: a\n    area: home\n    title: A\n", "needs `root`", id="no-root"),
        pytest.param("extra: 1\n" + HEAD, "unknown key", id="unknown-top-key"),
        pytest.param(HEAD + surface("a", extra="    colour: red\n"), "unknown key", id="unknown-surface-key"),
        pytest.param(HEAD + surface("a", area="nowhere"), "area `nowhere` is not one of", id="unknown-area"),
        pytest.param(HEAD + surface("a").replace("root: data-surface", "root: element"), "`root` is",
                     id="bad-root"),
        pytest.param(HEAD + surface("a", extra="    reach: one way\n"), "list of text items", id="reach-not-list"),
        pytest.param(HEAD + surface("a", extra="    why: [a]\n"), "must be text", id="why-not-text"),
        pytest.param(HEAD + surface("a", extra="    links:\n      - via: x\n"), "needs `to`", id="link-without-to"),
        pytest.param(HEAD.replace("  - id: more\n", "  - id: home\n"), "listed twice", id="duplicate-area"),
        pytest.param(HEAD.replace("walk:\n  date: 2026-01-01\n", "walk:\n"), "needs `date`", id="walk-incomplete"),
    ],
)
def test_a_map_outside_the_schema_is_an_error(text: str, says: str) -> None:
    with pytest.raises(um.MapError, match=says):
        um.load(text, "m.yaml")


def test_a_root_none_keeps_its_reason_and_a_bare_none_is_not_rootless() -> None:
    text = HEAD + surface("a").replace("root: data-surface", "root:\n      none: a gesture") + surface("b").replace(
        "root: data-surface", "root:\n      none:")
    a, b = um.load(text, "m.yaml").surfaces
    assert (a.root_none, a.rootless, b.root_none, b.rootless) == ("a gesture", True, "", False)


# --------------------------------------------------------------- generator

def test_the_template_renders_and_a_second_run_is_byte_identical() -> None:
    text = TEMPLATE.read_text(encoding="utf-8")
    first = um.render(um.load(text, "docs/ux-surfaces.yaml"), "docs/ux-surfaces.yaml")
    assert first == um.render(um.load(text, "docs/ux-surfaces.yaml"), "docs/ux-surfaces.yaml")
    assert first.startswith("<!-- Generated from docs/ux-surfaces.yaml by scripts/ux_surface_map.py.")
    assert first.count("```mermaid") == 4, "one diagram per area"
    assert "### `keys.global` Keyboard shortcuts" in first


def test_each_area_diagram_draws_its_own_surfaces_and_cross_area_stubs() -> None:
    text = HEAD + surface("home.list", extra="    links:\n      - to: more.sheet\n        via: Open \"more\"\n"
                                             "      - to: home.gone\n") + surface("more.sheet", area="more")
    page = um.render(um.load(text, "m.yaml"), "m.yaml")
    home, more = (page.split("## Home\n")[1].split("## More\n")[0], page.split("## More\n")[1])
    assert 's0["T home.list"]' in home and 's1(["T more.sheet · More"])' in home
    assert 's0 -->|"Open #quot;more#quot;"| s1' in home
    assert '(["home.gone (no entry)"])' in home
    assert 's1["T more.sheet"]' in more and 's0(["T home.list · Home"])' in more
    assert "home.gone" not in more.split("## Link index")[0], "a link between two other areas is not drawn here"
    assert "| [T home.list](#homelist-t-homelist) | Open \"more\" | [T more.sheet](#moresheet-t-moresheet) |" in page
    assert "| [T home.list](#homelist-t-homelist) |  | `home.gone` (no entry) |" in page


def test_an_area_with_no_surfaces_says_so_and_repeated_headings_number_like_github() -> None:
    text = HEAD.replace("title: More", "title: Home") + surface("a.x")
    page = um.render(um.load(text, "m.yaml"), "m.yaml")
    assert "| [Home](#home) | 1 |\n| [Home](#home-1) | 0 |" in page
    assert page.rstrip().endswith("No links yet.")
    assert "No surfaces yet." in page


def test_first_difference_ignores_line_endings_and_names_the_line() -> None:
    assert um.first_difference("a\nb\n", "a\r\nb\r\n") == 0
    assert um.first_difference("a\nb\n", "a\nc\n") == 2
    assert um.first_difference("a\nb\n", "a\n") == 2


# --------------------------------------------------------------------- CLI

def test_the_cli_writes_the_page_and_check_fails_until_it_is_current(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / ".fleet.toml").write_text('[ux_surface_ratchet]\nmap = "ux/map.yaml"\npage = "ux/page.md"\n',
                                          encoding="utf-8")
    (tmp_path / "ux").mkdir()
    (tmp_path / "ux" / "map.yaml").write_text(TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8")
    assert um.main(["--root", str(tmp_path), "--check"]) == um.EXIT_FAIL
    assert "is not what ux/map.yaml generates" in capsys.readouterr().out
    assert um.main(["--root", str(tmp_path)]) == um.EXIT_OK
    written = (tmp_path / "ux" / "page.md").read_bytes()
    assert b"\r\n" not in written
    assert um.main(["--root", str(tmp_path), "--check"]) == um.EXIT_OK
    assert um.main(["--root", str(tmp_path)]) == um.EXIT_OK
    assert (tmp_path / "ux" / "page.md").read_bytes() == written, "a second run is byte-identical"


def test_the_cli_fails_on_an_invalid_or_missing_map(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert um.main(["--root", str(tmp_path)]) == um.EXIT_FAIL
    assert "cannot read docs/ux-surfaces.yaml" in capsys.readouterr().out
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "ux-surfaces.yaml").write_text("app: &x\n", encoding="utf-8")
    assert um.main(["--root", str(tmp_path)]) == um.EXIT_FAIL
    assert "docs/ux-surfaces.yaml:1:" in capsys.readouterr().out
    assert not (tmp_path / "docs" / "ux-surface-map.md").exists()


def test_the_convention_page_example_is_a_valid_map() -> None:
    page = (REPO_ROOT / "docs" / "ux-surface-map.md").read_text(encoding="utf-8")
    example = page.split("```yaml\n", 1)[1].split("```", 1)[0]
    smap = um.load(example, "docs/ux-surface-map.md")
    assert [s.id for s in smap.surfaces] == ["today.row-menu"]
    assert smap.surfaces[0].reach[-1] == "`.` on a focused row"
