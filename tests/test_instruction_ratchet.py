"""Tests for the instruction-file lint ratchet.

Four layers, mirroring `test_docs_ratchet.py`:

1. **Lint** on fixture files: what each enforced rule counts, at which cap for
   which reader, and what it must not count (fences, inline code, frontmatter,
   the rules left to the weekly audit).
2. **Ratchet behaviour** on throwaway git repos: a risen count or a file past its
   size cap fails and names the file, rule and line, a lowered one passes, every
   mode, and the "not confirmed" exit for anything the linter cannot finish.
3. **Self-adoption** -- this repo's own declaration and gate wiring.
4. **Drift** against the prompt audit's own lint engine in a fleet-config
   checkout: the caps, rule tags, patterns and audiences are the same, and both
   engines give the same hits on the same files.
"""

from __future__ import annotations

import importlib
import os
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest

from scripts import docs_ratchet
from scripts import instruction_ratchet as ir
from tests._git_repo import git, write

REPO_ROOT = Path(__file__).resolve().parent.parent


def lint(root: Path, rel: str, text: str, *, agents: str | None = None) -> list[ir.Hit]:
    """Every hit in one file written under `root`, with an optional `AGENTS.md` beside it."""
    if agents is not None:
        (root / "AGENTS.md").write_text(agents, encoding="utf-8")
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    kind = ir.kind_of(rel) or "skill-ref"
    return ir.lint_doc(ir._doc(root, rel, kind), root)[0]


def rules(hits: list[ir.Hit], cap: str = "violation") -> Counter[str]:
    out: Counter[str] = Counter()
    for h in hits:
        if h.cap == cap:
            out[h.rule] += h.count
    return out


def skill(body: str, *, description: str = "Formats a report. Use when asked to format one.",
          name: str = "report-format") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"


# ------------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert ir.parse_config('layer = "x"\n') is None
    assert ir.parse_config("[instruction_ratchet]\nenabled = false\n") is None
    assert ir.parse_config("[instruction_ratchet]\n") is None  # opting in is explicit


def test_enabled_table_gets_the_documented_defaults() -> None:
    assert ir.parse_config("[instruction_ratchet]\nenabled = true\n") == ir.Config(
        ".instruction-ratchet-baseline.json", (".claude/skills",), ()
    )


def test_enabled_table_honours_every_key() -> None:
    cfg = ir.parse_config(
        '[instruction_ratchet]\nenabled = true\nbaseline = "b.json"\nskill_dirs = ["skills/", ".claude\\\\skills"]\n'
        'extra_files = ["global-CLAUDE.md"]\n'
    )
    assert cfg == ir.Config("b.json", ("skills", ".claude/skills"), ("global-CLAUDE.md",))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("enabled = true\nbaselin = 'x'\n", id="typo-in-key"),
        pytest.param('enabled = "yes"\n', id="enabled-not-bool"),
        pytest.param("enabled = true\nbaseline = ''\n", id="empty-baseline"),
        pytest.param("enabled = true\nskill_dirs = 'skills'\n", id="skill-dirs-not-a-list"),
        pytest.param("enabled = true\nextra_files = ['docs/guide.md']\n", id="extra-file-not-an-instruction-file"),
        pytest.param("enabled = true\nextra_files = ['/']\n", id="extra-file-empty-path"),
    ],
)
def test_malformed_table_fails_loud(body: str) -> None:
    with pytest.raises(ir.ConfigError):
        ir.parse_config("[instruction_ratchet]\n" + body)


# ------------------------------------------------------- reader and kinds

@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("CLAUDE.md", "claude-md"),
        ("global-CLAUDE.md", "claude-md"),
        ("AGENTS.md", "agents-md"),
        (".claude/rules/testing.md", "rules"),
        (".claude/skills/x/SKILL.md", "skill"),
        ("docs/guide.md", None),
    ],
)
def test_kind_of(path: str, kind: str | None) -> None:
    assert ir.kind_of(path) == kind


def test_a_claude_md_is_claude_scoped_until_agents_md_points_at_it(tmp_path: Path) -> None:
    text = "Use the tool. You MUST run it.\n"
    assert rules(lint(tmp_path, "CLAUDE.md", text)) == {"R-01": 1}
    assert rules(lint(tmp_path, "CLAUDE.md", text, agents="See `CLAUDE.md`.\n")) == {}
    assert rules(lint(tmp_path, "CLAUDE.md", text, agents="See `CLAUDE.md`.\n"), "consider") == {"R-01": 1}


