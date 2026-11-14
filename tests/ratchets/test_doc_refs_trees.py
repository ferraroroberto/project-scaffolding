"""Tests for the doc-references ratchet's fenced layout trees (`[doc_refs_ratchet] trees = true`).

Two layers: tree parsing on fixture strings (nesting, roots, what is skipped and why),
and the switch on throwaway git repos (default off, a stale entry fails, ignored and
allowed paths, the modes).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from scripts import doc_refs_ratchet as dr
from tests._git_repo import git, write

FILES = [
    "README.md",
    "scripts/real.py",
    "scripts/tool.py",
    "src/mod.py",
    "src/pkg/__init__.py",
    "src/pkg/util.py",
    "tests/fixtures/a.json",
    "tests/test_a.py",
    "docs/a.md",
]
TREE = dr.build_tree(FILES, None)
TOP = TREE.top_dirs


def tree_keys(text: str, *, stats: Counter[str] | None = None, layout: dr.Tree | None = TREE) -> list[str]:
    refs = dr.scan_text(text, "README.md", TOP, layout=layout, stats=stats)
    return [r.key for r in refs if r.kind == "tree"]


def fenced(body: str, info: str = "") -> str:
    return f"```{info}\n{body}\n```\n"


# ------------------------------------------------------------------ parsing

def test_a_stale_entry_is_reported_with_its_line_and_full_path() -> None:
    text = "intro\n" + fenced("project/\n├── scripts/\n│   ├── real.py\n│   └── gone.py\n└── src/")
    (ref,) = [r for r in dr.scan_text(text, "README.md", TOP, layout=TREE) if r.kind == "tree"]
    assert (ref.line, ref.key, ref.text) == (6, "scripts/gone.py", "│   └── gone.py")


def test_a_clean_tree_reports_nothing_and_counts_as_checked() -> None:
    stats: Counter[str] = Counter()
    assert tree_keys(fenced("├── scripts/\n│   └── real.py\n└── src/\n    └── pkg/"), stats=stats) == []
    assert stats == Counter(checked=1)


@pytest.mark.parametrize("indent", [2, 3, 4])
def test_any_indent_width_nests_the_same(indent: int) -> None:
    pad = " " * indent
    body = f"├── scripts/\n│{pad}├── real.py\n│{pad}└── gone.py\n└── src/\n{' ' * (indent + 1)}└── mod.py"
    assert tree_keys(fenced(body)) == ["scripts/gone.py"]


def test_a_closing_connector_pops_back_to_the_parent() -> None:
    body = "├── src/\n│   ├── pkg/\n│   │   └── util.py\n│   └── mod.py\n└── docs/\n    └── gone.md"
    assert tree_keys(fenced(body)) == ["docs/gone.md"]


def test_comments_and_alternates_after_the_name_are_ignored() -> None:
    body = "├── scripts/            # the gate\n│   ├── real.py  (entry)\n│   │   # continued\n│   └── tool.py / other.py\n└── src/"
    assert tree_keys(fenced(body)) == []


def test_a_missing_folder_reports_itself_not_its_children() -> None:
    body = "├── scripts/\n├── app/\n│   ├── main.py\n│   └── views/\n│       └── home.py\n└── src/"
    assert tree_keys(fenced(body)) == ["app"]


def test_the_trailing_slash_is_dropped_so_the_key_matches_an_inline_mention() -> None:
    assert tree_keys(fenced("├── scripts/\n├── old/\n└── src/")) == ["old"]


@pytest.mark.parametrize("name", ["<name>/", "*.py", "{a,b}", "$HOME", "…", "...", "../up", "~/x", "/abs", "`x.py`", "**bold**"])
def test_placeholders_and_non_paths_are_skipped_with_their_subtree(name: str) -> None:
    body = f"├── scripts/\n├── {name}\n│   └── child.py\n└── src/"
    assert tree_keys(fenced(body)) == []


def test_the_named_root_folder_rebases_the_tree() -> None:
    assert tree_keys(fenced("tests/\n├── fixtures/\n└── gone.py")) == ["tests/gone.py"]
    assert tree_keys(fenced("tests/\n├── test_a.py\n└── fixtures/")) == []
    assert tree_keys(fenced("tests/\n├── real.py\n└── fixtures/")) == ["tests/real.py"]  # `real.py` lives in scripts/


def test_dot_and_repo_name_roots_are_the_repo_root() -> None:
    for label in (".", "./", "myproject/", "my-repo"):
        assert tree_keys(fenced(f"{label}\n├── scripts/\n└── old.py")) == ["old.py"], label


def test_a_tree_with_no_root_line_starts_at_the_repo_root() -> None:
    assert tree_keys(fenced("├── scripts/\n└── old.py")) == ["old.py"]


def test_an_unanchored_tree_is_skipped_and_counted() -> None:
    stats: Counter[str] = Counter()
    other_repo = fenced("other/\n├── alpha/\n│   └── x.py\n└── beta/")
    assert tree_keys(other_repo, stats=stats) == []
    assert stats == Counter(unanchored=1)


def test_a_tree_needs_at_least_two_entries() -> None:
    stats: Counter[str] = Counter()
    assert tree_keys(fenced("└── gone.py"), stats=stats) == []
    assert not stats


@pytest.mark.parametrize("info", ["", "text", "txt", "tree", "plain", "plaintext", "TEXT"])
def test_fences_that_may_hold_a_tree_are_read(info: str) -> None:
    assert tree_keys(fenced("├── scripts/\n└── old.py", info)) == ["old.py"]


@pytest.mark.parametrize("info", ["python", "json", "mermaid", "bash", "toml"])
def test_other_fences_are_never_read_as_trees(info: str) -> None:
    assert tree_keys(fenced("├── scripts/\n└── old.py", info)) == []


def test_a_one_dash_diagram_is_not_a_file_tree() -> None:
    assert tree_keys(fenced("body\n├─ header\n│  └─ nav\n└─ main")) == []


def test_a_tree_outside_a_fence_is_prose_and_not_read() -> None:
    assert tree_keys("├── scripts/\n└── old.py\n") == []


def test_a_fence_inside_a_list_item_or_blockquote_is_read() -> None:
    listed = "- layout:\n\n  ```text\n  ├── scripts/\n  └── old.py\n  ```\n"
    quoted = "> ```\n> ├── scripts/\n> └── old.py\n> ```\n"
    assert tree_keys(listed) == ["old.py"]
    assert tree_keys(quoted) == ["old.py"]


def test_crlf_text_reads_the_same() -> None:
    assert tree_keys(fenced("├── scripts/\n└── old.py").replace("\n", "\r\n")) == ["old.py"]


def test_without_a_layout_nothing_is_parsed() -> None:
    assert tree_keys(fenced("├── scripts/\n└── old.py"), layout=None) == []


def test_retired_terms_still_see_a_tree_fence_and_an_unclosed_one_is_still_not_confirmed() -> None:
    retired = (dr.Retired("old.py", "gone"),)
    refs = dr.scan_text(fenced("├── scripts/\n└── old.py"), "README.md", TOP, retired=retired, layout=TREE)
    assert sorted(r.kind for r in refs) == ["retired", "tree"]
    with pytest.raises(dr.NotConfirmed):
        dr.scan_text("```\n├── scripts/\n└── old.py\n", "README.md", TOP, layout=TREE)


# ------------------------------------------------------------------- config

def test_trees_defaults_off_and_reads_true() -> None:
    assert dr.parse_config("[doc_refs_ratchet]\nenabled = true\n").trees is False  # type: ignore[union-attr]
    assert dr.parse_config("[doc_refs_ratchet]\nenabled = true\ntrees = true\n").trees is True  # type: ignore[union-attr]


def test_trees_must_be_a_bool() -> None:
    with pytest.raises(dr.ConfigError):
        dr.parse_config('[doc_refs_ratchet]\nenabled = true\ntrees = "yes"\n')


# -------------------------------------------------------- ratchet on a git repo

README_TREE = "```text\nproj/\n├── scripts/\n│   └── real.py\n└── tests/\n    ├── fixtures/\n    └── data/\n```\n"


def make_repo(root: Path, *, trees: bool) -> Path:
    git(root, "init", "-q")
    switch = "trees = true\n" if trees else ""
    write(root, ".fleet.toml", f"[doc_refs_ratchet]\nenabled = true\n{switch}", track=False)
    write(root, "scripts/real.py", "")
    write(root, "tests/fixtures/a.json", "{}")
    write(root, "README.md", README_TREE)
    return root


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return dr.run(root, init=init, update=update, allow_additions=allow)


def test_default_off_a_stale_tree_entry_changes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path, trees=False)
    assert run_mode(root, init=True) == dr.EXIT_PASS
    assert run_mode(root) == dr.EXIT_PASS
    out = capsys.readouterr().out
    assert "none new" in out
    assert "layout tree" not in out
    assert "tests/data" not in (root / dr.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_switched_on_the_stale_entry_is_baselined_then_a_new_one_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = make_repo(tmp_path, trees=True)
    assert run_mode(root, init=True) == dr.EXIT_PASS
    assert '"refs": ["tests/data"]' in (root / dr.DEFAULT_BASELINE).read_text(encoding="utf-8")
    capsys.readouterr()
    assert run_mode(root) == dr.EXIT_PASS
    assert "1 layout tree(s) checked, 0 not anchored" in capsys.readouterr().out

    write(root, "README.md", README_TREE.replace("real.py", "real.py\n│   └── older.py"))
    assert run_mode(root) == dr.EXIT_RISE
    assert "README.md:5: tree `scripts/older.py` does not exist" in capsys.readouterr().out


def test_fixing_the_entry_makes_the_baseline_shrinkable(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path, trees=True)
    run_mode(root, init=True)
    write(root, "README.md", README_TREE.replace("data/", "fixtures/"))
    capsys.readouterr()
    assert run_mode(root) == dr.EXIT_PASS
    assert "--update-baseline" in capsys.readouterr().out
    assert run_mode(root, update=True) == dr.EXIT_PASS
    assert '"entries": []' in (root / dr.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_an_ignored_entry_is_machine_local_not_stale(tmp_path: Path) -> None:
    root = make_repo(tmp_path, trees=True)
    write(root, ".gitignore", "tests/data/\n")
    run_mode(root, init=True)
    assert "tests/data" not in (root / dr.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_allow_refs_covers_a_tree_entry_exactly_as_it_covers_an_inline_mention(tmp_path: Path) -> None:
    root = make_repo(tmp_path, trees=True)
    write(root, ".fleet.toml", '[doc_refs_ratchet]\nenabled = true\ntrees = true\nallow_refs = ["tests/data"]\n', track=False)
    run_mode(root, init=True)
    assert "tests/data" not in (root / dr.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_a_trees_value_that_is_not_a_bool_exits_2(tmp_path: Path) -> None:
    root = make_repo(tmp_path, trees=False)
    write(root, ".fleet.toml", '[doc_refs_ratchet]\nenabled = true\ntrees = "yes"\n', track=False)
    assert run_mode(root, init=True) == dr.EXIT_CONFIG


def test_trees_outside_the_include_scope_are_not_read(tmp_path: Path) -> None:
    root = make_repo(tmp_path, trees=True)
    write(root, "notes/layout.md", README_TREE.replace("data/", "gone/"))
    run_mode(root, init=True)
    assert "notes/layout.md" not in (root / dr.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_unanchored_trees_are_counted_in_the_pass_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = make_repo(tmp_path, trees=True)
    write(root, "docs/other.md", "```\nelsewhere/\n├── alpha/\n└── beta/\n```\n")
    run_mode(root, init=True)
    capsys.readouterr()
    assert run_mode(root) == dr.EXIT_PASS
    assert "1 layout tree(s) checked, 1 not anchored, skipped" in capsys.readouterr().out
