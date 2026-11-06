"""Tests for the instruction ratchet's three file-shape rules.

S-01 a `## CI expectations` section whenever `.github/workflows/` exists, S-02 an `AGENTS.md` that is
a short pointer to `CLAUDE.md`, S-03 a line cap on the root `CLAUDE.md` of an app repo. Each is off
until the adopter's `[instruction_ratchet]` table turns it on, so a re-vendor never turns a repo red;
once on, the findings are baselined like any other count and may only shrink.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts import instruction_ratchet as ir
from src.no_window import NO_WINDOW
from tests._git_repo import git, write
from tests.ratchets.test_instruction_ratchet import baseline_text, run_mode

REPO_ROOT = Path(__file__).resolve().parents[2]

POINTER = "See `CLAUDE.md`.\n"
WORKFLOW = ".github/workflows/ci.yml"


def make_repo(root: Path, options: str = "", **files: str) -> Path:
    """A git repo with the stage enabled plus `options`; `files` maps a path (`__` for `/`) to its text."""
    git(root, "init", "-q")
    (root / ".fleet.toml").write_text("[instruction_ratchet]\nenabled = true\n" + options, encoding="utf-8")
    for name, text in files.items():
        write(root, name.replace("__", "/"), text)
    return root


def init_hits(root: Path) -> str:
    assert run_mode(root, init=True) == ir.EXIT_PASS
    return baseline_text(root)


# ------------------------------------------------------------------- config

def test_the_shape_rules_are_off_by_default() -> None:
    cfg = ir.parse_config("[instruction_ratchet]\nenabled = true\n")
    assert cfg is not None
    assert (cfg.ci_expectations, cfg.agents_pointer, cfg.claude_md_max_lines) == (False, False, None)


def test_the_shape_keys_are_honoured() -> None:
    cfg = ir.parse_config(
        "[instruction_ratchet]\nenabled = true\nci_expectations = true\nagents_pointer = true\n"
        "claude_md_max_lines = 120\n"
    )
    assert cfg is not None
    assert (cfg.ci_expectations, cfg.agents_pointer, cfg.claude_md_max_lines) == (True, True, 120)


@pytest.mark.parametrize(
    "body",
    [
        pytest.param('ci_expectations = "yes"\n', id="ci-not-bool"),
        pytest.param("agents_pointer = 1\n", id="pointer-not-bool"),
        pytest.param("claude_md_max_lines = 0\n", id="cap-zero"),
        pytest.param("claude_md_max_lines = -5\n", id="cap-negative"),
        pytest.param('claude_md_max_lines = "120"\n', id="cap-string"),
        pytest.param("claude_md_max_lines = true\n", id="cap-bool"),
    ],
)
def test_a_malformed_shape_key_fails_loud(body: str) -> None:
    with pytest.raises(ir.ConfigError):
        ir.parse_config("[instruction_ratchet]\nenabled = true\n" + body)


def test_with_every_option_off_the_shape_findings_are_not_counted(tmp_path: Path) -> None:
    make_repo(tmp_path, **{"CLAUDE.md": "# App\n", WORKFLOW.replace("/", "__"): "on: push\n"})
    assert '"entries": []' in init_hits(tmp_path)


# ---------------------------------------------------- S-01 CI expectations

CI = "ci_expectations = true\n"


def test_workflows_without_a_ci_expectations_section_are_baselined_on_claude_md(tmp_path: Path) -> None:
    make_repo(tmp_path, CI, **{"CLAUDE.md": "# App\n"})
    write(tmp_path, WORKFLOW, "on: push\n")
    assert '{"key": "CLAUDE.md", "hits": {"S-01": 1}}' in init_hits(tmp_path)


def test_a_ci_expectations_section_clears_it(tmp_path: Path) -> None:
    make_repo(tmp_path, CI, **{"CLAUDE.md": "# App\n\n## CI expectations\n- advisory\n"})
    write(tmp_path, WORKFLOW, "on: push\n")
    assert '"entries": []' in init_hits(tmp_path)


@pytest.mark.parametrize("heading", ["# CI expectations", "### ci expectations", "## CI expectations (advisory)"])
def test_the_heading_level_and_case_are_not_part_of_the_contract(tmp_path: Path, heading: str) -> None:
    make_repo(tmp_path, CI, **{"CLAUDE.md": f"# App\n\n{heading}\n- x\n"})
    write(tmp_path, WORKFLOW, "on: push\n")
    assert '"entries": []' in init_hits(tmp_path)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("# App\n\n```markdown\n## CI expectations\n```\n", id="inside-a-fence"),
        pytest.param("# App\n\nSee CI expectations below.\n", id="prose-mention"),
        pytest.param("# App\n\n## CI is advisory -- `## CI expectations` block\n", id="other-heading-naming-it"),
    ],
)
def test_only_a_real_heading_counts(tmp_path: Path, text: str) -> None:
    make_repo(tmp_path, CI, **{"CLAUDE.md": text})
    write(tmp_path, WORKFLOW, "on: push\n")
    assert '"S-01": 1' in init_hits(tmp_path)


def test_no_workflows_means_no_obligation(tmp_path: Path) -> None:
    make_repo(tmp_path, CI, **{"CLAUDE.md": "# App\n"})
    assert '"entries": []' in init_hits(tmp_path)


def test_a_template_file_under_workflows_still_counts(tmp_path: Path) -> None:
    make_repo(tmp_path, CI, **{"CLAUDE.md": "# App\n"})
    write(tmp_path, ".github/workflows/ci.yml.template", "on: push\n")
    assert '"S-01": 1' in init_hits(tmp_path)


def test_workflows_with_no_claude_md_are_a_finding_on_the_missing_file(tmp_path: Path) -> None:
    make_repo(tmp_path, CI)
    write(tmp_path, WORKFLOW, "on: push\n")
    assert '{"key": "CLAUDE.md", "hits": {"S-01": 1}}' in init_hits(tmp_path)


def test_a_new_workflow_in_a_clean_repo_fails_and_the_message_names_the_fix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_repo(tmp_path, CI, **{"CLAUDE.md": "# App\n"})
    run_mode(tmp_path, init=True)
    write(tmp_path, WORKFLOW, "on: push\n")
    assert run_mode(tmp_path) == ir.EXIT_RISE
    out = capsys.readouterr().out
    assert "CLAUDE.md: S-01" in out
    assert "## CI expectations" in out and "/issue-finish" in out


def test_adding_the_section_burns_the_baseline_down(tmp_path: Path) -> None:
    make_repo(tmp_path, CI, **{"CLAUDE.md": "# App\n"})
    write(tmp_path, WORKFLOW, "on: push\n")
    init_hits(tmp_path)
    assert run_mode(tmp_path) == ir.EXIT_PASS
    write(tmp_path, "CLAUDE.md", "# App\n\n## CI expectations\n- advisory\n")
    assert run_mode(tmp_path, update=True) == ir.EXIT_PASS
    assert '"entries": []' in baseline_text(tmp_path)


# ------------------------------------------------------ S-02 AGENTS pointer

PTR = "agents_pointer = true\n"


def test_a_one_line_pointer_passes(tmp_path: Path) -> None:
    make_repo(tmp_path, PTR, **{"CLAUDE.md": "# App\n", "AGENTS.md": POINTER})
    assert '"entries": []' in init_hits(tmp_path)


def test_the_scaffolds_own_pointer_shape_passes(tmp_path: Path) -> None:
    text = (REPO_ROOT / "AGENTS.md").read_text(encoding="utf-8")
    make_repo(tmp_path, PTR, **{"CLAUDE.md": "# App\n", "AGENTS.md": text})
    assert '"entries": []' in init_hits(tmp_path)


def test_a_missing_agents_md_is_a_finding_on_the_missing_file(tmp_path: Path) -> None:
    make_repo(tmp_path, PTR, **{"CLAUDE.md": "# App\n"})
    assert '{"key": "AGENTS.md", "hits": {"S-02": 1}}' in init_hits(tmp_path)


def test_an_agents_md_that_does_not_name_claude_md_is_a_finding(tmp_path: Path) -> None:
    make_repo(tmp_path, PTR, **{"CLAUDE.md": "# App\n", "AGENTS.md": "Be careful.\n"})
    assert '"S-02": 1' in init_hits(tmp_path)


def test_a_long_agents_md_is_a_copy_not_a_pointer(tmp_path: Path) -> None:
    body = "See `CLAUDE.md`.\n" + "".join(f"Rule {n}.\n" for n in range(ir.POINTER_MAX_LINES))
    make_repo(tmp_path, PTR, **{"CLAUDE.md": "# App\n", "AGENTS.md": body})
    assert '"S-02": 1' in init_hits(tmp_path)


def test_blank_lines_do_not_count_toward_the_pointer_length(tmp_path: Path) -> None:
    body = "# AGENTS.md\n\n" + "\n\n".join(["See `CLAUDE.md`."] * 3) + "\n" * 30
    make_repo(tmp_path, PTR, **{"CLAUDE.md": "# App\n", "AGENTS.md": body})
    assert '"entries": []' in init_hits(tmp_path)


def test_the_pointer_message_names_the_fix(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, PTR, **{"CLAUDE.md": "# App\n", "AGENTS.md": POINTER})
    run_mode(tmp_path, init=True)
    write(tmp_path, "AGENTS.md", "Different rules.\n")
    assert run_mode(tmp_path) == ir.EXIT_RISE
    out = capsys.readouterr().out
    assert "AGENTS.md: S-02" in out
    assert "pointer" in out and "CLAUDE.md" in out


# ------------------------------------------------------------ S-03 line cap

CAP = "claude_md_max_lines = 120\n"


def test_a_claude_md_at_the_cap_passes_and_one_over_counts_the_excess(tmp_path: Path) -> None:
    make_repo(tmp_path, CAP, **{"AGENTS.md": POINTER, "CLAUDE.md": "x\n" * 120})
    assert '"entries": []' in init_hits(tmp_path)
    write(tmp_path, "CLAUDE.md", "x\n" * 135)
    (tmp_path / ir.DEFAULT_BASELINE).unlink()
    assert '{"key": "CLAUDE.md", "hits": {"S-03": 15}}' in init_hits(tmp_path)


def test_the_cap_ratchets_growth_fails_shrink_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, CAP, **{"AGENTS.md": POINTER, "CLAUDE.md": "x\n" * 140})
    init_hits(tmp_path)
    write(tmp_path, "CLAUDE.md", "x\n" * 130)
    assert run_mode(tmp_path) == ir.EXIT_PASS
    write(tmp_path, "CLAUDE.md", "x\n" * 141)
    assert run_mode(tmp_path) == ir.EXIT_RISE
    out = capsys.readouterr().out
    assert "CLAUDE.md: S-03" in out and "21 hit(s) (baseline 20)" in out
    assert "120" in out and "skill" in out  # names the cap and where scoped detail goes


def test_the_cap_applies_to_the_root_claude_md_only(tmp_path: Path) -> None:
    make_repo(tmp_path, CAP + 'extra_files = ["docs/team-CLAUDE.md"]\n',
              **{"AGENTS.md": POINTER, "CLAUDE.md": "x\n", "docs__team-CLAUDE.md": "x\n" * 150})
    write(tmp_path, ".claude/rules/big.md", "x\n" * 150)
    assert '"entries": []' in init_hits(tmp_path)


def test_without_the_option_the_general_cap_is_still_200(tmp_path: Path) -> None:
    make_repo(tmp_path, "", **{"AGENTS.md": POINTER, "CLAUDE.md": "x\n" * 150})
    assert '"entries": []' in init_hits(tmp_path)


# ---------------------------------------------------------- shared behaviour

def test_every_shape_rule_has_a_title_and_none_collides_with_a_lint_rule() -> None:
    assert set(ir.SHAPE_RULES) == {"S-01", "S-02", "S-03", "S-04"}
    assert not set(ir.SHAPE_RULES) & set(ir.RULES)


def test_a_baseline_naming_a_shape_rule_is_accepted(tmp_path: Path) -> None:
    make_repo(tmp_path, PTR + CAP, **{"CLAUDE.md": "x\n" * 125})
    init_hits(tmp_path)
    assert ir.read_baseline(tmp_path / ir.DEFAULT_BASELINE)["CLAUDE.md"].hits == {"S-03": 5}
    assert ir.read_baseline(tmp_path / ir.DEFAULT_BASELINE)["AGENTS.md"].hits == {"S-02": 1}


def test_a_baseline_naming_an_unknown_rule_is_still_rejected(tmp_path: Path) -> None:
    path = tmp_path / "b.json"
    path.write_text('{"version": 1, "entries": [{"key": "CLAUDE.md", "hits": {"S-99": 1}}]}', encoding="utf-8")
    with pytest.raises(ir.ConfigError):
        ir.read_baseline(path)


# ----------------------------------------------------- sibling + self-adoption

def test_a_missing_frontmatter_sibling_is_not_confirmed_never_a_pass(tmp_path: Path) -> None:
    lone = tmp_path / "scripts"
    lone.mkdir()
    (lone / "instruction_ratchet.py").write_bytes((REPO_ROOT / "scripts" / "instruction_ratchet.py").read_bytes())
    proc = subprocess.run(
        [sys.executable, "-P", str(lone / "instruction_ratchet.py"), "--root", str(tmp_path)],
        capture_output=True, text=True, encoding="utf-8", check=False, creationflags=NO_WINDOW, timeout=60,
    )
    assert proc.returncode == ir.EXIT_NOT_CONFIRMED
    assert "instruction_frontmatter.py" in proc.stdout


def test_the_frontmatter_sibling_is_catalogued_and_the_script_stays_within_the_structure_cap() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["instruction_frontmatter"] == {"src": "scripts/instruction_frontmatter.py"}
    lines = (REPO_ROOT / "scripts" / "instruction_ratchet.py").read_text(encoding="utf-8").count("\n")
    assert lines <= 1000


def test_the_scaffold_turns_on_the_rules_it_can_satisfy_and_satisfies_them() -> None:
    cfg = ir.load_config(REPO_ROOT)
    assert cfg is not None and cfg.ci_expectations and cfg.agents_pointer
    assert cfg.claude_md_max_lines is None  # the scaffold is not an app repo
    assert ir.run(REPO_ROOT, init=False, update=False, allow_additions=False) == ir.EXIT_PASS