def test_a_rules_file_is_always_claude_scoped(tmp_path: Path) -> None:
    assert rules(lint(tmp_path, ".claude/rules/style.md", "NEVER guess.\n", agents="See `CLAUDE.md`.\n")) == {"R-01": 1}


def test_a_scope_marker_heading_scopes_its_section(tmp_path: Path) -> None:
    text = "# Rules\n\nPlain text.\n\n## Spawning *(Claude Code only)*\n\nYou MUST cap it.\n\n## Other\n\nYou MUST NOT.\n"
    hits = lint(tmp_path, "AGENTS.md", text)
    assert [(h.line, h.cap) for h in hits if h.rule == "R-01"] == [(7, "violation"), (11, "consider")]


def test_an_openai_rule_does_not_apply_inside_a_claude_scoped_file(tmp_path: Path) -> None:
    text = "Share a plan before editing.\n"
    assert rules(lint(tmp_path, ".claude/rules/plan.md", text)) == {}
    assert rules(lint(tmp_path, "AGENTS.md", text), "consider") == {"R-12": 1}


# ------------------------------------------------------------------ phrases

@pytest.mark.parametrize(
    ("line", "rule"),
    [
        ("If in doubt, run the tests.", "R-02"),
        ("Double-check the output.", "R-03"),
        ("After every 3 tool calls, summarise.", "R-04"),
        ("Hold all findings until the final message.", "R-05"),
        ("Never use bullet points.", "R-06"),
        ("Think step by step.", "R-07"),
        ("Do not think before answering.", "R-08"),
        ("Be conservative in review.", "R-09"),
        ("Prefill the answer.", "R-10"),
        ("As of March 2026 the API changed.", "R-11"),
        ("Present a plan before editing.", "R-12"),
        ("Show your work.", "R-30"),
        ("Minimize tool calls.", "R-45"),
    ],
)
def test_each_phrase_rule_fires_in_a_claude_scoped_file(tmp_path: Path, line: str, rule: str) -> None:
    hits = lint(tmp_path, ".claude/rules/r.md", line + "\n")
    expected = {"R-12": 0}.get(rule, 1)  # an openai rule does not apply to a claude reader
    assert rules(hits).get(rule, 0) == expected


def test_shared_rules_reach_violation_in_a_neutral_file(tmp_path: Path) -> None:
    hits = lint(tmp_path, "AGENTS.md", "Re-verify your work.\nEvery few tool calls, post an update.\n")
    assert rules(hits) == {"R-03": 1, "R-04": 1}


def test_fences_inline_code_and_frontmatter_are_not_linted(tmp_path: Path) -> None:
    text = skill("Run `double-check.sh` first.\n\n```\nMUST NEVER\n```\n", description="Re-verify a build. MUST.")
    hits = lint(tmp_path, ".claude/skills/a/SKILL.md", text)
    assert rules(hits).get("R-03", 0) == 0
    assert rules(hits, "consider").get("R-01", 0) == 0


def test_r13_and_r37_are_left_to_the_weekly_audit(tmp_path: Path) -> None:
    hits = lint(tmp_path, ".claude/rules/r.md", "Never commit secrets.\nDo not push.\nCall `browser_batch` here.\n")
    assert {h.rule for h in hits} <= {"R-16"}
    assert set(ir.NOT_ENFORCED) == {"R-13", "R-37"}
    assert not set(ir.NOT_ENFORCED) & set(ir.RULES)


# --------------------------------------------------------------- structure

def test_r14_size_caps_per_kind(tmp_path: Path) -> None:
    assert rules(lint(tmp_path, "CLAUDE.md", "x\n" * 200, agents="CLAUDE.md")) == {}
    assert rules(lint(tmp_path, "CLAUDE.md", "x\n" * 201, agents="CLAUDE.md")) == {"R-14": 1}
    assert rules(lint(tmp_path, ".claude/skills/a/SKILL.md", skill("x\n" * 499))) == {}
    assert rules(lint(tmp_path, ".claude/skills/a/SKILL.md", skill("x\n" * 500))) == {"R-14": 1}
    assert rules(lint(tmp_path, "AGENTS.md", "x" * 32768)) == {}
    assert rules(lint(tmp_path, "AGENTS.md", "x" * 32769)) == {"R-14": 1}


