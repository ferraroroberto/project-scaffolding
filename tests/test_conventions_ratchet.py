"""Tests for the conventions ratchet.

Three layers, mirroring `test_dead_code_ratchet.py`:

1. **Rules** on fixture sources: each rule fails by name on a seeded violation
   and passes on the compliant form, plus the scoping each rule relies on
   (test modules, platform branches, CLI modules, helpers, exempt markers).
2. **Ratchet behaviour** on throwaway git repos: every mode, and the "not
   confirmed" exit for anything that cannot be read through. A missing
   prerequisite is a hard failure, never `pytest.skip`.
3. **Self-adoption** -- this repo's own declaration and gate wiring.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import conventions_ratchet as cr
from tests._git_repo import git, write

REPO_ROOT = Path(__file__).resolve().parent.parent
ALL = cr.Config(cr.DEFAULT_BASELINE, cr.RULES, (), cr.DEFAULT_PRINT_PATHS, ("src/secret_compare.py",), ("src/git_run.py",))


def hits(src: str, path: str = "src/a.py", cfg: cr.Config = ALL) -> list[str]:
    """`rule:line` of every hit in one in-memory module."""
    return [f"{h.rule}:{h.line}" for h in cr.scan_source(src, path, cr.rules_for(path, cfg))]


# ------------------------------------------------------------------- config

def test_absent_or_disabled_table_is_not_enabled() -> None:
    assert cr.parse_config('layer = "x"\n') is None
    assert cr.parse_config("[conventions_ratchet]\nenabled = false\n") is None
    assert cr.parse_config("[conventions_ratchet]\n") is None  # opting in is explicit


def test_enabled_table_keeps_rule_order_and_defaults() -> None:
    cfg = cr.parse_config('[conventions_ratchet]\nenabled = true\nrules = ["no-drive-path", "no-window"]\n')
    assert cfg == cr.Config(cr.DEFAULT_BASELINE, ("no-window", "no-drive-path"))


def test_enabled_table_honours_every_key() -> None:
    cfg = cr.parse_config(
        '[conventions_ratchet]\nenabled = true\nbaseline = "b.json"\nrules = ["secret-compare", "git-wrapper"]\n'
        'exclude = ["src/gen/**"]\nprint_paths = ["lib/"]\nsecret_helpers = ["src/s.py"]\ngit_wrappers = ["src/g.py"]\n'
    )
    assert cfg == cr.Config("b.json", ("secret-compare", "git-wrapper"), ("src/gen/**",), ("lib/",),
                            ("src/s.py",), ("src/g.py",))


@pytest.mark.parametrize(
    "body",
    [
        pytest.param("enabled = true\nrules = ['no-window']\nrule = []\n", id="typo-in-key"),
        pytest.param('enabled = "yes"\nrules = ["no-window"]\n', id="enabled-not-bool"),
        pytest.param("enabled = true\n", id="no-rules"),
        pytest.param("enabled = true\nrules = []\n", id="empty-rules"),
        pytest.param("enabled = true\nrules = ['no-windows']\n", id="unknown-rule"),
        pytest.param("enabled = true\nrules = ['secret-compare']\n", id="secret-compare-without-helper"),
        pytest.param("enabled = true\nrules = ['git-wrapper']\n", id="git-wrapper-without-wrapper"),
        pytest.param("enabled = true\nrules = ['no-window']\nbaseline = ''\n", id="empty-baseline"),
        pytest.param("enabled = true\nrules = ['no-window']\nexclude = 'x'\n", id="exclude-not-a-list"),
    ],
)
def test_malformed_table_fails_loud(body: str) -> None:
    with pytest.raises(cr.ConfigError):
        cr.parse_config("[conventions_ratchet]\n" + body)


# -------------------------------------------------------------------- rules

@pytest.mark.parametrize(
    ("rule", "bad", "good"),
    [
        pytest.param("no-window", "import subprocess\nsubprocess.run(['x'])\n",
                     "import subprocess\nsubprocess.run(['x'], creationflags=NO_WINDOW)\n", id="no-window"),
        pytest.param("logging-not-print", "print('hello')\n", "import logging\nlogging.info('hello')\n",
                     id="logging-not-print"),
        pytest.param("no-drive-path", "ROOT = 'E:/data/app'\n", "ROOT = os.environ['APP_ROOT']\n",
                     id="no-drive-path"),
        pytest.param("secret-compare", "import hmac\nok = hmac.compare_digest(a, b)\n",
                     "from src.secret_compare import equal\nok = equal(a, b)\n", id="secret-compare"),
        pytest.param("git-wrapper", "import subprocess\nsubprocess.run(['git', 'status'], creationflags=0)\n",
                     "from src.git_run import run_git\nrun_git(['status'])\n", id="git-wrapper"),
    ],
)
def test_each_rule_fails_by_name_on_a_violation_and_passes_the_compliant_form(rule: str, bad: str, good: str) -> None:
    assert hits(bad) == [f"{rule}:{len(bad.splitlines())}"]  # each seeded violation is on its last line
    assert hits(good) == []


def test_a_disabled_rule_reports_nothing() -> None:
    only_window = cr.Config(cr.DEFAULT_BASELINE, ("no-window",))
    assert hits("print('x')\nP = 'C:/x/y'\n", cfg=only_window) == []


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("import subprocess as sp\nsp.Popen(['x'])\n", id="module-alias"),
        pytest.param("from subprocess import check_output\ncheck_output(['x'])\n", id="from-import"),
        pytest.param("import asyncio\nasync def f():\n    await asyncio.create_subprocess_exec('x')\n",
                     id="asyncio"),
    ],
)
def test_no_window_follows_import_aliases(src: str) -> None:
    assert [h.split(":")[0] for h in hits(src)] == ["no-window"]


def test_no_window_trusts_a_kwargs_splat_rather_than_guess() -> None:
    assert hits("import subprocess\nsubprocess.run(['x'], **opts)\n") == []


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("if sys.platform == 'darwin':\n    subprocess.run(['open', p])\n", id="darwin-branch"),
        pytest.param("if sys.platform == 'win32':\n    os.startfile(p)\nelse:\n    subprocess.run(['xdg-open', p])\n",
                     id="else-of-windows"),
        pytest.param("if os.name != 'nt':\n    subprocess.run(['kill', p])\n", id="not-nt"),
        pytest.param("if platform.system() == 'Linux':\n    subprocess.run(['x'])\n", id="platform-system"),
        pytest.param("def f():\n    if sys.platform == 'win32':\n        return 1\n    subprocess.run(['xclip'])\n",
                     id="after-windows-early-return"),
    ],
)
def test_no_window_skips_branches_that_never_run_on_windows(src: str) -> None:
    assert hits("import os, sys, platform, subprocess\n" + src) == []


def test_no_window_still_reports_a_branch_that_may_run_on_windows() -> None:
    src = "import sys, subprocess\nif sys.platform != 'darwin':\n    subprocess.run(['x'])\n"
    assert hits(src) == ["no-window:3"]


def test_test_modules_are_held_to_no_window_only() -> None:
    src = "import subprocess, hmac\nsubprocess.run(['git', 'x'])\nP = 'C:/x/y'\nhmac.compare_digest(a, b)\n"
    for path in ("tests/test_x.py", "tests/_helpers.py", "src/pkg/tests/check.py", "conftest.py", "src/x_test.py"):
        assert hits(src, path) == ["no-window:2"], path


@pytest.mark.parametrize(
    "src",
    [
        pytest.param("import argparse\nprint('x')\n", id="argparse"),
        pytest.param("import click\nprint('x')\n", id="click"),
        pytest.param("def main():\n    print('x')\n\nif __name__ == '__main__':\n    main()\n", id="main-guard"),
        pytest.param("print('x', file=fh)\n", id="writes-to-a-file"),
        pytest.param("from rich import print\nprint('x')\n", id="print-shadowed"),
    ],
)
def test_logging_not_print_leaves_command_line_modules_and_file_writes_alone(src: str) -> None:
    assert hits(src) == []


def test_logging_not_print_covers_only_print_paths_and_not_cli_files() -> None:
    assert hits("print('x')\n", "scripts/tool.py") == []
    assert hits("print('x')\n", "src/cli.py") == []
    assert hits("print('x')\n", "app/cli/run.py") == []
    assert hits("print('x')\n", "src/__main__.py") == []
    assert hits("print('x', file=sys.stderr)\n", "app/views/home.py") == ["logging-not-print:1"]


@pytest.mark.parametrize(
    "literal",
    ["C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", r"C:\\Program Files\\Git\\bin\\git.exe",
     "C:/ProgramData/pip/pip.ini", "C:\\", "D:/", "C:", "http://host/c:/x", "see E:/x"],
)
def test_no_drive_path_allows_system_folders_drive_roots_and_non_leading_drives(literal: str) -> None:
    assert hits(f"P = {literal!r}\n") == []


def test_no_drive_path_ignores_docstrings_but_not_f_strings() -> None:
    assert hits('"""Writes to E:/data by default."""\n') == []
    assert hits("P = f'D:/out/{name}'\n") == ["no-drive-path:1"]


def test_helpers_and_wrappers_may_do_what_everyone_else_may_not() -> None:
    assert hits("import hmac\nhmac.compare_digest(a, b)\n", "src/secret_compare.py") == []
    assert hits("import subprocess\nsubprocess.run(['git', 'x'], creationflags=0)\n", "src/git_run.py") == []
    assert hits("from secrets import compare_digest\ncompare_digest(a, b)\n") == ["secret-compare:2"]
    assert hits("import subprocess\nsubprocess.run('git status', creationflags=0)\n") == ["git-wrapper:2"]
    assert hits("import subprocess\nsubprocess.run([r'C:\\\\Git\\\\git.exe', 'x'], creationflags=0)\n") == [
        "git-wrapper:2", "no-drive-path:2"]


def test_an_exempt_marker_needs_the_rule_and_a_reason() -> None:
    call = "subprocess.run(['x'])"
    assert hits(f"import subprocess\n{call}  # no-window-exempt: deliberately visible console\n") == []
    assert hits(f"import subprocess\n# no-window-exempt: POSIX-only helper,\n# called from the mac installer\n{call}\n") == []
    assert hits(f"import subprocess\n{call}  # no-window-exempt\n") == ["no-window:2"], "a bare marker exempts nothing"
    assert hits(f"import subprocess\n{call}  # git-wrapper-exempt: wrong rule\n") == ["no-window:2"]


def test_a_file_that_does_not_parse_is_not_confirmed() -> None:
    with pytest.raises(cr.NotConfirmed, match="does not parse"):
        cr.scan_source(b"def broken(:\n", "src/a.py", frozenset(cr.RULES))
    with pytest.raises(cr.NotConfirmed, match="does not parse"):
        cr.scan_source(b"x = 'caf\xe9'\n", "src/latin.py", frozenset())


# ------------------------------------------------------- ratchet on a git repo

@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with two rules on and one baselined drive path."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(
        '[conventions_ratchet]\nenabled = true\nrules = ["no-window", "no-drive-path"]\n', encoding="utf-8"
    )
    write(tmp_path, "src/a.py", "ROOT = 'E:/old/data'\n")
    return tmp_path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return cr.run(root, init=init, update=update, allow_additions=allow)


def baseline_text(root: Path) -> str:
    return (root / cr.DEFAULT_BASELINE).read_text(encoding="utf-8")


def test_init_records_real_counts_and_never_overwrites(repo: Path) -> None:
    assert run_mode(repo, init=True) == cr.EXIT_PASS
    assert '{"key": "src/a.py", "counts": {"no-drive-path": 1}}' in baseline_text(repo)
    assert run_mode(repo, init=True) == cr.EXIT_CONFIG


def test_unchanged_tree_passes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    assert run_mode(repo) == cr.EXIT_PASS
    assert "PASS (1 baselined hit(s) in 1 file(s), none new; rules: no-window, no-drive-path)" in capsys.readouterr().out


def test_a_new_violation_fails_by_rule_file_and_line(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "src/b.py", "import subprocess\n\nsubprocess.Popen(['tool'])\n")
    capsys.readouterr()
    assert run_mode(repo) == cr.EXIT_RISE
    out = capsys.readouterr().out
    assert "src/b.py: [no-window] 1 hit(s), baseline 0:" in out
    assert "src/b.py:3: [no-window] `subprocess.Popen(...)` passes no creationflags=" in out


def test_a_second_violation_of_a_baselined_rule_in_the_same_file_fails(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/a.py", "ROOT = 'E:/old/data'\nOUT = 'E:/old/out'\n")
    assert run_mode(repo) == cr.EXIT_RISE


def test_a_fixed_violation_passes_with_a_shrink_hint(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "src/a.py", "import os\nROOT = os.environ['ROOT']\n")
    assert run_mode(repo) == cr.EXIT_PASS
    assert "1 baselined hit(s) are gone" in capsys.readouterr().out


def test_update_baseline_shrinks_only(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/a.py", "ROOT = None\n")
    assert run_mode(repo, update=True) == cr.EXIT_PASS
    assert '"entries": []' in baseline_text(repo)
    write(repo, "src/b.py", "P = 'D:/x/y'\n")
    assert run_mode(repo, update=True) == cr.EXIT_RISE
    assert "src/b.py" not in baseline_text(repo), "a refused update writes nothing"


def test_allow_additions_adds_to_the_baseline(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/b.py", "P = 'D:/x/y'\n")
    assert run_mode(repo, update=True, allow=True) == cr.EXIT_PASS
    assert '{"key": "src/b.py", "counts": {"no-drive-path": 1}}' in baseline_text(repo)
    assert run_mode(repo) == cr.EXIT_PASS


def test_missing_baseline_fails_instead_of_passing(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_mode(repo) == cr.EXIT_RISE
    assert "baseline .conventions-ratchet-baseline.json is missing" in capsys.readouterr().out


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"version": 9, "entries": []}',
        '{"version": 1, "entries": [{"key": "a"}]}',
        '{"version": 1, "entries": [{"key": "a", "counts": {"no-such-rule": 1}}]}',
        '{"version": 1, "entries": [{"key": "a", "counts": {"no-window": 0}}]}',
    ],
)
def test_unreadable_baseline_exits_two(repo: Path, text: str) -> None:
    (repo / cr.DEFAULT_BASELINE).write_text(text, encoding="utf-8")
    assert run_mode(repo) == cr.EXIT_CONFIG


def test_disabled_or_absent_stage_exits_zero_and_says_so(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".fleet.toml").write_text('layer = "x"\n', encoding="utf-8")
    assert run_mode(tmp_path) == cr.EXIT_PASS
    assert "not enabled" in capsys.readouterr().out
    assert run_mode(tmp_path, init=True) == cr.EXIT_CONFIG


def test_untracked_excluded_and_vendored_files_are_not_scanned(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "src/scratch.py", "P = 'D:/x/y'\n", track=False)
    write(repo, "src/vend/x.py", "P = 'D:/x/y'\n")
    write(repo, "src/gen/y.py", "P = 'D:/x/y'\n")
    (repo / ".fleet.toml").write_text(
        '[conventions_ratchet]\nenabled = true\nrules = ["no-drive-path"]\nexclude = ["src/gen/**"]\n'
        '[vendored]\nx = { dest = "src/vend/" }\n',
        encoding="utf-8",
    )
    assert run_mode(repo) == cr.EXIT_PASS


def test_no_baseline_is_ever_read_as_evidence(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    git(repo, "add", "-f", cr.DEFAULT_BASELINE)
    write(repo, ".dead-code-ratchet-baseline.json", '{"note": "E:/old/data subprocess.run([\'x\'])"}\n')
    write(repo, "notes.txt", "C:/Users/someone\n")
    capsys.readouterr()
    assert run_mode(repo) == cr.EXIT_PASS
    assert "PASS (1 baselined hit(s) in 1 file(s), none new" in capsys.readouterr().out
    assert run_mode(repo, update=True) == cr.EXIT_PASS
    assert '{"key": "src/a.py", "counts": {"no-drive-path": 1}}' in baseline_text(repo)


# ------------------------------------------------------- not confirmed

MODES = ({}, {"update": True}, {"update": True, "allow": True})


@pytest.mark.parametrize(
    ("body", "says"),
    [
        pytest.param(b"def broken(:\n", "does not parse (line 1)", id="syntax"),
        pytest.param(b"x = 'caf\xe9'\n", "does not parse", id="not-utf8"),
    ],
)
def test_a_module_that_does_not_parse_is_not_confirmed_in_every_mode(
    repo: Path, body: bytes, says: str, capsys: pytest.CaptureFixture[str]
) -> None:
    run_mode(repo, init=True)
    (repo / "src" / "bad.py").write_bytes(body)
    git(repo, "add", "src/bad.py")
    for kwargs in MODES:
        assert run_mode(repo, **kwargs) == cr.EXIT_NOT_CONFIRMED
        out = capsys.readouterr().out
        assert "NOT CONFIRMED: src/bad.py" in out and says in out
    (repo / cr.DEFAULT_BASELINE).unlink()
    assert run_mode(repo, init=True) == cr.EXIT_NOT_CONFIRMED
    assert not (repo / cr.DEFAULT_BASELINE).exists(), "--init writes nothing it could not confirm"


@pytest.mark.parametrize(
    ("var", "value", "says"),
    [("GIT_DIR", "no-such-git-dir", "git ls-files"), ("PATH", "empty", "git could not start")],
)
def test_git_that_cannot_list_the_tree_is_not_confirmed(
    repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], var: str, value: str, says: str
) -> None:
    run_mode(repo, init=True)
    monkeypatch.setenv(var, str(repo / value))
    assert run_mode(repo) == cr.EXIT_NOT_CONFIRMED
    assert says in capsys.readouterr().out


def test_main_rejects_allow_additions_without_update(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        cr.main(["--allow-additions"])
    assert exc.value.code == 2
    assert "--allow-additions" in capsys.readouterr().err


# ------------------------------------------------------------ self-adoption

def test_scaffold_adopts_the_stage_and_commits_a_parseable_baseline() -> None:
    cfg, _ = cr.load_config(REPO_ROOT)
    assert cfg is not None, "the scaffold adopts its own stage first"
    assert (REPO_ROOT / cfg.baseline).is_file()
    cr.read_baseline(REPO_ROOT / cfg.baseline)


def test_gate_runs_the_stage_after_the_dead_code_ratchet_and_before_mypy() -> None:
    text = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    before, stage, mypy = (
        text.index(s) for s in ('Invoke-Stage "dead code ratchet"', 'Invoke-Stage "conventions ratchet"',
                                'Invoke-Stage "mypy')
    )
    assert before < stage < mypy
    assert "scripts/conventions_ratchet.py" in text


def test_the_script_is_catalogued_so_it_is_mypy_gated_and_drift_checked() -> None:
    from scripts.vendored_catalog import load_catalog

    assert load_catalog(REPO_ROOT)["conventions_ratchet"] == {"src": "scripts/conventions_ratchet.py"}


def test_every_rule_is_documented_with_the_line_it_enforces() -> None:
    doc = (REPO_ROOT / "docs" / "conventions-ratchet.md").read_text(encoding="utf-8")
    for rule in cr.RULES:
        assert f"### `{rule}`" in doc, f"docs/conventions-ratchet.md has no section for {rule}"
