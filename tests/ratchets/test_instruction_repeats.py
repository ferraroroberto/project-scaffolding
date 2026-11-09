"""Tests for the instruction ratchet's S-04 rule: CLAUDE.md text repeated from docs/ or the global file.

S-04 is off until the adopter's `[instruction_ratchet]` table sets `repeated_text_words`, so a re-vendor
never turns a repo red; once on, each run of that many shared words is one baselined hit that may only
shrink. The finder itself lives in the `instruction_repeats` sibling.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import instruction_ratchet as ir
from scripts import instruction_repeats as rep
from src.no_window import NO_WINDOW
from tests._git_repo import git, write
from tests.ratchets.test_instruction_ratchet import baseline_text, run_mode

REPO_ROOT = Path(__file__).resolve().parents[2]

N = "repeated_text_words = 12\n"
# Thirty distinct words, so a copy of any 12+ of them is a run and a copy of fewer is not.
PASSAGE = ("restart only this app by port or pid and then poll the version endpoint with a hard timeout "
           "until the served sha equals head before reporting the build as live to the owner")


def make_repo(root: Path, options: str = N, **files: str) -> Path:
    git(root, "init", "-q")
    (root / ".fleet.toml").write_text("[instruction_ratchet]\nenabled = true\n" + options, encoding="utf-8")
    for name, text in files.items():
        write(root, name.replace("__", "/"), text)
    return root


def init_text(root: Path) -> str:
    assert run_mode(root, init=True) == ir.EXIT_PASS
    return baseline_text(root)


def words(count: int, start: int = 0) -> str:
    return " ".join(PASSAGE.split()[start:start + count])


# ------------------------------------------------------------------ the finder

def lines_of(text: str) -> rep.Lines:
    return list(enumerate(text.splitlines(), 1))


def test_a_run_is_every_consecutive_shared_window_merged() -> None:
    index = rep.index_sources({"docs/a.md": lines_of(PASSAGE)}, 12)
    runs = rep.repeated_runs(lines_of("intro words here\n" + PASSAGE + "\nand then something new"), index, 12)
    assert runs == [rep.Run(2, len(PASSAGE.split()), "docs/a.md")]


def test_fewer_words_than_the_window_is_not_a_run() -> None:
    index = rep.index_sources({"docs/a.md": lines_of(PASSAGE)}, 12)
    assert rep.repeated_runs(lines_of(words(11)), index, 12) == []


def test_two_copies_apart_are_two_runs() -> None:
    index = rep.index_sources({"docs/a.md": lines_of(PASSAGE)}, 12)
    text = words(14) + "\nsomething entirely different in between these two copies of it\n" + words(14, 10)
    assert [r.line for r in rep.repeated_runs(lines_of(text), index, 12)] == [1, 3]


def test_case_markdown_marks_and_wrapping_do_not_hide_a_copy() -> None:
    index = rep.index_sources({"docs/a.md": lines_of(PASSAGE)}, 12)
    wrapped = "- **Restart** only this app, by port or PID,\n  and then poll the version\nendpoint with a *hard* timeout until the served SHA."
    assert len(rep.repeated_runs(lines_of(wrapped), index, 12)) == 1


def test_the_first_source_by_path_is_named() -> None:
    index = rep.index_sources({"docs/b.md": lines_of(PASSAGE), "docs/a.md": lines_of(PASSAGE)}, 12)
    assert rep.repeated_runs(lines_of(PASSAGE), index, 12)[0].source == "docs/a.md"


# ---------------------------------------------------------------------- config

def test_s04_is_off_by_default() -> None:
    cfg = ir.parse_config("[instruction_ratchet]\nenabled = true\n")
    assert cfg is not None
    assert (cfg.repeated_text_words, cfg.repeated_text_global) == (None, False)


def test_the_keys_are_honoured() -> None:
    cfg = ir.parse_config("[instruction_ratchet]\nenabled = true\nrepeated_text_words = 12\nrepeated_text_global = true\n")
    assert cfg is not None
    assert (cfg.repeated_text_words, cfg.repeated_text_global) == (12, True)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("repeated_text_words = 4\n", id="below-the-floor"),
        pytest.param("repeated_text_words = 0\n", id="zero"),
        pytest.param('repeated_text_words = "12"\n', id="string"),
        pytest.param("repeated_text_words = true\n", id="bool"),
        pytest.param("repeated_text_global = true\n", id="global-without-words"),
        pytest.param("repeated_text_words = 12\nrepeated_text_global = 1\n", id="global-not-bool"),
    ],
)
def test_a_malformed_key_fails_loud(body: str) -> None:
    with pytest.raises(ir.ConfigError):
        ir.parse_config("[instruction_ratchet]\nenabled = true\n" + body)


def test_an_excluded_source_is_listed_and_defaults_to_none() -> None:
    off = ir.parse_config("[instruction_ratchet]\nenabled = true\nrepeated_text_words = 12\n")
    on = ir.parse_config('[instruction_ratchet]\nenabled = true\nrepeated_text_words = 12\nrepeated_text_exclude = ["docs/m.md"]\n')
    assert off is not None and on is not None
    assert (off.repeated_text_exclude, on.repeated_text_exclude) == ((), ("docs/m.md",))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param('repeated_text_exclude = ["docs/m.md"]\n', id="exclude-without-words"),
        pytest.param('repeated_text_words = 12\nrepeated_text_exclude = "docs/m.md"\n', id="exclude-not-a-list"),
        pytest.param("repeated_text_words = 12\nrepeated_text_exclude = [1]\n", id="exclude-not-paths"),
    ],
)
def test_a_malformed_exclude_fails_loud(body: str) -> None:
    with pytest.raises(ir.ConfigError):
        ir.parse_config("[instruction_ratchet]\nenabled = true\n" + body)


def test_s04_is_a_registered_shape_rule() -> None:
    assert "S-04" in ir.SHAPE_RULES and "S-04" not in ir.RULES


# ------------------------------------------------------------------ the docs/ source

def test_without_the_option_a_repeat_is_not_counted(tmp_path: Path) -> None:
    make_repo(tmp_path, "", **{"CLAUDE.md": words(30), "docs__a.md": PASSAGE})
    assert '"entries": []' in init_text(tmp_path)


def test_text_repeated_from_docs_is_one_baselined_hit_on_claude_md(tmp_path: Path) -> None:
    make_repo(tmp_path, **{"CLAUDE.md": "# App\n\n" + PASSAGE + "\n", "docs__a.md": "# Doc\n\n" + PASSAGE + "\n"})
    assert '{"key": "CLAUDE.md", "hits": {"S-04": 1}}' in init_text(tmp_path)


def test_a_pointer_to_the_doc_is_not_a_repeat(tmp_path: Path) -> None:
    make_repo(tmp_path, **{"CLAUDE.md": "Restart procedure: see `docs/a.md` before touching the tray.\n", "docs__a.md": PASSAGE})
    assert '"entries": []' in init_text(tmp_path)


def test_eleven_shared_words_pass_and_twelve_are_a_hit(tmp_path: Path) -> None:
    make_repo(tmp_path, **{"CLAUDE.md": "x " + words(11), "docs__a.md": PASSAGE})
    assert '"entries": []' in init_text(tmp_path)
    write(tmp_path, "CLAUDE.md", "x " + words(12))
    assert run_mode(tmp_path) == ir.EXIT_RISE


def test_fenced_and_inline_code_are_not_compared(tmp_path: Path) -> None:
    claude = f"# App\n\n```text\n{PASSAGE}\n```\n\nInline: `{words(15)}` ends here.\n"
    make_repo(tmp_path, **{"CLAUDE.md": claude, "docs__a.md": PASSAGE})
    assert '"entries": []' in init_text(tmp_path)


def test_a_fenced_example_in_a_doc_is_not_a_source(tmp_path: Path) -> None:
    make_repo(tmp_path, **{"CLAUDE.md": PASSAGE + "\n", "docs__a.md": f"```text\n{PASSAGE}\n```\n"})
    assert '"entries": []' in init_text(tmp_path)


def test_only_markdown_under_docs_is_a_source(tmp_path: Path) -> None:
    make_repo(tmp_path, **{"CLAUDE.md": PASSAGE + "\n", "README.md": PASSAGE, "docs__notes.txt": PASSAGE, "src__x.md": PASSAGE})
    assert '"entries": []' in init_text(tmp_path)


def test_docs_in_a_subfolder_are_sources(tmp_path: Path) -> None:
    make_repo(tmp_path, **{"CLAUDE.md": PASSAGE + "\n", "docs__agents__p.md": PASSAGE})
    assert '"S-04": 1' in init_text(tmp_path)


def test_an_excluded_doc_is_never_a_source(tmp_path: Path) -> None:
    make_repo(tmp_path, N + 'repeated_text_exclude = ["docs/agents/master.md"]\n',
              **{"CLAUDE.md": PASSAGE + "\n", "docs__agents__master.md": PASSAGE})
    assert '"entries": []' in init_text(tmp_path)


def test_an_excluded_doc_leaves_every_other_doc_a_source(tmp_path: Path) -> None:
    make_repo(tmp_path, N + 'repeated_text_exclude = ["docs/agents/master.md"]\n',
              **{"CLAUDE.md": PASSAGE + "\n", "docs__agents__master.md": PASSAGE, "docs__a.md": PASSAGE})
    assert '"S-04": 1' in init_text(tmp_path)


def test_each_claude_md_entry_is_keyed_by_its_own_path(tmp_path: Path) -> None:
    make_repo(tmp_path, N + 'extra_files = ["docs/team-CLAUDE.md"]\n',
              **{"CLAUDE.md": "x\n", "docs__team-CLAUDE.md": PASSAGE, "docs__a.md": PASSAGE})
    text = init_text(tmp_path)
    assert '{"key": "docs/team-CLAUDE.md", "hits": {"S-04": 1}}' in text and '"key": "CLAUDE.md"' not in text


def test_a_file_is_never_compared_with_itself(tmp_path: Path) -> None:
    make_repo(tmp_path, N + 'extra_files = ["docs/team-CLAUDE.md"]\n', **{"CLAUDE.md": "x\n", "docs__team-CLAUDE.md": PASSAGE})
    assert '"entries": []' in init_text(tmp_path)


def test_an_unclosed_fence_in_a_doc_is_not_confirmed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, **{"CLAUDE.md": "x\n", "docs__a.md": "```text\nnever closed\n"})
    assert run_mode(tmp_path, init=True) == ir.EXIT_NOT_CONFIRMED
    assert "docs/a.md" in capsys.readouterr().out


# ---------------------------------------------------------------- the global source

@pytest.fixture
def global_file(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path_factory.mktemp("home") / "CLAUDE.md"
    monkeypatch.setattr(ir, "global_instructions_path", lambda: path)
    return path


def test_text_repeated_from_the_global_file_is_a_hit(tmp_path: Path, global_file: Path) -> None:
    global_file.write_text("# Global\n\n" + PASSAGE + "\n", encoding="utf-8")
    make_repo(tmp_path, N + "repeated_text_global = true\n", **{"CLAUDE.md": PASSAGE + "\n"})
    assert '{"key": "CLAUDE.md", "hits": {"S-04": 1}}' in init_text(tmp_path)


def test_the_global_file_is_ignored_unless_asked_for(tmp_path: Path, global_file: Path) -> None:
    global_file.write_text(PASSAGE, encoding="utf-8")
    make_repo(tmp_path, **{"CLAUDE.md": PASSAGE + "\n"})
    assert '"entries": []' in init_text(tmp_path)


def test_a_missing_global_file_is_not_confirmed_never_a_pass(
    tmp_path: Path, global_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path, N + "repeated_text_global = true\n", **{"CLAUDE.md": "x\n"})
    assert run_mode(tmp_path, init=True) == ir.EXIT_NOT_CONFIRMED
    assert "global" in capsys.readouterr().out and not (tmp_path / ir.DEFAULT_BASELINE).exists()


def test_the_global_file_is_not_compared_with_itself(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_repo(tmp_path, N + 'repeated_text_global = true\nextra_files = ["global-CLAUDE.md"]\n',
              **{"CLAUDE.md": "x\n", "global-CLAUDE.md": PASSAGE})
    monkeypatch.setattr(ir, "global_instructions_path", lambda: tmp_path / "global-CLAUDE.md")
    assert '"entries": []' in init_text(tmp_path)


def test_a_repo_file_that_is_the_global_file_still_answers_to_docs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_repo(tmp_path, N + 'repeated_text_global = true\nextra_files = ["global-CLAUDE.md"]\n',
              **{"CLAUDE.md": "x\n", "global-CLAUDE.md": PASSAGE, "docs__a.md": PASSAGE})
    monkeypatch.setattr(ir, "global_instructions_path", lambda: tmp_path / "global-CLAUDE.md")
    assert '{"key": "global-CLAUDE.md", "hits": {"S-04": 1}}' in init_text(tmp_path)


# ------------------------------------------------------------------- the ratchet

def test_a_new_repeat_fails_and_the_report_names_the_source_and_the_fix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path, **{"CLAUDE.md": "# App\n", "docs__a.md": PASSAGE})
    init_text(tmp_path)
    write(tmp_path, "CLAUDE.md", "# App\n\nOwn rule here.\n" + PASSAGE + "\n")
    assert run_mode(tmp_path) == ir.EXIT_RISE
    out = capsys.readouterr().out
    assert "CLAUDE.md: S-04" in out and "1 hit(s) (baseline 0)" in out
    assert "line 4" in out and "docs/a.md" in out and "point" in out


def test_a_baselined_repeat_passes_and_removing_it_lowers_the_baseline(tmp_path: Path) -> None:
    make_repo(tmp_path, **{"CLAUDE.md": PASSAGE + "\n", "docs__a.md": PASSAGE})
    init_text(tmp_path)
    assert run_mode(tmp_path) == ir.EXIT_PASS
    write(tmp_path, "CLAUDE.md", "See `docs/a.md`.\n")
    assert run_mode(tmp_path, update=True) == ir.EXIT_PASS
    assert '"entries": []' in baseline_text(tmp_path)


def test_editing_a_doc_to_repeat_claude_md_raises_the_count(tmp_path: Path) -> None:
    make_repo(tmp_path, **{"CLAUDE.md": PASSAGE + "\n", "docs__a.md": "other\n"})
    init_text(tmp_path)
    write(tmp_path, "docs/a.md", PASSAGE + "\n")
    assert run_mode(tmp_path) == ir.EXIT_RISE


# ------------------------------------------------------- sibling + self-adoption

def _lone_script(tmp_path: Path, *siblings: str) -> Path:
    lone = tmp_path / "scripts"
    lone.mkdir()
    for name in ("instruction_ratchet", "instruction_frontmatter", *siblings):
        (lone / f"{name}.py").write_bytes((REPO_ROOT / "scripts" / f"{name}.py").read_bytes())
    return lone / "instruction_ratchet.py"


def _run_script(script: Path, root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-P", str(script), "--root", str(root)],
        capture_output=True, text=True, encoding="utf-8", check=False, creationflags=NO_WINDOW, timeout=60,
    )


def test_a_missing_repeats_sibling_is_not_confirmed_when_the_rule_is_on(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    make_repo(root, **{"CLAUDE.md": "x\n"})
    ir.run(root, init=True, update=False, allow_additions=False)  # the in-process run has the sibling
    proc = _run_script(_lone_script(tmp_path), root)
    assert proc.returncode == ir.EXIT_NOT_CONFIRMED
    assert "instruction_repeats.py" in proc.stdout


def test_a_repo_that_has_not_turned_the_rule_on_needs_no_sibling(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    make_repo(root, "", **{"CLAUDE.md": "x\n"})
    ir.run(root, init=True, update=False, allow_additions=False)
    proc = _run_script(_lone_script(tmp_path), root)
    assert proc.returncode == ir.EXIT_PASS, proc.stdout


def test_the_sibling_is_catalogued_and_the_script_stays_within_the_structure_cap() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["instruction_repeats"] == {"src": "scripts/instruction_repeats.py"}
    assert (REPO_ROOT / "scripts" / "instruction_ratchet.py").read_text(encoding="utf-8").count("\n") <= 1000