def test_agents_md_bytes_are_measured_after_crlf_normalisation(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_bytes(b"x\r\n" * 16000)
    doc = ir._doc(tmp_path, "AGENTS.md", "agents-md")
    assert doc.size_bytes == 32000
    assert ir.lint_doc(doc, tmp_path)[1] == 32000


def test_r15_skill_description_and_name(tmp_path: Path) -> None:
    ok = lint(tmp_path, ".claude/skills/a/SKILL.md", skill("Body.\n", description='Formats it. E.g. "format my report".'))
    assert rules(ok, "consider").get("R-15", 0) == 0
    bad = lint(tmp_path, ".claude/skills/a/SKILL.md",
               skill("Body.\n", description="I format your <b>report</b>.", name="Report_Format"))
    assert rules(bad, "consider")["R-15"] == 2 + 2 + 1  # I + your, two tags, the name


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("Body only.\n", id="no-frontmatter"),
        pytest.param("---\nname: a\ndescription: has: a colon\n---\nBody.\n", id="unparseable-description"),
        pytest.param("---\nname: a\n---\nBody.\n", id="no-description"),
    ],
)
def test_an_unreadable_skill_description_is_not_confirmed(tmp_path: Path, text: str) -> None:
    with pytest.raises(ir.NotConfirmed, match="description"):
        lint(tmp_path, ".claude/skills/a/SKILL.md", text)


def test_an_unclosed_fence_is_not_confirmed(tmp_path: Path) -> None:
    with pytest.raises(ir.NotConfirmed, match="line 3"):
        lint(tmp_path, "AGENTS.md", "Text.\n\n```\nhidden\n")


def test_r16_same_phrase_under_both_modals(tmp_path: Path) -> None:
    hits = lint(tmp_path, "AGENTS.md", "Always commit to main.\nSomething else.\nNever commit to main.\n")
    assert [(h.rule, h.line) for h in hits if h.cap == "violation"] == [("R-16", 1)]


def test_r17_one_vendor_named_without_a_marker(tmp_path: Path) -> None:
    text = "Claude reads this.\n\nClaude and Codex read this.\n\n## Spawning (Claude Code only)\n\nClaude only.\n"
    hits = lint(tmp_path, "AGENTS.md", text)
    assert [(h.rule, h.line) for h in hits if h.cap == "violation"] == [("R-17", 1)]


def test_r34_and_r35_reference_docs(tmp_path: Path) -> None:
    (tmp_path / ".claude/skills/a").mkdir(parents=True)
    (tmp_path / ".claude/skills/a/ref.md").write_text("See [deep](deep.md).\n" + "line\n" * 120, encoding="utf-8")
    (tmp_path / ".claude/skills/a/deep.md").write_text("Deep.\n", encoding="utf-8")
    hits = lint(tmp_path, ".claude/skills/a/SKILL.md", skill("Read [the ref](ref.md).\n"), agents="")
    assert rules(hits, "consider") == {"R-34": 1}
    ref = ir.lint_doc(ir._doc(tmp_path, ".claude/skills/a/ref.md", "skill-ref"), tmp_path)[0]
    assert [h.rule for h in ref] == ["R-35"]


def test_r36_backslash_paths_and_their_caps(tmp_path: Path) -> None:
    hits = lint(tmp_path, ".claude/skills/a/SKILL.md", skill("Run scripts\\gen.py, then C:\\tools\\x.exe and .\\.venv\\Scripts\\python.exe.\n"))
    assert [(h.rule, h.count, h.cap) for h in hits if h.rule == "R-36"] == [("R-36", 2, "consider"), ("R-36", 1, "violation")]


# ------------------------------------------------------- ratchet on a git repo

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the stage enabled and one R-03 hit in its neutral `CLAUDE.md`."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text("[instruction_ratchet]\nenabled = true\n", encoding="utf-8")
    write(tmp_path, "AGENTS.md", "See `CLAUDE.md`.\n")
    write(tmp_path, "CLAUDE.md", "# Rules\n\nDouble-check the build.\n")
    return tmp_path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return ir.run(root, init=init, update=update, allow_additions=allow)


