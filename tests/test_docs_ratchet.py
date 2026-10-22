"""Tests for the README-size and docs-history ratchet.

Three layers, mirroring `test_comment_ratchet.py`:

1. **Counting** on fixture strings: what the Markdown scan counts and what it
   must not (fences, URLs, link targets, HTML comments, anchors, entities).
2. **Ratchet behaviour** on throwaway git repos: a risen count or a README past
   its budget fails and names the file, a lowered one passes, every mode, and the
   "not confirmed" exit for anything the scanner cannot finish. A missing
   prerequisite is a hard failure, never `pytest.skip`.
3. **Self-adoption** -- this repo's own declaration and gate wiring.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import docs_ratchet as dr
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parent.parent


def kinds(text: str, allow: tuple[str, ...] = ()) -> list[str]:
    return [m.kind for m in dr.scan_text(text, allow)]


def count(text: str, allow: tuple[str, ...] = ()) -> int:
    return len(dr.scan_text(text, allow))


# ------------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert dr.parse_config('layer = "x"\n') is None
    assert dr.parse_config("[docs_ratchet]\nenabled = false\n") is None
    assert dr.parse_config("[docs_ratchet]\n") is None  # opting in is explicit


def test_enabled_table_gets_the_documented_defaults() -> None:
    assert dr.parse_config("[docs_ratchet]\nenabled = true\n") == dr.Config(
        ".docs-ratchet-baseline.json", ("README.md", "docs/"), (), 40960, ()
    )


def test_enabled_table_honours_every_key() -> None:
    cfg = dr.parse_config(
        '[docs_ratchet]\nenabled = true\nbaseline = "b.json"\ninclude = ["README.md"]\n'
        'exclude = ["docs/gen/**"]\nreadme_max_bytes = 100\nallow_refs = ["o/r#1"]\n'
    )
    assert cfg == dr.Config("b.json", ("README.md",), ("docs/gen/**",), 100, ("o/r#1",))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("enabled = true\nbaselin = 'x'\n", id="typo-in-key"),
        pytest.param('enabled = "yes"\n', id="enabled-not-bool"),
        pytest.param("enabled = true\nbaseline = ''\n", id="empty-baseline"),
        pytest.param("enabled = true\ninclude = 'docs/'\n", id="include-not-a-list"),
        pytest.param("enabled = true\nexclude = [1]\n", id="exclude-not-strings"),
        pytest.param("enabled = true\nallow_refs = 'o/r#1'\n", id="allow-refs-not-a-list"),
        pytest.param("enabled = true\nreadme_max_bytes = 0\n", id="budget-zero"),
        pytest.param("enabled = true\nreadme_max_bytes = '40k'\n", id="budget-not-int"),
        pytest.param("enabled = true\nreadme_max_bytes = true\n", id="budget-bool"),
    ],
)
def test_malformed_table_fails_loud(body: str) -> None:
    with pytest.raises(dr.ConfigError):
        dr.parse_config("[docs_ratchet]\n" + body)


def test_vendored_dests_are_read_from_the_adopters_own_table() -> None:
    toml = (
        '[vendored]\nnav = { src = "x", sha = "1", dest = "docs/vendored" }\n'
        'single = { src = "y", dest = "docs\\\\copy.md" }\nbare = { src = "z" }\n'
    )
    assert dr.vendored_dests(toml) == ("docs/copy.md", "docs/vendored")
    assert dr.vendored_dests('layer = "x"\n') == ()


# ------------------------------------------------------------------ counting: references

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param("fixed in #123", 1, id="bare"),
        pytest.param("fixed in repo#123", 1, id="repo-prefix"),
        pytest.param("fixed in owner/repo#123", 1, id="owner-repo-prefix"),
        pytest.param("#1 #22 #333 #4444 #55555", 5, id="one-to-five-digits"),
        pytest.param("#666666", 0, id="six-digits-is-not-an-issue"),
        pytest.param("(#42)", 1, id="in-parens"),
        pytest.param("#12-intro", 0, id="anchor-style-suffix"),
        pytest.param("#12abc", 0, id="word-suffix"),
        pytest.param("&#123; and &#8212;", 0, id="html-entity"),
        pytest.param("## 12", 0, id="heading-marker-is-not-a-reference"),
        pytest.param("path/#12", 0, id="after-a-slash"),
        pytest.param("see [section](#12) and [two](#3-install)", 0, id="anchor-link-target"),
        pytest.param('<a href="#12">x</a> <img src="a#3.png">', 0, id="html-attribute-urls"),
    ],
)
def test_reference_shape(text: str, expected: int) -> None:
    assert count(text) == expected


def test_a_reference_inside_inline_code_counts() -> None:
    assert count("see `#123` and ``repo#7``") == 2


def test_link_text_counts_once_and_its_target_never() -> None:
    assert count("[#962](https://github.com/o/r/issues/962)") == 1
    assert count("[the design](https://github.com/o/r/issues/962#issuecomment-5)") == 0
    assert count("![#9](img/9.png)") == 1


def test_urls_autolinks_and_reference_definitions_are_blanked() -> None:
    text = (
        "https://github.com/o/r/pull/12#discussion\n"
        "<https://example.com/page#34>\n"
        "[ref]: https://example.com/#56\n"
        "http://x/#78 then #9\n"
    )
    assert [m.text.split()[0] for m in dr.scan_text(text)] == ["#9"]


def test_a_url_does_not_hide_a_later_reference_on_the_line() -> None:
    assert count("https://example.com/a#1 and then #2") == 1


def test_several_references_on_one_line_count_separately() -> None:
    assert count("#1, #2 and #3") == 3


def test_allow_refs_matches_the_text_as_written_and_nothing_looser() -> None:
    allow = ("fleet-config#178",)
    assert count("see fleet-config#178", allow) == 0
    assert count("see #178", allow) == 1  # a different spelling is not allowed
    assert count("see other-repo#178", allow) == 1
    assert count("see fleet-config#1789", allow) == 1
    assert count("see fleet-config#178 and fleet-config#179", allow) == 1


def test_the_marker_names_its_line_and_what_matched() -> None:
    (marker,) = dr.scan_text("one\ntwo see repo#7 here\n")
    assert (marker.line, marker.kind) == (2, "ref")
    assert marker.text.startswith("repo#7")


# ------------------------------------------------------------------ counting: fences and comments

def test_references_inside_backtick_fences_do_not_count() -> None:
    assert count("```\nFixed in #1\n```\nand #2\n") == 1


def test_references_inside_tilde_fences_do_not_count() -> None:
    assert count("~~~~\n#1\n~~~~\n#2\n") == 1


def test_a_fence_closes_only_on_the_same_character_and_at_least_the_same_length() -> None:
    assert count("````\n```\n#1\n```\n#2\n````\n#3\n") == 1  # a shorter fence is content
    assert count("~~~\n```\n#1\n```\n~~~\n#2\n") == 1  # a different character is content
    assert count("```\n#1\n`````\n#2\n") == 1  # a longer closer closes


def test_a_fence_with_an_info_string_or_inside_a_list_or_quote_hides_its_body() -> None:
    assert count("```toml {x}\n#1\n```\n") == 0
    assert count("1. step\n   ```bash\n   #1\n   ```\n2. next #2\n") == 1
    assert count("- ```py\n  #1\n  ```\n") == 0
    assert count("> ```\n> #1\n> ```\n> #2\n") == 1


def test_three_backticks_inline_are_not_a_fence() -> None:
    assert count("```code``` and #1\n#2\n") == 2


def test_references_inside_html_comments_do_not_count() -> None:
    assert count("a <!-- hidden #1 --> b #2\n") == 1
    assert count("<!--\nmulti #1\nline #2\n-->\n#3\n") == 1
    assert count("x <!-- a --> y <!-- b #1 --> z #2") == 1


def test_html_comment_marker_inside_inline_code_is_code() -> None:
    assert count("write `<!-- note -->` or `<!--` and see #1\n") == 1


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("# t\n```\nnever closed #1\n", id="unclosed-backtick-fence"),
        pytest.param("~~~\nnever closed\n", id="unclosed-tilde-fence"),
        pytest.param("````\n```\n", id="shorter-closer-leaves-it-open"),
        pytest.param("text\n<!-- never closed #1\n", id="unclosed-html-comment"),
    ],
)
def test_an_unclosed_block_is_not_confirmed(src: str) -> None:
    with pytest.raises(dr.NotConfirmed):
        dr.scan_text(src)


# ------------------------------------------------------------------ counting: headings

def test_a_dated_heading_counts_once_and_prose_dates_do_not() -> None:
    assert kinds("## Go / no-go decision (2026-06-24)\n") == ["dated-heading"]
    assert kinds("### 2026-06-24 walk log\n") == ["dated-heading"]
    assert kinds("# Title\nRotate the cert before 2026-12-01.\n- as of 2026-10-22 it works\n") == []
    assert kinds("| 2026-06-24 | row |\n") == []


def test_only_valid_iso_dates_in_headings_count() -> None:
    assert kinds("## Build 2026-13-45\n") == []
    assert kinds("## Order 12026-06-241\n") == []


@pytest.mark.parametrize(
    "heading",
    [
        "## Changelog",
        "# CHANGELOG",
        "### 3.2 Release notes",
        "## Release history",
        "## What's new",
        "## What’s new in 2.0",
        "## 📝 Changelog",
    ],
)
def test_a_changelog_heading_counts(heading: str) -> None:
    assert kinds(heading + "\n") == ["changelog-heading"]


def test_a_changelog_heading_with_a_date_counts_once() -> None:
    assert kinds("## Changelog 2026-06-24\n") == ["changelog-heading"]


@pytest.mark.parametrize(
    "line",
    ["## Why there is no changelog", "## Timeline", "## History of the board", "Changelog", "    # Release notes"],
)
def test_other_headings_and_plain_text_do_not_count(line: str) -> None:
    assert kinds(line + "\n") == []


def test_headings_inside_a_fence_or_comment_do_not_count() -> None:
    assert kinds("```\n## Changelog\n```\n<!--\n## 2026-01-01\n-->\n") == []


def test_crlf_text_scans_like_lf() -> None:
    assert count("a #1\r\n```\r\n#2\r\n```\r\n#3\r\n") == 2


# ------------------------------------------------------------------ scope

@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("README.md", True),
        ("docs/a.md", True),
        ("docs/deep/er/a.md", True),
        ("docs/a.MD", True),
        ("docs/a.txt", False),
        ("CLAUDE.md", False),
        ("sub/README.md", False),
        ("tests/notes.md", False),
        ("docs/node_modules/x.md", False),
        ("docs/.venv/x.md", False),
    ],
)
def test_default_scope(path: str, expected: bool) -> None:
    cfg = dr.parse_config("[docs_ratchet]\nenabled = true\n")
    assert cfg is not None
    assert dr.in_scope(path, cfg, ()) is expected


def test_include_exclude_and_vendored_narrow_the_scope() -> None:
    cfg = dr.parse_config('[docs_ratchet]\nenabled = true\ninclude = ["docs/"]\nexclude = ["docs/reports/**"]\n')
    assert cfg is not None
    assert not dr.in_scope("README.md", cfg, ())
    assert dr.in_scope("docs/a.md", cfg, ())
    assert not dr.in_scope("docs/reports/2026-01-01/run.md", cfg, ())
    assert not dr.in_scope("docs/vendored/a.md", cfg, ("docs/vendored",))


def test_generated_marker_in_the_first_lines() -> None:
    assert dr.is_generated("<!-- DO NOT EDIT -->\n# x\n")
    assert dr.is_generated("# x\n@generated\n")
    assert not dr.is_generated("# x\nDo NOT edit this file per-app\n")
    assert not dr.is_generated("\n" * 6 + "DO NOT EDIT\n")


# ------------------------------------------------------- ratchet on a git repo

def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, creationflags=NO_WINDOW)


def write(root: Path, rel: str, text: str, *, track: bool = True) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    if track:
        git(root, "add", "-f", rel)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the stage enabled (20-byte budget) and one reference in `docs/a.md`."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text("[docs_ratchet]\nenabled = true\nreadme_max_bytes = 20\n", encoding="utf-8")
    write(tmp_path, "README.md", "# App\n")
    write(tmp_path, "docs/a.md", "Added in #1\n")
    return tmp_path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return dr.run(root, init=init, update=update, allow_additions=allow)


def baseline_text(root: Path) -> str:
    return (root / dr.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_init_writes_a_per_file_baseline_and_never_overwrites(repo: Path) -> None:
    write(repo, "docs/b.md", "#2 and #3\n")
    assert run_mode(repo, init=True) == dr.EXIT_PASS
    assert baseline_text(repo) == (
        '{\n  "version": 1,\n  "entries": [\n'
        '    {"key": "docs/a.md", "markers": 1},\n    {"key": "docs/b.md", "markers": 2}\n  ]\n}\n'
    )
    assert run_mode(repo, init=True) == dr.EXIT_CONFIG


def test_unchanged_tree_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    assert run_mode(repo) == dr.EXIT_PASS
    out = capsys.readouterr().out
    assert "PASS" in out
    assert "README 6 of 20 bytes" in out


def test_a_new_marker_fails_and_names_file_kind_and_counts(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "docs/a.md", "Added in #1\n## Round 2026-06-24\nAnd #5\n")
    capsys.readouterr()
    assert run_mode(repo) == dr.EXIT_RISE
    out = capsys.readouterr().out
    assert "docs/a.md: 3 history marker(s) (baseline 1)" in out
    assert "line 2: dated-heading" in out
    assert "line 3: ref: #5" in out


def test_a_new_file_with_a_marker_fails_even_if_another_file_shrank(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "docs/a.md", "clean\n")
    write(repo, "docs/new.md", "see #9\n")
    capsys.readouterr()
    assert run_mode(repo) == dr.EXIT_RISE
    assert "docs/new.md: 1 history marker(s) (baseline none -- not baselined)" in capsys.readouterr().out


def test_a_new_file_without_markers_passes(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "docs/new.md", "# Present tense\n")
    assert run_mode(repo) == dr.EXIT_PASS


def test_a_removed_marker_passes_with_a_shrink_hint(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "docs/a.md", "clean\n")
    capsys.readouterr()
    assert run_mode(repo) == dr.EXIT_PASS
    assert "below the baseline" in capsys.readouterr().out


def test_update_baseline_lowers_and_drops(repo: Path) -> None:
    write(repo, "docs/b.md", "#2 and #3\n")
    run_mode(repo, init=True)
    write(repo, "docs/b.md", "just #2\n")
    write(repo, "docs/a.md", "clean\n")
    assert run_mode(repo, update=True) == dr.EXIT_PASS
    assert baseline_text(repo) == '{\n  "version": 1,\n  "entries": [\n    {"key": "docs/b.md", "markers": 1}\n  ]\n}\n'


def test_update_baseline_refuses_a_rise_and_writes_nothing(repo: Path) -> None:
    run_mode(repo, init=True)
    before = baseline_text(repo)
    write(repo, "docs/a.md", "#1 #2\n")
    assert run_mode(repo, update=True) == dr.EXIT_RISE
    assert baseline_text(repo) == before


def test_allow_additions_raises_the_baseline(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "docs/a.md", "#1 #2\n")
    write(repo, "docs/new.md", "#3\n")
    assert run_mode(repo, update=True, allow=True) == dr.EXIT_PASS
    assert '{"key": "docs/a.md", "markers": 2}' in baseline_text(repo)
    assert '{"key": "docs/new.md", "markers": 1}' in baseline_text(repo)
    assert run_mode(repo) == dr.EXIT_PASS


def test_missing_baseline_fails_instead_of_passing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo) == dr.EXIT_RISE
    assert "is missing" in capsys.readouterr().out


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"version": 2, "entries": []}',
        '{"version": 1}',
        '{"version": 1, "entries": [{"key": "a.md", "markers": 0}]}',
        '{"version": 1, "entries": [{"key": "a.md", "markers": -1}]}',
        '{"version": 1, "entries": [{"key": "a.md", "markers": true}]}',
        '{"version": 1, "entries": [{"key": "a.md", "markers": 1, "bytes": 0}]}',
        '{"version": 1, "entries": [{"markers": 1}]}',
    ],
)
def test_unreadable_baseline_exits_two(repo: Path, text: str) -> None:
    (repo / dr.DEFAULT_BASELINE).write_text(text, encoding="utf-8")
    assert run_mode(repo) == dr.EXIT_CONFIG


def test_disabled_or_absent_stage_exits_zero_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path) == dr.EXIT_PASS
    assert "not enabled" in capsys.readouterr().out
    assert run_mode(tmp_path, init=True) == dr.EXIT_CONFIG  # nothing to write for an undeclared stage


def test_malformed_table_or_toml_exits_two(tmp_path: Path) -> None:
    (tmp_path / ".fleet.toml").write_text("[docs_ratchet]\nenabled = true\nbogus = 1\n", encoding="utf-8")
    assert run_mode(tmp_path) == dr.EXIT_CONFIG
    (tmp_path / ".fleet.toml").write_text("[docs_ratchet\n", encoding="utf-8")
    assert run_mode(tmp_path) == dr.EXIT_CONFIG
    (tmp_path / ".fleet.toml").unlink()
    assert run_mode(tmp_path) == dr.EXIT_CONFIG


def test_other_files_vendored_generated_and_untracked_are_not_counted(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "CLAUDE.md", "see #1 #2\n")
    write(repo, "sub/README.md", "#3\n")
    write(repo, "docs/notes.txt", "#4\n")
    write(repo, "docs/gen.md", "<!-- DO NOT EDIT -->\n#5\n")
    write(repo, "docs/untracked.md", "#6\n", track=False)
    write(repo, "docs/vendor/v.md", "#7\n")
    (repo / ".fleet.toml").write_text(
        '[docs_ratchet]\nenabled = true\nreadme_max_bytes = 20\n[vendored]\nx = { src = "s", dest = "docs/vendor" }\n',
        encoding="utf-8",
    )
    assert run_mode(repo) == dr.EXIT_PASS


def test_exclude_and_include_limit_the_tree(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "docs/reports/run.md", "## 2026-06-24\n#5\n")
    assert run_mode(repo) == dr.EXIT_RISE
    (repo / ".fleet.toml").write_text(
        '[docs_ratchet]\nenabled = true\nreadme_max_bytes = 20\nexclude = ["docs/reports/**"]\n', encoding="utf-8"
    )
    assert run_mode(repo) == dr.EXIT_PASS


def test_allow_refs_in_the_config_keeps_a_pointer_out_of_the_count(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(
        '[docs_ratchet]\nenabled = true\nreadme_max_bytes = 20\nallow_refs = ["fleet-config#178"]\n', encoding="utf-8"
    )
    write(repo, "docs/a.md", "Design: fleet-config#178\n")
    assert run_mode(repo, init=True) == dr.EXIT_PASS
    assert baseline_text(repo) == '{\n  "version": 1,\n  "entries": []\n}\n'
    write(repo, "docs/a.md", "Design: fleet-config#178 and #5\n")
    assert run_mode(repo) == dr.EXIT_RISE


def test_crlf_and_bom_files_are_counted_like_lf(repo: Path) -> None:
    (repo / "docs" / "crlf.md").write_bytes(b"\xef\xbb\xbfa #1\r\n```\r\n#2\r\n```\r\n#3\r\n")
    git(repo, "add", "docs/crlf.md")
    run_mode(repo, init=True)
    assert '{"key": "docs/crlf.md", "markers": 2}' in baseline_text(repo)


def test_a_tracked_file_deleted_from_the_tree_is_skipped(repo: Path) -> None:
    run_mode(repo, init=True)
    (repo / "docs" / "a.md").unlink()
    assert run_mode(repo) == dr.EXIT_PASS


# ------------------------------------------------------- README size budget

def readme_bytes(root: Path, size: int, *, crlf: bool = False) -> None:
    body = "x" * (size - 1)
    data = (body + ("\r\n" if crlf else "\n")).encode()
    (root / "README.md").write_bytes(data)
    git(root, "add", "README.md")


def test_a_readme_under_budget_needs_no_entry(repo: Path) -> None:
    readme_bytes(repo, 20)
    run_mode(repo, init=True)
    assert "README.md" not in baseline_text(repo)
    assert run_mode(repo) == dr.EXIT_PASS


def test_a_readme_growing_past_the_budget_fails_by_name(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    readme_bytes(repo, 21)
    capsys.readouterr()
    assert run_mode(repo) == dr.EXIT_RISE
    assert "README.md: 21 bytes, over the 20-byte budget (not baselined)" in capsys.readouterr().out


def test_an_over_budget_readme_is_baselined_and_may_only_shrink(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    readme_bytes(repo, 100)
    run_mode(repo, init=True)
    assert '{"key": "README.md", "markers": 0, "bytes": 100}' in baseline_text(repo)
    assert run_mode(repo) == dr.EXIT_PASS
    readme_bytes(repo, 101)
    capsys.readouterr()
    assert run_mode(repo) == dr.EXIT_RISE
    assert "README.md: 101 bytes, over the 20-byte budget (baseline 100 bytes)" in capsys.readouterr().out
    readme_bytes(repo, 60)
    assert run_mode(repo) == dr.EXIT_PASS
    assert "below the baseline" in capsys.readouterr().out
    assert run_mode(repo, update=True) == dr.EXIT_PASS
    assert '"bytes": 60' in baseline_text(repo)


def test_a_readme_back_under_budget_drops_its_size_entry(repo: Path) -> None:
    readme_bytes(repo, 100)
    run_mode(repo, init=True)
    readme_bytes(repo, 20)
    assert run_mode(repo, update=True) == dr.EXIT_PASS
    assert "README.md" not in baseline_text(repo)


def test_update_baseline_refuses_a_readme_that_grew(repo: Path) -> None:
    readme_bytes(repo, 100)
    run_mode(repo, init=True)
    before = baseline_text(repo)
    readme_bytes(repo, 150)
    assert run_mode(repo, update=True) == dr.EXIT_RISE
    assert baseline_text(repo) == before
    assert run_mode(repo, update=True, allow=True) == dr.EXIT_PASS
    assert '"bytes": 150' in baseline_text(repo)


def test_readme_markers_and_size_are_tracked_independently(repo: Path) -> None:
    write(repo, "README.md", "see #1\n" + "x" * 100)
    run_mode(repo, init=True)
    assert '{"key": "README.md", "markers": 1, "bytes": 107}' in baseline_text(repo)
    write(repo, "README.md", "see #1\n" + "x" * 90)
    assert run_mode(repo) == dr.EXIT_PASS
    write(repo, "README.md", "see #1 #2\n" + "x" * 50)
    assert run_mode(repo) == dr.EXIT_RISE


def test_readme_size_is_measured_after_crlf_normalisation(repo: Path) -> None:
    readme_bytes(repo, 20, crlf=True)  # 21 raw bytes, 20 once the CR is dropped
    assert run_mode(repo, init=True) == dr.EXIT_PASS
    assert "README.md" not in baseline_text(repo)


def test_a_generated_or_out_of_scope_readme_has_no_budget(repo: Path) -> None:
    write(repo, "README.md", "<!-- DO NOT EDIT -->\n" + "x" * 100)
    assert run_mode(repo, init=True) == dr.EXIT_PASS
    assert "README.md" not in baseline_text(repo)


# ------------------------------------------------------- not confirmed

@pytest.mark.parametrize(
    ("rel", "text"),
    [
        pytest.param("docs/bad.md", "```\nnever closed\n", id="unclosed-fence"),
        pytest.param("README.md", "<!-- never closed\n", id="unclosed-html-comment"),
    ],
)
def test_a_file_the_scanner_cannot_finish_is_not_confirmed_in_every_mode(
    repo: Path, rel: str, text: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run_mode(repo, init=True)
    write(repo, rel, text)
    for kwargs in ({}, {"update": True}, {"update": True, "allow": True}):
        assert run_mode(repo, **kwargs) == dr.EXIT_NOT_CONFIRMED
        out = capsys.readouterr().out
        assert "NOT CONFIRMED" in out
        assert rel in out
    (repo / dr.DEFAULT_BASELINE).unlink()
    assert run_mode(repo, init=True) == dr.EXIT_NOT_CONFIRMED
    assert not (repo / dr.DEFAULT_BASELINE).exists()


def test_undecodable_bytes_are_not_confirmed(repo: Path) -> None:
    run_mode(repo, init=True)
    (repo / "docs" / "latin.md").write_bytes(b"caf\xe9 #1\n")
    git(repo, "add", "docs/latin.md")
    assert run_mode(repo) == dr.EXIT_NOT_CONFIRMED


def test_git_that_cannot_list_files_is_not_confirmed(repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    monkeypatch.setenv("GIT_DIR", str(repo / "no-such-git-dir"))
    assert run_mode(repo) == dr.EXIT_NOT_CONFIRMED
    assert "git ls-files" in capsys.readouterr().out


def test_a_missing_git_binary_is_not_confirmed(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_mode(repo, init=True)
    monkeypatch.setenv("PATH", str(repo / "empty"))
    assert run_mode(repo) == dr.EXIT_NOT_CONFIRMED


def test_main_rejects_allow_additions_without_update(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        dr.main(["--allow-additions"])
    assert exc.value.code == 2
    assert "--allow-additions" in capsys.readouterr().err


# ------------------------------------------------------------ self-adoption

def test_scaffold_adopts_the_stage_and_commits_a_parseable_baseline() -> None:
    cfg, _ = dr.load_config(REPO_ROOT)
    assert cfg is not None, "the scaffold adopts its own stage first"
    assert (REPO_ROOT / cfg.baseline).is_file()
    dr.read_baseline(REPO_ROOT / cfg.baseline)


def test_the_new_docs_follow_their_own_rule() -> None:
    for rel in ("docs/readme-and-docs.md", "docs/docs-ratchet.md"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert dr.scan_text(text) == [], f"{rel} must carry no history marker"


def test_gate_runs_the_stage_after_the_comment_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    comment, stage, mypy = (text.index(s) for s in ('Invoke-Stage "comment ratchet"', 'Invoke-Stage "docs ratchet"', 'Invoke-Stage "mypy'))
    assert comment < stage < mypy
    assert "scripts/docs_ratchet.py" in text


def test_the_script_is_catalogued_so_it_is_mypy_gated_and_drift_checked() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["docs_ratchet"] == {"src": "scripts/docs_ratchet.py"}
