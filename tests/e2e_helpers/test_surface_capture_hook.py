"""The design-surface capture hook's pure contract, no browser needed.

`surface()` is a no-op with the capture env var unset, rejects a bad name or a
missing capture directory before it touches the page, and in capture mode the
collection hook deselects every test whose own source never calls `surface(`.
The page stand-in fails on any use, so none of this can reach a browser; the
in-page capture itself is pinned by `tests/e2e/_surface_hook_checks.py`.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from playwright.sync_api import Page

from tests.e2e._surface import (
    CAPTURE_ENV,
    SurfaceCaptureError,
    pytest_collection_modifyitems,
    surface,
)


def _capture_dir(root: Path) -> Path:
    """A prepared capture directory; its script never runs, the page is untouchable."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "script.js").write_text("(params) => ({})", encoding="utf-8")
    (root / "params.json").write_text("{}", encoding="utf-8")
    return root


class _Untouchable:
    """A page stand-in that fails the test on any use."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"surface() touched the page ({name}) when it must not")


def test_unset_env_is_a_noop(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    page = cast(Page, _Untouchable())
    for value in (None, ""):
        if value is None:
            monkeypatch.delenv(CAPTURE_ENV, raising=False)
        else:
            monkeypatch.setenv(CAPTURE_ENV, value)
        # Not even the name is looked at: the gate path is one env lookup.
        surface(page, "Not A Valid Name")
        assert list(tmp_path.iterdir()) == []


def test_misuse_fails_loudly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    page = cast(Page, _Untouchable())
    monkeypatch.setenv(CAPTURE_ENV, str(_capture_dir(tmp_path / "cap")))
    for bad in ("", "Jobs.Sheet", "jobs sheet", "jobs..sheet", "-jobs", "jobs.", "jobs_sheet"):
        with pytest.raises(ValueError):
            surface(page, bad)
    monkeypatch.setenv(CAPTURE_ENV, str(tmp_path / "missing"))
    with pytest.raises(SurfaceCaptureError):
        surface(page, "jobs.sort-sheet")


def _opens_and_captures() -> None:
    surface(cast(Page, None), "jobs.sort-sheet")


def _delegates_to_a_helper() -> None:
    _opens_and_captures()


def _helper_test_surface() -> None:  # the name merely ends in "surface"
    pass


def test_capture_mode_deselects_tests_that_never_call_surface(monkeypatch: pytest.MonkeyPatch) -> None:
    def make_items() -> list[Any]:
        return [
            SimpleNamespace(function=_opens_and_captures),
            SimpleNamespace(function=_delegates_to_a_helper),
            SimpleNamespace(function=_helper_test_surface),
            SimpleNamespace(),  # no python function at all
            SimpleNamespace(function=len),  # source unreadable: unknown, so kept
        ]

    deselected: list[Any] = []
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=lambda items: deselected.extend(items)))

    monkeypatch.delenv(CAPTURE_ENV, raising=False)
    items = make_items()
    pytest_collection_modifyitems(cast(pytest.Config, config), items)
    assert len(items) == 5 and deselected == []

    monkeypatch.setenv(CAPTURE_ENV, "somewhere")
    items = make_items()
    pytest_collection_modifyitems(cast(pytest.Config, config), items)
    assert [getattr(i, "function", None) for i in items] == [_opens_and_captures, len]
    assert len(deselected) == 3