def baseline_text(root: Path) -> str:
    return (root / ir.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_init_writes_a_per_file_per_rule_baseline_and_never_overwrites(repo: Path) -> None:
    assert run_mode(repo, init=True) == ir.EXIT_PASS
    assert baseline_text(repo) == '{\n  "version": 1,\n  "entries": [\n    {"key": "CLAUDE.md", "hits": {"R-03": 1}}\n  ]\n}\n'
    assert run_mode(repo, init=True) == ir.EXIT_CONFIG


def test_unchanged_tree_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    assert run_mode(repo) == ir.EXIT_PASS
    assert "PASS (1 hit(s) in 1 of 2 file(s)" in capsys.readouterr().out


def test_a_new_hit_fails_and_names_file_rule_and_line(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "CLAUDE.md", "# Rules\n\nDouble-check the build.\nRe-verify the deploy.\n")
    assert run_mode(repo) == ir.EXIT_RISE
    out = capsys.readouterr().out
    assert "CLAUDE.md: R-03 No forced verification or re-check lines: 2 hit(s) (baseline 1)" in out
    assert "line 4: Re-verify the deploy." in out


def test_a_new_skill_with_a_hit_fails_even_if_another_file_shrank(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "CLAUDE.md", "# Rules\n")
    write(repo, ".claude/skills/a/SKILL.md", skill("Double-check it.\n"))
    assert run_mode(repo) == ir.EXIT_RISE


def test_a_removed_hit_passes_with_a_shrink_hint(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "CLAUDE.md", "# Rules\n")
    assert run_mode(repo) == ir.EXIT_PASS
    assert "1 file(s) are below the baseline" in capsys.readouterr().out


def test_update_baseline_lowers_refuses_a_rise_and_allow_additions_raises(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "CLAUDE.md", "# Rules\n")
    assert run_mode(repo, update=True) == ir.EXIT_PASS
    assert '"entries": []' in baseline_text(repo)
    write(repo, "CLAUDE.md", "Re-verify.\n")
    assert run_mode(repo, update=True) == ir.EXIT_RISE
    assert '"entries": []' in baseline_text(repo)
    assert run_mode(repo, update=True, allow=True) == ir.EXIT_PASS
    assert '"R-03": 1' in baseline_text(repo)


def test_a_file_growing_past_its_cap_fails_by_name(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "CLAUDE.md", "# Rules\n\nDouble-check the build.\n" + "x\n" * 198)
    assert run_mode(repo) == ir.EXIT_RISE
    assert "CLAUDE.md: R-14 Instruction-file size cap: 201 (not baselined)" in capsys.readouterr().out


def test_an_over_cap_file_is_baselined_at_its_size_and_may_only_shrink(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "CLAUDE.md", "x\n" * 210)
    run_mode(repo, init=True)
    assert '{"key": "CLAUDE.md", "size": 210}' in baseline_text(repo)
    write(repo, "CLAUDE.md", "x\n" * 205)
    assert run_mode(repo) == ir.EXIT_PASS
    write(repo, "CLAUDE.md", "x\n" * 211)
    assert run_mode(repo) == ir.EXIT_RISE
    assert "R-14 Instruction-file size cap: 211 (baseline 210)" in capsys.readouterr().out
    write(repo, "CLAUDE.md", "x\n" * 200)
    assert run_mode(repo, update=True) == ir.EXIT_PASS
    assert '"entries": []' in baseline_text(repo)


def test_missing_baseline_fails_instead_of_passing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo) == ir.EXIT_RISE
    assert "--init" in capsys.readouterr().out


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"version": 2, "entries": []}',
        '{"version": 1, "entries": [{"key": "a", "hits": {"R-99": 1}}]}',
        '{"version": 1, "entries": [{"key": "a", "hits": {"R-14": 1}}]}',
        '{"version": 1, "entries": [{"key": "a", "hits": {"R-03": 0}}]}',
        '{"version": 1, "entries": [{"key": "a"}]}',
        '{"version": 1, "entries": [{"key": "a", "size": true}]}',
    ],
)
def test_unreadable_baseline_exits_two(repo: Path, text: str) -> None:
    (repo / ir.DEFAULT_BASELINE).write_text(text, encoding="utf-8")
    assert run_mode(repo) == ir.EXIT_CONFIG


def test_disabled_or_absent_stage_exits_zero_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path) == ir.EXIT_PASS
    assert "not enabled" in capsys.readouterr().out
    assert run_mode(tmp_path, init=True) == ir.EXIT_CONFIG


def test_untracked_and_nested_files_are_not_linted(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, ".claude/skills/b/SKILL.md", skill("Double-check it.\n"), track=False)
    write(repo, "docs/CLAUDE.md", "Double-check it.\n")
    assert run_mode(repo) == ir.EXIT_PASS


