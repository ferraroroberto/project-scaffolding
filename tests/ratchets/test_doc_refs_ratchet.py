"""Tests for the doc-references ratchet.

Three layers, mirroring `test_docs_ratchet.py`:

1. **Extraction and resolution** on fixture strings: which inline code spans,
   links and ports count as references, which are skipped (placeholders, other
   owners, URLs, fences, comments), and what a reference resolves to.
2. **Ratchet behaviour** on throwaway git repos: a new dangling reference fails
   and names the file, line and reference; the port check against `.fleet.toml`;
   every mode; and the "not confirmed" exit for anything that cannot be resolved.
   A missing prerequisite is a hard failure, never `pytest.skip`.
3. **Self-adoption** -- this repo's own declaration and gate wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import doc_refs_ratchet as dr
from tests._git_repo import git, write
from tests._ratchet_not_confirmed import (
    GIT_FAILURES,
    assert_unlistable_git_not_confirmed,
    assert_unreadable_file_not_confirmed,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TOP = frozenset({"scripts", "docs", "src", "tests"})


def keys(text: str, doc: str = "README.md", *, ports: bool = True, root_py: frozenset[str] = frozenset()) -> list[str]:
    return [r.key for r in dr.scan_text(text, doc, TOP, root_py, check_ports=ports)]


# ------------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert dr.parse_config('layer = "x"\n') is None
    assert dr.parse_config("[doc_refs_ratchet]\nenabled = false\n") is None
    assert dr.parse_config("[doc_refs_ratchet]\n") is None  # opting in is explicit


def test_enabled_table_gets_the_documented_defaults() -> None:
    assert dr.parse_config("[doc_refs_ratchet]\nenabled = true\n") == dr.Config(
        ".doc-refs-ratchet-baseline.json", ("README.md", "CLAUDE.md", "docs/"), (), ()
    )


def test_enabled_table_honours_every_key() -> None:
    cfg = dr.parse_config(
        '[doc_refs_ratchet]\nenabled = true\nbaseline = "b.json"\ninclude = ["README.md"]\n'
        'exclude = ["docs/gen/**"]\nallow_refs = ["docs/layout.md", ":8000"]\n'
    )
    assert cfg == dr.Config("b.json", ("README.md",), ("docs/gen/**",), ("docs/layout.md", ":8000"))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("enabled = true\nbaselin = 'x'\n", id="typo-in-key"),
        pytest.param('enabled = "yes"\n', id="enabled-not-bool"),
        pytest.param("enabled = true\nbaseline = ''\n", id="empty-baseline"),
        pytest.param("enabled = true\ninclude = 'docs/'\n", id="include-not-a-list"),
        pytest.param("enabled = true\nexclude = [1]\n", id="exclude-not-strings"),
        pytest.param("enabled = true\nallow_refs = 'x'\n", id="allow-refs-not-a-list"),
    ],
)
def test_malformed_table_fails_loud(body: str) -> None:
    with pytest.raises(dr.ConfigError):
        dr.parse_config("[doc_refs_ratchet]\n" + body)


@pytest.mark.parametrize(
    ("toml", "port"),
    [('layer = "x"\n', None), ("port = 8447\n", 8447), ('port = ":8447"\n', 8447), ('port = "8502"\n', 8502)],
)
def test_the_declared_port_reads_both_fleet_shapes(toml: str, port: int | None) -> None:
    assert dr.declared_port(toml) == port


@pytest.mark.parametrize("toml", ['port = "eight"\n', "port = 0\n", "port = 70000\n", "port = true\n"])
def test_a_malformed_port_fails_loud(toml: str) -> None:
    with pytest.raises(dr.ConfigError):
        dr.declared_port(toml)


# ---------------------------------------------------------- inline code paths

def test_a_path_under_a_tracked_top_folder_is_a_reference() -> None:
    assert keys("Run `scripts/gate.ps1` and read `docs/x.md`.") == ["scripts/gate.ps1", "docs/x.md"]


def test_a_path_whose_first_segment_is_not_a_tracked_folder_is_not_read() -> None:
    assert keys("`skills/_lib/x.py`, `node_modules/a/b.js`, `foo.py`, `README.md`") == []


def test_every_token_of_a_command_span_is_read() -> None:
    assert keys(r"`& .\.venv\Scripts\python.exe .\scripts\gate.py --root docs/`") == ["scripts/gate.py", "docs"]


@pytest.mark.parametrize(
    "span",
    [
        "src/<name>.py", "tests/*.py", "docs/{a,b}.md", "scripts/$TOOL", "docs/…", "src/app/...",
        "/scripts/x.py", "~/docs/x.md", "C:/src/x.py", "docs/../x.md", "https://x.dev/docs/a.md",
    ],
)
def test_templates_globs_absolute_and_urls_are_not_literal_paths(span: str) -> None:
    assert keys(f"`{span}`") == []


@pytest.mark.parametrize(
    ("span", "key"),
    [
        ("scripts/x.py:12", "scripts/x.py"),
        ("scripts/x.py:12-30", "scripts/x.py"),
        ("scripts/x.py#L4", "scripts/x.py"),
        ("src/x.py:parse_spoken", "src/x.py"),
        ("tests/test_a.py::test_b[param-1]", "tests/test_a.py"),
        ("./scripts/x.py", "scripts/x.py"),
        ("docs/", "docs"),
    ],
)
def test_line_symbol_and_test_id_suffixes_are_not_part_of_the_path(span: str, key: str) -> None:
    assert keys(f"`{span}`") == [key]


@pytest.mark.parametrize(
    "line",
    [
        "`fleet-config`'s `docs/a.md`",
        "the scaffold's `docs/a.md`",
        "see its `docs/a.md`",
        "fleet-config’s [`docs/a.md`](https://example.com)",
        "contract: local-llm-hub `docs/a.md`",
        "| task-os | `src/a.py:12` | what it does |",
    ],
)
def test_a_span_named_as_another_owners_is_not_read(line: str) -> None:
    assert keys(line) == []


def test_a_possessive_wrapped_onto_the_previous_line_still_qualifies() -> None:
    assert keys("Copy from `home-automation`'s\n`scripts/x.py` verbatim.") == []
    assert keys("A sentence ends here.\n`scripts/x.py` is ours.") == ["scripts/x.py"]


def test_python_dash_m_reads_only_modules_this_repo_owns() -> None:
    text = "`python -m src.tool --x` and `python -m pytest` and `python -m main`"
    assert keys(text, root_py=frozenset({"main"})) == ["-m src.tool", "-m main"]


# --------------------------------------------------------------------- links

def test_relative_links_resolve_from_the_docs_own_folder() -> None:
    text = "[a](b.md) [b](../README.md) [c](/scripts/x.py) ![i](img/a.png) [d](sub/c.md#part)"
    assert keys(text, "docs/guide.md") == ["docs/b.md", "README.md", "scripts/x.py", "docs/img/a.png", "docs/sub/c.md"]


def test_reference_definitions_and_html_attributes_are_links() -> None:
    assert keys('[x]: docs/a.md\n<img src="docs/b.png"> <a href=\'c.md\'>') == ["docs/a.md", "docs/b.png", "c.md"]


@pytest.mark.parametrize(
    "link",
    ["[a](https://x.dev/a.md)", "[a](#anchor)", "[a](mailto:x@y.z)", "[a](../../other-repo/x.md)", "[a](<x>.md)"],
)
def test_urls_anchors_and_links_that_leave_the_repo_are_not_read(link: str) -> None:
    assert keys(link, "docs/a.md") == []


def test_link_targets_are_url_decoded() -> None:
    assert keys("[a](my%20file.md)") == ["my file.md"]


# --------------------------------------------------------------------- ports

def test_loopback_and_bare_inline_ports_are_references() -> None:
    text = "Open http://127.0.0.1:8447/x, `localhost:8000`, `:8090`; version 1:20 and `a:1234` are not ports"
    assert keys(text) == [":8000", ":8447", ":8090"]


def test_ports_are_not_read_when_the_check_is_off() -> None:
    assert keys("`127.0.0.1:8000`", ports=False) == []


# ------------------------------------------------------------ blocks + refs

def test_fences_and_html_comments_hide_their_content() -> None:
    text = "```bash\npython scripts/a.py\n```\n~~~\n`scripts/b.py`\n~~~\n<!-- `scripts/c.py`\n-->\n`scripts/d.py`"
    assert keys(text) == ["scripts/d.py"]


@pytest.mark.parametrize("src", ["```\n`scripts/a.py`\n", "<!-- open\n`scripts/a.py`\n"])
def test_an_unclosed_block_is_not_confirmed(src: str) -> None:
    with pytest.raises(dr.NotConfirmed, match="never closes"):
        dr.scan_text(src, "README.md", TOP)


def test_the_reference_names_its_line_kind_and_context() -> None:
    (ref,) = dr.scan_text("intro\nsee `docs/x.md` here", "README.md", TOP)
    assert (ref.line, ref.kind, ref.key, ref.text) == (2, "path", "docs/x.md", "see `docs/x.md` here")


def test_crlf_text_scans_like_lf() -> None:
    assert keys("a\r\n`docs/x.md`\r\n") == ["docs/x.md"]


# ----------------------------------------------------------------- resolve

TREE = dr.build_tree(["scripts/tool.py", "src/pkg/__init__.py", "src/mod.py", "src/cli/__main__.py", "docs/a.md"], 8447)


@pytest.mark.parametrize(
    ("kind", "key", "ok"),
    [
        ("path", "scripts/tool.py", True),
        ("path", "src/pkg", True),
        ("path", "scripts/tool", True),
        ("path", "src/mod.parse", True),
        ("path", "src/pkg.helper", True),
        ("path", "scripts/gone.py", False),
        ("path", "docs/a.md.bak", False),
        ("link", "scripts/tool", False),
        ("module", "-m src.mod", True),
        ("module", "-m src.pkg", True),
        ("module", "-m src.cli", True),
        ("module", "-m src.gone", False),
        ("port", ":8447", True),
        ("port", ":8000", False),
    ],
)
def test_what_a_reference_resolves_to(kind: str, key: str, ok: bool) -> None:
    assert dr.resolves(dr.Ref(1, kind, key, ""), TREE) is ok


def test_no_declared_port_means_every_port_resolves() -> None:
    assert dr.resolves(dr.Ref(1, "port", ":1", ""), dr.build_tree([], None))


def test_default_scope_is_readme_claude_md_and_docs() -> None:
    cfg = dr.Config(dr.DEFAULT_BASELINE, dr.DEFAULT_INCLUDE, (), ())
    picked = [p for p in ("README.md", "CLAUDE.md", "docs/a.md", "docs/x/b.md", "src/README.md", "docs/a.txt")
              if dr.in_scope(p, cfg, ())]
    assert picked == ["README.md", "CLAUDE.md", "docs/a.md", "docs/x/b.md"]


# ------------------------------------------------------- ratchet on a git repo

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the stage enabled, one real script and one dangling reference."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text("[doc_refs_ratchet]\nenabled = true\n", encoding="utf-8")
    write(tmp_path, "scripts/real.py", "")
    write(tmp_path, "README.md", "Run `scripts/real.py`, not `scripts/old.py`.\n")
    return tmp_path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return dr.run(root, init=init, update=update, allow_additions=allow)


def baseline_text(root: Path) -> str:
    return (root / dr.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_init_records_each_dangling_reference_and_never_overwrites(repo: Path) -> None:
    write(repo, "docs/a.md", "[x](gone.md) and [y](gone.md)\n")
    assert run_mode(repo, init=True) == dr.EXIT_PASS
    assert baseline_text(repo) == (
        '{\n  "version": 1,\n  "entries": [\n'
        '    {"key": "README.md", "refs": ["scripts/old.py"]},\n'
        '    {"key": "docs/a.md", "refs": ["docs/gone.md", "docs/gone.md"]}\n  ]\n}\n'
    )
    assert run_mode(repo, init=True) == dr.EXIT_CONFIG


def test_unchanged_tree_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    assert run_mode(repo) == dr.EXIT_PASS
    assert "PASS (1 baselined" in capsys.readouterr().out


def test_a_new_dangling_path_fails_by_name(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "docs/guide.md", "intro\nThen run `scripts/missing.py --x`.\n")
    capsys.readouterr()
    assert run_mode(repo) == dr.EXIT_RISE
    out = capsys.readouterr().out
    assert "docs/guide.md:2: path `scripts/missing.py` does not exist" in out
    assert "allow_refs" in out


def test_swapping_one_dangling_reference_for_another_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "README.md", "Run `scripts/real.py`, not `scripts/older.py`.\n")
    assert run_mode(repo) == dr.EXIT_RISE
    assert "`scripts/older.py`" in capsys.readouterr().out


def test_a_second_copy_of_a_baselined_reference_fails(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "README.md", "`scripts/old.py` and again `scripts/old.py`\n")
    assert run_mode(repo) == dr.EXIT_RISE


def test_a_fixed_reference_passes_with_a_shrink_hint(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "README.md", "Run `scripts/real.py`.\n")
    assert run_mode(repo) == dr.EXIT_PASS
    assert "--update-baseline" in capsys.readouterr().out


def test_update_baseline_drops_what_resolves(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "scripts/old.py", "")
    assert run_mode(repo, update=True) == dr.EXIT_PASS
    assert dr.read_baseline(repo / dr.DEFAULT_BASELINE) == {}


def test_update_baseline_refuses_an_addition_and_writes_nothing(repo: Path) -> None:
    run_mode(repo, init=True)
    before = baseline_text(repo)
    write(repo, "docs/new.md", "`scripts/nope.py`\n")
    assert run_mode(repo, update=True) == dr.EXIT_RISE
    assert baseline_text(repo) == before


def test_allow_additions_adds_to_the_baseline(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "docs/new.md", "`scripts/nope.py`\n")
    assert run_mode(repo, update=True, allow=True) == dr.EXIT_PASS
    assert dr.read_baseline(repo / dr.DEFAULT_BASELINE)["docs/new.md"] == {"scripts/nope.py": 1}
    assert run_mode(repo) == dr.EXIT_PASS


def test_missing_baseline_fails_instead_of_passing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo) == dr.EXIT_RISE
    assert "--init" in capsys.readouterr().out


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"version": 2, "entries": []}',
        '{"version": 1, "entries": {}}',
        '{"version": 1, "entries": [{"key": "README.md"}]}',
        '{"version": 1, "entries": [{"key": "README.md", "refs": []}]}',
        '{"version": 1, "entries": [{"key": "README.md", "refs": [1]}]}',
    ],
)
def test_unreadable_baseline_exits_two(repo: Path, text: str) -> None:
    (repo / dr.DEFAULT_BASELINE).write_text(text, encoding="utf-8")
    assert run_mode(repo) == dr.EXIT_CONFIG


def test_disabled_or_absent_stage_exits_zero_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path) == dr.EXIT_PASS
    assert "not enabled" in capsys.readouterr().out
    assert run_mode(tmp_path, init=True) == dr.EXIT_CONFIG


def test_malformed_table_toml_or_port_exits_two(tmp_path: Path) -> None:
    for text in ("[doc_refs_ratchet]\nenabled = 1\n", "not = [valid", 'port = "x"\n[doc_refs_ratchet]\nenabled = true\n'):
        (tmp_path / ".fleet.toml").write_text(text, encoding="utf-8")
        assert run_mode(tmp_path) == dr.EXIT_CONFIG


def test_a_gitignored_path_or_folder_is_machine_local_not_dangling(repo: Path) -> None:
    write(repo, ".gitignore", "scripts/local.json\nscripts/certs/*\n")
    run_mode(repo, init=True)
    write(repo, "docs/a.md", "`scripts/local.json` and `scripts/certs/`\n")
    assert run_mode(repo) == dr.EXIT_PASS


def test_allow_refs_globs_keep_intentional_pointers_out(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(
        '[doc_refs_ratchet]\nenabled = true\nallow_refs = ["scripts/old.py", "docs/adopter/**"]\n', encoding="utf-8"
    )
    write(repo, "docs/a.md", "Create `docs/adopter/layout.md`.\n")
    assert run_mode(repo, init=True) == dr.EXIT_PASS
    assert dr.read_baseline(repo / dr.DEFAULT_BASELINE) == {}


def test_vendored_generated_and_out_of_scope_files_are_not_read(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(
        '[doc_refs_ratchet]\nenabled = true\n[vendored]\nx = { src = "a", dest = "docs/vendored" }\n', encoding="utf-8"
    )
    run_mode(repo, init=True)
    write(repo, "docs/vendored/x.md", "`scripts/b.py`\n")
    write(repo, "docs/gen.md", "<!-- DO NOT EDIT -->\n`scripts/c.py`\n")
    write(repo, "src/README.md", "`scripts/d.py`\n")
    assert run_mode(repo) == dr.EXIT_PASS


def test_claude_md_is_read_by_default(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "CLAUDE.md", "Gate: `scripts/verify.ps1`.\n")
    assert run_mode(repo) == dr.EXIT_RISE


def test_a_tracked_file_deleted_from_the_tree_counts_as_dangling(repo: Path) -> None:
    write(repo, "scripts/other.py", "")  # keeps `scripts` a tracked top folder once real.py is gone
    run_mode(repo, init=True)
    (repo / "scripts" / "real.py").unlink()
    assert run_mode(repo) == dr.EXIT_PASS  # git still tracks it: the index is the tree of record
    git(repo, "rm", "-q", "--cached", "scripts/real.py")
    assert run_mode(repo) == dr.EXIT_RISE


# ------------------------------------------------------------------ ports

def test_a_doc_port_other_than_the_declared_one_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / ".fleet.toml").write_text('port = ":8447"\n[doc_refs_ratchet]\nenabled = true\n', encoding="utf-8")
    write(repo, "docs/run.md", "Open http://127.0.0.1:8447/.\n")
    run_mode(repo, init=True)
    write(repo, "docs/run.md", "Open http://127.0.0.1:8447/ or `localhost:8446`.\n")
    capsys.readouterr()
    assert run_mode(repo) == dr.EXIT_RISE
    assert "docs/run.md:1: port `:8446` does not exist" in capsys.readouterr().out


def test_a_foreign_port_in_allow_refs_passes(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(
        'port = 8447\n[doc_refs_ratchet]\nenabled = true\nallow_refs = [":8000"]\n', encoding="utf-8"
    )
    run_mode(repo, init=True)
    write(repo, "docs/run.md", "The hub on `:8000`, this app on `127.0.0.1:8447`.\n")
    assert run_mode(repo) == dr.EXIT_PASS


def test_ports_are_unchecked_without_a_declared_port(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "docs/run.md", "`localhost:9999`\n")
    assert run_mode(repo) == dr.EXIT_PASS
    assert "ports unchecked" in capsys.readouterr().out


# ------------------------------------------------------- not confirmed

@pytest.mark.parametrize(
    ("rel", "body", "says"),
    [
        pytest.param("docs/bad.md", b"`scripts/a.py`\n```\nnever closed\n", "fenced block opened on line 2", id="fence"),
        pytest.param("CLAUDE.md", b"<!-- never closed\n", "HTML comment opened on line 1", id="comment"),
        pytest.param("docs/latin.md", b"caf\xe9\n", "not valid UTF-8", id="not-utf8"),
    ],
)
def test_a_doc_that_cannot_be_read_through_is_not_confirmed_in_every_mode(
    repo: Path, rel: str, body: bytes, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert_unreadable_file_not_confirmed(
        dr, run_mode, repo, rel, body, says, capsys
    )


@pytest.mark.parametrize(("var", "value", "says"), GIT_FAILURES)
def test_git_that_cannot_list_the_tree_is_not_confirmed(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], var: str, value: str, says: str
) -> None:
    assert_unlistable_git_not_confirmed(
        dr, run_mode, repo, monkeypatch, capsys, var, value, says
    )


def test_git_that_cannot_answer_check_ignore_is_not_confirmed(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_mode(repo, init=True)
    real = dr._git

    def broken(root: Path, args: list[str], stdin: bytes | None = None) -> object:
        proc = real(root, args, stdin)
        if args[0] == "check-ignore":
            proc.returncode = 128
        return proc

    monkeypatch.setattr(dr, "_git", broken)
    assert run_mode(repo) == dr.EXIT_NOT_CONFIRMED


def test_main_rejects_allow_additions_without_update(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        dr.main(["--allow-additions"])
    assert exc.value.code == 2
    assert "--allow-additions" in capsys.readouterr().err


# ------------------------------------------------------------ self-adoption

def test_scaffold_adopts_the_stage_and_commits_a_parseable_baseline() -> None:
    cfg, _, _ = dr.load_config(REPO_ROOT)
    assert cfg is not None, "the scaffold adopts its own stage first"
    assert (REPO_ROOT / cfg.baseline).is_file()
    dr.read_baseline(REPO_ROOT / cfg.baseline)


def test_the_stage_doc_has_no_dangling_reference() -> None:
    cfg, vendored, port = dr.load_config(REPO_ROOT)
    assert cfg is not None
    assert "docs/doc-refs-ratchet.md" not in dr.dangling_tree(REPO_ROOT, cfg, vendored, port)


def test_gate_runs_the_stage_after_the_instruction_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    before, stage, mypy = (
        text.index(s) for s in ('Invoke-Stage "instruction ratchet"', 'Invoke-Stage "doc refs ratchet"', 'Invoke-Stage "mypy')
    )
    assert before < stage < mypy
    assert "scripts/doc_refs_ratchet.py" in text


def test_the_script_is_catalogued_so_it_is_mypy_gated_and_drift_checked() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["doc_refs_ratchet"] == {"src": "scripts/doc_refs_ratchet.py"}


def test_an_untracked_file_with_a_violation_fails(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "docs/guide.md", 'Then run `scripts/missing.py`.\n', track=False)
    assert run_mode(repo) == dr.EXIT_RISE


def test_an_ignored_file_is_still_skipped(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, ".gitignore", "docs/ignored.md\n")
    write(repo, "docs/ignored.md", 'Then run `scripts/missing.py`.\n', track=False)
    assert run_mode(repo) == dr.EXIT_PASS
