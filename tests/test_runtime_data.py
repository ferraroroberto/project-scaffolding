"""Unit tests for the runtime-data root resolver (project-scaffolding#243).

The load-bearing assertions are the *precedence* ones. Every fleet app that
adopts this module already has a full-path override its unit and e2e harnesses
set (``TELEMETRY_DB_PATH``, ``WR_DB_PATH``, …); if that override ever stopped
winning, a test run would silently write into the live production store — the
exact pollution bug `home-automation#296` fixed once already.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.runtime_data import (
    FLEET_DATA_ROOT_ENV,
    WINDOWS_DEFAULT_ROOT,
    app_dir_env_var,
    fleet_data_root,
    runtime_data_dir,
    runtime_db_path,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ambient override leaks in from the developer's own shell."""
    for name in (FLEET_DATA_ROOT_ENV, "XDG_DATA_HOME", "DEMO_APP_DATA_DIR", "DEMO_DB_PATH"):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------------- env-var names

def test_app_dir_env_var_normalises_the_slug() -> None:
    assert app_dir_env_var("home-automation") == "HOME_AUTOMATION_DATA_DIR"
    assert app_dir_env_var("task-os") == "TASK_OS_DATA_DIR"
    assert app_dir_env_var("demo") == "DEMO_DATA_DIR"


# ------------------------------------------------------------------- the root

@pytest.mark.skipif(sys.platform != "win32", reason="Windows default root")
def test_windows_default_root_is_c_sqlite() -> None:
    assert fleet_data_root() == WINDOWS_DEFAULT_ROOT


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX default root")
def test_posix_default_root_follows_xdg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", "/var/lib/fleet")
    assert fleet_data_root() == Path("/var/lib/fleet/sqlite")


def test_fleet_root_env_overrides_the_platform_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(FLEET_DATA_ROOT_ENV, str(tmp_path))
    assert fleet_data_root() == tmp_path
    assert runtime_data_dir("demo") == tmp_path / "demo"


def test_blank_env_value_is_not_an_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty or whitespace-only var is an unset var, not a root of ``''``."""
    monkeypatch.setenv(FLEET_DATA_ROOT_ENV, "   ")
    assert fleet_data_root() != Path("   ")


# ------------------------------------------------------------------ per app

def test_each_app_gets_its_own_subdirectory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole point of the per-app level: two apps, same filename, no clash."""
    monkeypatch.setenv(FLEET_DATA_ROOT_ENV, str(tmp_path))
    a = runtime_db_path("home-automation", "telemetry.sqlite3")
    b = runtime_db_path("voice-transcriber", "telemetry.sqlite3")
    assert a != b
    assert a.name == b.name == "telemetry.sqlite3"


def test_app_dir_env_beats_the_fleet_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(FLEET_DATA_ROOT_ENV, str(tmp_path / "root"))
    monkeypatch.setenv("DEMO_DATA_DIR", str(tmp_path / "elsewhere"))
    assert runtime_data_dir("demo") == tmp_path / "elsewhere"


# --------------------------------------------------------------- precedence

def test_full_path_override_wins_over_everything(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A harness pointing DEMO_DB_PATH at a temp file must never be outranked."""
    monkeypatch.setenv(FLEET_DATA_ROOT_ENV, str(tmp_path / "root"))
    monkeypatch.setenv("DEMO_DATA_DIR", str(tmp_path / "elsewhere"))
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "harness" / "t.sqlite3"))
    assert runtime_db_path("demo", "t.sqlite3", env_var="DEMO_DB_PATH") == (
        tmp_path / "harness" / "t.sqlite3"
    )


def test_unset_full_path_override_falls_through(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(FLEET_DATA_ROOT_ENV, str(tmp_path))
    assert runtime_db_path("demo", "t.sqlite3", env_var="DEMO_DB_PATH") == (
        tmp_path / "demo" / "t.sqlite3"
    )


# ------------------------------------------------------------- side effects

def test_resolution_is_pure_by_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """No mkdir at import or resolution time — only when a caller asks."""
    monkeypatch.setenv(FLEET_DATA_ROOT_ENV, str(tmp_path / "root"))
    runtime_db_path("demo", "t.sqlite3")
    assert not (tmp_path / "root").exists()


def test_create_makes_the_app_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(FLEET_DATA_ROOT_ENV, str(tmp_path / "root"))
    path = runtime_db_path("demo", "t.sqlite3", create=True)
    assert path.parent.is_dir()


def test_create_makes_the_override_parent_too(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A harness override pointing into a not-yet-existing dir still connects."""
    monkeypatch.setenv("DEMO_DB_PATH", str(tmp_path / "deep" / "nested" / "t.sqlite3"))
    path = runtime_db_path("demo", "t.sqlite3", env_var="DEMO_DB_PATH", create=True)
    assert path.parent.is_dir()
