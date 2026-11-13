"""Tests for the docs ratchet's `bare-command` rule.

A fenced shell block that calls bare `python`, `pip` or a venv-installed tool
resolves to the system interpreter in a repo whose convention is a `.venv`
called by path. The rule counts each such line as a marker; the venv
interpreter by path and venv creation stay legal.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import docs_ratchet as dr
from tests._git_repo import git, write

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the stage enabled and one clean README."""
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text("[docs_ratchet]\nenabled = true\n", encoding="utf-8")
    write(tmp_path, "README.md", "# App\n")
    return tmp_path


def run_mode(root: Path, *, init: bool = False) -> int:
    return dr.run(root, init=init, update=False, allow_additions=False)


def bare(text: str) -> list[dr.Marker]:
    return [m for m in dr.scan_text(text, venv_commands=True) if m.kind == "bare-command"]


def fenced(body: str, tag: str = "bash") -> str:
    return f"Run it:\n\n```{tag}\n{body}\n```\n"


# ------------------------------------------------------------- flagged

@pytest.mark.parametrize(
    "line",
    [
        "python app.py",
        "python3 -m pytest",
        "python -m pip install -r requirements.txt",
        "pip install -r requirements.txt",
        "pip3 install ruff",
        "pytest -q",
        "ruff check .",
        "mypy src",
        "streamlit run app/app.py",
        "uvicorn app.main:app",
        "python.exe scripts/x.py",
        "  python indented.py",
    ],
)
def test_a_bare_interpreter_or_venv_tool_is_flagged(line: str) -> None:
    assert len(bare(fenced(line))) == 1


@pytest.mark.parametrize("tag", ["", "bash", "sh", "shell", "powershell", "pwsh", "ps1", "bat", "cmd"])
def test_every_shell_tag_and_an_untagged_fence_is_scanned(tag: str) -> None:
    assert len(bare(fenced("pip install x", tag))) == 1


@pytest.mark.parametrize("tag", ["python", "toml", "text", "json", "yaml"])
def test_a_non_shell_fence_is_not_scanned(tag: str) -> None:
    assert bare(fenced("python app.py", tag)) == []


def test_a_command_after_a_chain_operator_is_flagged() -> None:
    assert len(bare(fenced("cd repo && pip install -r requirements.txt"))) == 1
    assert len(bare(fenced("cd repo; python app.py"))) == 1


def test_a_shell_prompt_is_stripped_before_the_command() -> None:
    assert len(bare(fenced("$ python app.py"))) == 1
    assert len(bare(fenced("PS C:\\repo> pip install x", "powershell"))) == 1


def test_a_console_block_reads_only_prompt_lines() -> None:
    body = "$ python app.py\npython is the output here\n"
    assert [m.line for m in bare(fenced(body, "console"))] == [4]


def test_the_marker_names_its_line_and_command() -> None:
    (marker,) = bare("intro\n\n```bash\ncd repo\npip install x\n```\n")
    assert marker.line == 5
    assert "pip install x" in marker.text


# ------------------------------------------------------------- legal

@pytest.mark.parametrize(
    "line",
    [
        ".venv\\Scripts\\python.exe -m pytest",
        "& .\\.venv\\Scripts\\python.exe app.py",
        "./.venv/bin/python -m pytest",
        ".venv/bin/pip install -r requirements.txt",
        "python -m venv .venv",
        "python3 -m venv .venv",
        "py -m venv .venv",
        "py -3.12 -m venv .venv",
        "# python in a comment",
        "REM python in a comment",
        "git status",
        "npx playwright test",
        "echo python",
    ],
)
def test_venv_paths_venv_creation_and_other_commands_pass(line: str) -> None:
    assert bare(fenced(line)) == []


def test_a_continuation_line_is_an_argument_not_a_command() -> None:
    assert bare(fenced("docker run --rm \\\n  python app.py")) == []
    assert bare(fenced("Invoke-Thing `\n  pip", "powershell")) == []


def test_an_exempt_comment_beside_the_block_skips_it() -> None:
    text = "<!-- bare-command-exempt: runs inside the container image -->\n```bash\npython app.py\n```\n"
    assert bare(text) == []


def test_an_exempt_comment_without_a_reason_is_not_honoured() -> None:
    text = "<!-- bare-command-exempt: -->\n```bash\npython app.py\n```\n"
    assert len(bare(text)) == 1


def test_the_exemption_covers_only_the_next_block() -> None:
    text = ("<!-- bare-command-exempt: container -->\n```bash\npython a.py\n```\n\n"
            "```bash\npython b.py\n```\n")
    assert [m.line for m in bare(text)] == [7]


def test_the_rule_is_off_unless_the_repo_has_a_venv_convention() -> None:
    assert dr.scan_text(fenced("python app.py")) == []


def test_bare_commands_do_not_change_the_history_count() -> None:
    assert [m.kind for m in dr.scan_text(fenced("python app.py #1"), venv_commands=True)] == ["bare-command"]


# ------------------------------------------------- the convention signal

@pytest.mark.parametrize(
    ("gitignore", "expected"),
    [(".venv/\n", True), ("/.venv\n", True), ("node_modules/\n.venv\n", True), ("venv/\n", False), ("", False)],
)
def test_a_gitignored_venv_is_the_convention_signal(tmp_path: Path, gitignore: str, expected: bool) -> None:
    (tmp_path / ".gitignore").write_text(gitignore, encoding="utf-8")
    assert dr.venv_convention(tmp_path) is expected


def test_no_gitignore_means_no_venv_convention(tmp_path: Path) -> None:
    assert dr.venv_convention(tmp_path) is False


def test_a_bare_command_fails_the_ratchet_in_a_venv_repo(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, ".gitignore", ".venv/\n")
    run_mode(repo, init=True)
    write(repo, "README.md", "# App\n\n```bash\npip install x\n```\n")
    assert run_mode(repo) == dr.EXIT_RISE
    out = capsys.readouterr().out
    assert "bare-command" in out and "README.md" in out


def test_a_bare_command_passes_in_a_repo_without_a_venv_convention(repo: Path) -> None:
    run_mode(repo, init=True)
    write(repo, "README.md", "# App\n\n```bash\npip install x\n```\n")
    assert run_mode(repo) == dr.EXIT_PASS


# ------------------------------------------------------------ self-adoption

def test_the_scaffold_docs_carry_no_bare_command_and_no_baseline_for_one() -> None:
    cfg, vendored = dr.load_config(REPO_ROOT)
    assert cfg is not None
    assert dr.venv_convention(REPO_ROOT), "the scaffold ignores .venv, so the rule is on here"
    scan = dr.count_tree(REPO_ROOT, cfg, vendored)
    hits = [f"{path}:{m.line}: {m.text}" for path, found in scan.markers.items() for m in found if m.kind == "bare-command"]
    assert hits == []