def test_skill_dirs_and_extra_files_widen_the_scope(repo: Path) -> None:
    (repo / ".fleet.toml").write_text(
        '[instruction_ratchet]\nenabled = true\nskill_dirs = ["skills"]\nextra_files = ["global-CLAUDE.md"]\n',
        encoding="utf-8",
    )
    write(repo, "skills/a/SKILL.md", skill("Double-check it.\n"))
    write(repo, "global-CLAUDE.md", "Re-verify it.\n")
    run_mode(repo, init=True)
    text = baseline_text(repo)
    assert '"key": "skills/a/SKILL.md"' in text and '"key": "global-CLAUDE.md"' in text


def test_an_untracked_extra_file_is_a_config_error(repo: Path) -> None:
    (repo / ".fleet.toml").write_text('[instruction_ratchet]\nenabled = true\nextra_files = ["global-CLAUDE.md"]\n',
                                      encoding="utf-8")
    run_mode(repo, init=True)
    assert not (repo / ir.DEFAULT_BASELINE).exists()


@pytest.mark.parametrize("mode", [{}, {"update": True}])
def test_a_file_the_linter_cannot_finish_is_not_confirmed(repo: Path, mode: dict[str, bool], capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "CLAUDE.md", "```\nnever closed\n")
    assert run_mode(repo, **mode) == ir.EXIT_NOT_CONFIRMED
    assert "CLAUDE.md: the fenced block opened on line 1 never closes" in capsys.readouterr().out


def test_undecodable_bytes_are_not_confirmed(repo: Path) -> None:
    run_mode(repo, init=True)
    (repo / "CLAUDE.md").write_bytes(b"caf\xe9\n")
    assert run_mode(repo) == ir.EXIT_NOT_CONFIRMED


