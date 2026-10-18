"""The design-surface capture hook's own suite (issue #408).

Drives `_surface.py` against the hermetic static page in `_fixtures/surface/`
with a stub in-page script, so nothing here depends on fleet-config. Pins the
contract the hook's docstring makes: a true no-op when `DESIGN_SURFACE_CAPTURE`
is unset, both themes flipped in place and restored, first-call-wins, name
validation, a throwing script recorded as its own state, byte-stable output, and
the capture-mode collection filter.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
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
from tests.e2e.conftest import serve_directory

_FIXTURES = Path(__file__).resolve().parent / "_fixtures" / "surface"

# The page's --bg per theme, as computed on <body>.
_LIGHT_BG, _DARK_BG = "rgb(255, 255, 255)", "rgb(13, 17, 23)"

_STUB_SCRIPT = """(params) => {
  const cs = el => getComputedStyle(el);
  return {
    bg: cs(document.body).backgroundColor,
    title: document.getElementById('title').textContent,
    size: params.size,
    buttons: [...document.querySelectorAll('button')].map(b => ({
      id: b.id, fontSize: cs(b).fontSize, fontWeight: cs(b).fontWeight,
      rect: b.getBoundingClientRect().toJSON(),
    })),
  };
}"""


@pytest.fixture(scope="session")
def surface_server() -> Iterator[str]:
    """Serve tests/e2e/_fixtures/surface over HTTP for the session."""
    with serve_directory(_FIXTURES) as base_url:
        yield base_url


def _capture_dir(root: Path, *, script: str = _STUB_SCRIPT, storage_key: str | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "script.js").write_text(script, encoding="utf-8")
    (root / "params.json").write_text(json.dumps({"size": 3}), encoding="utf-8")
    if storage_key:
        (root / "capture.json").write_text(json.dumps({"theme_storage_key": storage_key}), encoding="utf-8")
    return root


def _read(path: Path) -> dict[str, Any]:
    return cast("dict[str, Any]", json.loads(path.read_text(encoding="utf-8")))


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


@pytest.mark.parametrize("storage_key", [None, "fixture-theme"], ids=["media-only", "storage-key"])
def test_capture_flips_both_themes_in_place_and_restores(
    page: Page, surface_server: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, storage_key: str | None
) -> None:
    out = _capture_dir(tmp_path / "cap", storage_key=storage_key)
    monkeypatch.setenv(CAPTURE_ENV, str(out))
    page.goto(f"{surface_server}/page.html")
    page.emulate_media(color_scheme="light")
    if storage_key:
        page.evaluate(
            "k => { document.documentElement.dataset.theme = 'light'; localStorage.setItem(k, 'light'); }",
            storage_key,
        )

    surface(page, "jobs.sort-sheet")

    light, dark = _read(out / "jobs.sort-sheet.light.json"), _read(out / "jobs.sort-sheet.dark.json")
    assert (light["theme"], dark["theme"]) == ("light", "dark")
    assert (light["metrics"]["bg"], dark["metrics"]["bg"]) == (_LIGHT_BG, _DARK_BG)
    assert light["metrics"]["size"] == 3  # the params file reached the script
    assert (light["observed"]["dark"], dark["observed"]["dark"]) == (False, True)
    assert light["error"] is None and light["surface"] == "jobs.sort-sheet"
    assert light["viewport"] == dict(page.viewport_size or {})
    assert light["engine"] == page.context.browser.browser_type.name  # type: ignore[union-attr]
    assert light["phone"] is False
    for theme in ("light", "dark"):
        assert (out / f"jobs.sort-sheet.{theme}.png").stat().st_size > 0
    # Nothing but the prepared inputs and the four outputs.
    expected = {"script.js", "params.json"} | ({"capture.json"} if storage_key else set())
    assert {p.name for p in out.iterdir()} == expected | {
        f"jobs.sort-sheet.{t}.{ext}" for t in ("light", "dark") for ext in ("json", "png")
    }

    # The page is left as the test had it.
    assert page.evaluate("matchMedia('(prefers-color-scheme: dark)').matches") is False
    if storage_key:
        assert page.evaluate("document.documentElement.getAttribute('data-theme')") == "light"
        assert page.evaluate("k => localStorage.getItem(k)", storage_key) == "light"
    else:
        assert page.evaluate("document.documentElement.hasAttribute('data-theme')") is False

    # First call wins: a second call under the same name changes nothing.
    before = (out / "jobs.sort-sheet.light.json").read_bytes()
    page.evaluate("document.getElementById('title').textContent = 'Changed'")
    surface(page, "jobs.sort-sheet")
    assert (out / "jobs.sort-sheet.light.json").read_bytes() == before


def test_misuse_fails_loudly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    page = cast(Page, _Untouchable())
    monkeypatch.setenv(CAPTURE_ENV, str(_capture_dir(tmp_path / "cap")))
    for bad in ("", "Jobs.Sheet", "jobs sheet", "jobs..sheet", "-jobs", "jobs.", "jobs_sheet"):
        with pytest.raises(ValueError):
            surface(page, bad)
    monkeypatch.setenv(CAPTURE_ENV, str(tmp_path / "missing"))
    with pytest.raises(SurfaceCaptureError):
        surface(page, "jobs.sort-sheet")


def test_a_throwing_script_is_recorded_not_swallowed(
    page: Page, surface_server: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    out = _capture_dir(tmp_path / "cap", script="(params) => { throw new Error('boom'); }")
    monkeypatch.setenv(CAPTURE_ENV, str(out))
    page.goto(f"{surface_server}/page.html")
    surface(page, "jobs.sort-sheet")
    for theme in ("light", "dark"):
        record = _read(out / f"jobs.sort-sheet.{theme}.json")
        assert record["metrics"] is None
        assert "boom" in record["error"]


def test_two_runs_write_identical_json(
    page: Page, surface_server: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runs: list[dict[str, bytes]] = []
    for n in (1, 2):
        out = _capture_dir(tmp_path / f"run{n}")
        monkeypatch.setenv(CAPTURE_ENV, str(out))
        page.goto(f"{surface_server}/page.html")
        surface(page, "jobs.sort-sheet")
        runs.append({p.name: p.read_bytes() for p in sorted(out.glob("*.json")) if p.name != "params.json"})
    assert runs[0].keys() == {"jobs.sort-sheet.light.json", "jobs.sort-sheet.dark.json"}
    assert runs[0] == runs[1]


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
