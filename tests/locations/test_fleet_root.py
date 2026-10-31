"""Unit tests for the fleet-root resolver.

One test per resolution step, one per precedence edge, and the
could-not-resolve case. The load-bearing ones are the "set but wrong" tests:
a bad ``FLEET_ROOT`` or config value must raise, never fall through to the
checkout parent, or a typo silently points fleet code at the wrong tree.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import src.fleet_root
from src.fleet_root import (
    FLEET_ROOT_ENV,
    FleetRootError,
    fleet_config_path,
    fleet_root,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No ambient override or real config leaks in from the developer's machine."""
    monkeypatch.delenv(FLEET_ROOT_ENV, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config-home"))


def _write_config(text: str) -> Path:
    config = fleet_config_path()
    config.parent.mkdir(parents=True)
    config.write_text(text, encoding="utf-8")
    return config


def _checkout(tmp_path: Path, *, git_as_file: bool = False) -> Path:
    """A fake ``<root>/repo`` checkout; returns a module file inside it."""
    repo = tmp_path / "root" / "repo"
    (repo / "src").mkdir(parents=True)
    if git_as_file:
        (repo / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
    else:
        (repo / ".git").mkdir()
    module = repo / "src" / "fleet_root.py"
    module.write_text("", encoding="utf-8")
    return module


# ---------------------------------------------------------- step 1: env var

def test_env_var_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / "env-root"
    root.mkdir()
    _write_config(f"root = '{(tmp_path / 'other').as_posix()}'\n")
    monkeypatch.setenv(FLEET_ROOT_ENV, str(root))
    assert fleet_root(anchor=_checkout(tmp_path)) == root


def test_env_var_missing_directory_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(FLEET_ROOT_ENV, str(tmp_path / "absent"))
    with pytest.raises(FleetRootError, match="FLEET_ROOT is not an existing directory"):
        fleet_root(anchor=_checkout(tmp_path))


def test_env_var_relative_path_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(FLEET_ROOT_ENV, "relative/root")
    with pytest.raises(FleetRootError, match="not an absolute path"):
        fleet_root(anchor=_checkout(tmp_path))


def test_blank_env_var_is_unset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(FLEET_ROOT_ENV, "   ")
    assert fleet_root(anchor=_checkout(tmp_path)) == tmp_path / "root"


# ------------------------------------------------------ step 2: config file

def test_config_file_used_when_env_unset(tmp_path: Path) -> None:
    root = tmp_path / "config-root"
    root.mkdir()
    _write_config(f"root = '{root.as_posix()}'\n")
    assert fleet_root(anchor=_checkout(tmp_path)) == root


def test_config_path_defaults_under_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert fleet_config_path() == Path.home() / ".config" / "fleet" / "fleet.toml"


def test_config_without_root_key_falls_through(tmp_path: Path) -> None:
    _write_config("other = 'value'\n")
    assert fleet_root(anchor=_checkout(tmp_path)) == tmp_path / "root"


def test_config_bad_root_value_raises(tmp_path: Path) -> None:
    _write_config(f"root = '{(tmp_path / 'absent').as_posix()}'\n")
    with pytest.raises(FleetRootError, match="not an existing directory"):
        fleet_root(anchor=_checkout(tmp_path))


def test_config_non_string_root_raises(tmp_path: Path) -> None:
    _write_config("root = 3\n")
    with pytest.raises(FleetRootError, match="non-empty string"):
        fleet_root(anchor=_checkout(tmp_path))


def test_malformed_config_raises(tmp_path: Path) -> None:
    _write_config("root = \n")
    with pytest.raises(FleetRootError, match="cannot read fleet config"):
        fleet_root(anchor=_checkout(tmp_path))


# --------------------------------------------------- step 3: checkout parent

def test_checkout_parent_when_nothing_configured(tmp_path: Path) -> None:
    assert fleet_root(anchor=_checkout(tmp_path)) == tmp_path / "root"


def test_worktree_git_file_marks_the_checkout(tmp_path: Path) -> None:
    assert fleet_root(anchor=_checkout(tmp_path, git_as_file=True)) == tmp_path / "root"


def test_default_anchor_is_this_repo() -> None:
    repo = Path(src.fleet_root.__file__).resolve().parents[1]
    assert fleet_root() == repo.parent


# ------------------------------------------------------- nothing resolves

def test_unresolvable_raises_instead_of_guessing(tmp_path: Path) -> None:
    loose = tmp_path / "loose" / "fleet_root.py"
    loose.parent.mkdir()
    loose.write_text("", encoding="utf-8")
    with pytest.raises(FleetRootError, match="not inside a git checkout"):
        fleet_root(anchor=loose)