def test_git_that_cannot_list_files_is_not_confirmed(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_mode(repo, init=True)
    monkeypatch.setenv("PATH", str(repo / "empty"))
    assert run_mode(repo) == ir.EXIT_NOT_CONFIRMED


def test_main_rejects_allow_additions_without_update(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        ir.main(["--allow-additions"])
    assert exc.value.code == 2
    assert "--allow-additions" in capsys.readouterr().err


# ------------------------------------------------------------ self-adoption

def test_scaffold_adopts_the_stage_and_commits_a_parseable_baseline() -> None:
    cfg = ir.load_config(REPO_ROOT)
    assert cfg is not None, "the scaffold adopts its own stage first"
    ir.read_baseline(REPO_ROOT / cfg.baseline)


def test_the_new_doc_carries_no_history_marker() -> None:
    text = (REPO_ROOT / "docs" / "instruction-ratchet.md").read_text(encoding="utf-8")
    assert docs_ratchet.scan_text(text) == []


def test_gate_runs_the_stage_after_the_structure_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    structure, stage, mypy = (text.index(s) for s in (
        'Invoke-Stage "structure ratchet"', 'Invoke-Stage "instruction ratchet"', 'Invoke-Stage "mypy'))
    assert structure < stage < mypy
    assert "scripts/instruction_ratchet.py" in text


def test_the_script_is_catalogued_so_it_is_mypy_gated_and_drift_checked() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["instruction_ratchet"] == {"src": "scripts/instruction_ratchet.py"}


# ------------------------------------------------- drift against prompt-audit

def _prompt_audit() -> ModuleType:
    """The prompt audit's package from a fleet-config checkout: `FLEET_CONFIG_DIR`, else a sibling of this repo.

    Its absence is reported as a skip with the reason (the comparison was not
    made), never as a pass; a set but wrong `FLEET_CONFIG_DIR` fails.
    """
    env = os.environ.get("FLEET_CONFIG_DIR")
    base = Path(env) if env else REPO_ROOT.parent / "fleet-config"
    skill_dir = base / ".claude" / "skills" / "prompt-audit"
    if not (skill_dir / "prompt_audit").is_dir():
        if env:
            pytest.fail(f"FLEET_CONFIG_DIR={env} has no .claude/skills/prompt-audit/prompt_audit")
        pytest.skip(f"drift NOT CHECKED: no fleet-config checkout at {base} (set FLEET_CONFIG_DIR)")
    if str(skill_dir) not in sys.path:
        sys.path.insert(0, str(skill_dir))
    return importlib.import_module("prompt_audit")


@pytest.fixture(scope="module")
def pa() -> dict[str, ModuleType]:
    _prompt_audit()
    return {name: importlib.import_module(f"prompt_audit.{name}") for name in ("common", "inventory", "lint", "rules")}


def test_the_caps_and_rule_tags_match_the_prompt_audit(pa: dict[str, ModuleType]) -> None:
    assert ir.SIZE_CAPS == pa["common"].SIZE_CAPS
    assert ir.ALWAYS_ON_KINDS == pa["common"].ALWAYS_ON_KINDS
    parsed = pa["rules"].parse_rules(pa["common"].RULES_MD.read_text(encoding="utf-8"))
    for rule, (vendor, scope, title) in ir.RULES.items():
        assert (parsed[rule]["vendor"], parsed[rule]["file"], parsed[rule]["title"]) == (vendor, scope, title), rule
        assert parsed[rule]["detect"] == "lint", rule
    assert set(ir.RULES) | set(ir.NOT_ENFORCED) == set(pa["lint"].LINT_RULES)


def test_the_patterns_and_audiences_match_the_prompt_audit(pa: dict[str, ModuleType]) -> None:
    lint_mod = pa["lint"]
    assert {r: [p.pattern for p in ps] for r, ps in ir.PATTERNS.items()} == {
        r: [p.pattern for p in ps] for r, ps in lint_mod.PATTERNS.items()}
    assert {r: p.pattern for r, p in ir.LINE_PATTERNS.items()} == {
        r: p.pattern for r, p in lint_mod.LINE_PATTERNS.items() if r not in ir.NOT_ENFORCED}
    audiences = pa["common"].load_toml()["audiences"]
    assert {n: (a.vendor, list(a.markers), list(a.terms), list(a.path_globs), list(a.unpointed))
            for n, a in ir.AUDIENCES.items()} == {
        n: (a["vendor"], a["markers"], a["terms"], a["path_globs"], a["unpointed"]) for n, a in audiences.items()}


def _corpus(root: Path) -> None:
    """A tracked fixture tree that trips every enforced rule at both caps."""
    git(root, "init", "-q")
    write(root, "CLAUDE.md", "You MUST double-check.\nIf in doubt, ask.\nAlways commit to main.\nNever commit to main.\n" + "x\n" * 200)
    write(root, "AGENTS.md", "Claude reads this.\n\nShare a plan before editing.\nShow your work.\n## Codex only\n\nMinimize tool calls.\n")
    write(root, ".claude/rules/r.md", "Never use markdown.\nThink step by step.\nDo not think.\nAs of May 2026.\nPrefill it.\n")
    write(root, ".claude/skills/a/ref.md", "See [deep](deep.md).\n" + "y\n" * 120)
    write(root, ".claude/skills/a/deep.md", "Deep.\n")
    write(root, ".claude/skills/a/SKILL.md", skill(
        "Read [ref](ref.md). Run scripts\\x.py and C:\\t\\x.exe.\nHold all findings until the final reply.\n",
        description="I help <b>you</b>.", name="Bad_Name"))


def test_both_engines_give_the_same_hits(pa: dict[str, ModuleType], tmp_path: Path) -> None:
    _corpus(tmp_path)
    lint_mod, inv, common = pa["lint"], pa["inventory"], pa["common"]
    parsed = pa["rules"].parse_rules(common.RULES_MD.read_text(encoding="utf-8"))
    audiences = common.load_toml()["audiences"]
    compared = 0
    for root in (tmp_path, REPO_ROOT):
        for doc in ir.inventory(root, ir.Config(ir.DEFAULT_BASELINE, ir.DEFAULT_SKILL_DIRS, ())):
            entry = inv.Entry(key=f"repo/{doc.path}", path=root / doc.path, repo="repo", kind=doc.kind,
                              data=(root / doc.path).read_bytes(), repo_dir=root)
            entry.audience = inv.audience_of(entry, root, audiences)
            assert entry.audience == doc.audience, doc.path
            theirs = lint_mod.lint_entry(entry, parsed, audiences, {})
            # R-45's dated consider-only noise guard is the weekly digest's; the ratchet counts it as tagged.
            want = Counter((h.rule, h.line, h.count, "-" if parsed[h.rule]["consider_only"] else h.cap)
                           for h in theirs.hits if h.rule in ir.RULES)
            got = Counter((h.rule, h.line, h.count, "-" if parsed[h.rule]["consider_only"] else h.cap)
                          for h in ir.lint_doc(doc, root)[0])
            assert got == want, doc.path
            compared += 1
    assert compared == 7  # the five corpus files plus this repo's CLAUDE.md and AGENTS.md
