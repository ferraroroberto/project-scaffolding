"""The "not confirmed" assertions every ratchet's throwaway-repo tests share.

Each ratchet script is stdlib-only and vendored on its own, so the scripts cannot
share code; their tests can. A ratchet that cannot read a file or list the tree
exits 3 in every mode and writes no baseline, and that contract is identical.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

from tests._git_repo import git

MODES = ({}, {"update": True}, {"update": True, "allow": True})

GIT_FAILURES = [("GIT_DIR", "no-such-git-dir", "git ls-files"), ("PATH", "empty", "git could not start")]


def assert_unreadable_file_not_confirmed(
    ratchet: ModuleType,
    run_mode: Callable[..., int],
    repo: Path,
    rel: str,
    body: bytes,
    says: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A tracked file the scanner cannot read through is exit 3 in every mode, never skipped."""
    run_mode(repo, init=True)
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_bytes(body)
    git(repo, "add", rel)
    for kwargs in MODES:
        assert run_mode(repo, **kwargs) == ratchet.EXIT_NOT_CONFIRMED
        out = capsys.readouterr().out
        assert f"NOT CONFIRMED: {rel}" in out and says in out
    (repo / ratchet.DEFAULT_BASELINE).unlink()
    assert run_mode(repo, init=True) == ratchet.EXIT_NOT_CONFIRMED
    assert not (repo / ratchet.DEFAULT_BASELINE).exists(), "--init writes nothing it could not confirm"


def assert_unlistable_git_not_confirmed(
    ratchet: ModuleType,
    run_mode: Callable[..., int],
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    var: str,
    value: str,
    says: str,
) -> None:
    """A git that cannot list the tree is exit 3, not an empty tree."""
    run_mode(repo, init=True)
    monkeypatch.setenv(var, str(repo / value))
    assert run_mode(repo) == ratchet.EXIT_NOT_CONFIRMED
    assert says in capsys.readouterr().out


def git_failure_test(ratchet: ModuleType, run_mode: Callable[..., int]) -> Callable[..., None]:
    """The parametrized "git cannot list the tree" test for one ratchet's suite.

    Assign the result to a module-level `test_*` name; it asks for the suite's own `repo` fixture.
    """

    @pytest.mark.parametrize(("var", "value", "says"), GIT_FAILURES)
    def test_git_that_cannot_list_the_tree_is_not_confirmed(
        repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], var: str, value: str, says: str
    ) -> None:
        assert_unlistable_git_not_confirmed(ratchet, run_mode, repo, monkeypatch, capsys, var, value, says)

    return test_git_that_cannot_list_the_tree_is_not_confirmed
