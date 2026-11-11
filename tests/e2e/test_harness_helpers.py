"""The harness helpers' own suite: the layout lint, the surface capture hook and the helper cwd isolation.

The layout lint: a broken fixture fails by name, its fixed twin passes.

`fixtures/layout/sheet.html` carries three deliberate defects (a reason line
overflowing a phone sheet, a clipped chip label, an overlapping button);
`?fixed=1` repairs them. Each case runs one `capture_states` call, which
covers phone and desktop in light and dark, so the matrix costs one case per
page, not four. A Streamlit case proves the same helper runs against a real
`streamlit run` with no per-engine code. A gallery case holds the vendored
component gallery to the lint with no `allow` entries: every adopter copies
those components, so a defect there ships fleet-wide.

The surface hook (`_surface.py`) is driven against the hermetic static page in
`fixtures/surface/` with a stub in-page script, so nothing here depends on
fleet-config; the checks are in `_surface_hook_checks.py`. The cwd isolation
case (`_cwd_isolation_checks.py`) pins that neither the Playwright driver nor
any browser helper holds this checkout as its working directory.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Playwright

from tests.e2e import _cwd_isolation_checks, _surface_hook_checks
from tests.e2e._cases import cases
from tests.e2e._layout_lint import Finding, capture_states
from tests.e2e.conftest import serve_directory

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "layout"
_SURFACE_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "surface"


@pytest.fixture(scope="module")
def layout_server() -> Iterator[str]:
    with serve_directory(_FIXTURES) as base_url:
        yield base_url


@pytest.fixture(scope="session")
def surface_server() -> Iterator[str]:
    """Serve tests/e2e/fixtures/surface over HTTP for the session."""
    with serve_directory(_SURFACE_FIXTURES) as base_url:
        yield base_url


@pytest.fixture()
def out_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("ui-proof")


def _named(findings: tuple[Finding, ...]) -> dict[str, str]:
    return {f.kind: f.element for f in findings if f.fails}


def _check_broken_sheet_fails_with_three_named_findings(layout_server: str, browser: Browser, out_dir: Path) -> None:
    def sheet(page: Page) -> None:
        page.goto(f"{layout_server}/sheet.html")

    with pytest.raises(AssertionError, match="layout lint failed"):
        capture_states(browser, {"fixture.sheet": sheet}, out_dir=out_dir)
    manifest = capture_states(browser, {"fixture.sheet": sheet}, out_dir=out_dir, check=False)

    assert [(e.viewport, e.theme) for e in manifest.entries] == [
        ("phone", "light"), ("phone", "dark"), ("desktop", "light"), ("desktop", "dark"),
    ]
    for entry in manifest.entries:
        assert Path(entry.screenshot).is_file()
        named = _named(entry.findings)
        assert named["clipped"].endswith("span.chip-label"), entry
        overlap = next(f for f in entry.findings if f.kind == "overlap")
        assert (overlap.element, overlap.other) == (
            "main > div.actions > button.retry", "main > div.actions > button.dismiss",
        ), entry
        # The reason line only runs past the sheet at phone width.
        if entry.viewport == "phone":
            assert set(named) == {"overflow", "clipped", "overlap"}, entry
            assert named["overflow"].endswith("div.sheet-row"), entry
        else:
            assert set(named) == {"clipped", "overlap"}, entry
    assert manifest.path.is_file()


def _check_fixed_sheet_passes_and_allow_needs_a_reason(layout_server: str, browser: Browser, out_dir: Path) -> None:
    def sheet(page: Page) -> None:
        page.goto(f"{layout_server}/sheet.html?fixed=1")

    manifest = capture_states(browser, {"fixture.sheet-fixed": sheet}, out_dir=out_dir)
    assert len(manifest.entries) == 4
    assert not manifest.failing, manifest.summary()

    with pytest.raises(ValueError, match="needs a reason"):
        capture_states(browser, {"fixture.sheet-fixed": sheet}, out_dir=out_dir, allow={".chip": " "})
    with pytest.raises(ValueError, match="inside the git work tree"):
        capture_states(browser, {"fixture.sheet-fixed": sheet}, out_dir=_FIXTURES)


def _check_component_gallery_lints_clean(static_server: str, browser: Browser, out_dir: Path) -> None:
    def gallery(page: Page) -> None:
        page.goto(f"{static_server}/_vendored/demo.html")
        page.wait_for_selector("body[data-demo-ready='1']")

    manifest = capture_states(browser, {"gallery.all": gallery}, out_dir=out_dir)
    assert len(manifest.entries) == 4


def _check_streamlit_welcome_view_lints_clean(streamlit_app: str, browser: Browser, out_dir: Path) -> None:
    def welcome(page: Page) -> None:
        page.goto(streamlit_app)
        page.get_by_role("heading", name="Welcome to", exact=False).wait_for(timeout=20_000)

    manifest = capture_states(browser, {"streamlit.welcome": welcome}, out_dir=out_dir, allow=_STREAMLIT_ALLOW)
    assert len(manifest.entries) == 4


# Streamlit's own chrome and widget sizing, which an app cannot restyle
# without fighting the framework. Keyed on its stable data-testid hooks.
_STREAMLIT_ALLOW = {
    '[data-testid="stIconEmoji"]': "Streamlit sizes the nav emoji box narrower than its glyph",
    '[data-testid="stSidebarNavLink"]': "Streamlit's sidebar nav links are 28px tall",
    '[data-testid="stSidebarCollapseButton"] button': "Streamlit header chrome, 28px",
    '[data-testid="stMainMenuButton"]': "Streamlit header chrome, 28px",
    '[data-testid="stAppDeployButton"] button': "Streamlit header chrome, 28px",
    '[data-testid="stCheckbox"] input': "st.checkbox renders a 21px row",
}


def test_harness_helpers(
    tmp_path_factory: pytest.TempPathFactory,
    new_page: Callable[..., AbstractContextManager[Page]],
    layout_server: str,
    surface_server: str,
    browser: Browser,
    playwright: Playwright,
    static_server: str,
    streamlit_app: str,
) -> None:
    """The layout lint fails the broken sheet by name and passes the fixed twin, the gallery and Streamlit; the surface hook captures both themes; no Playwright process is rooted in this checkout."""
    with cases() as c:
        with c.case("broken_sheet_fails_with_three_named_findings"), nullcontext(tmp_path_factory.mktemp("ui-proof")) as out_dir:
            _check_broken_sheet_fails_with_three_named_findings(layout_server=layout_server, browser=browser, out_dir=out_dir)
        with c.case("fixed_sheet_passes_and_allow_needs_a_reason"), nullcontext(tmp_path_factory.mktemp("ui-proof")) as out_dir:
            _check_fixed_sheet_passes_and_allow_needs_a_reason(layout_server=layout_server, browser=browser, out_dir=out_dir)
        with c.case("component_gallery_lints_clean"), nullcontext(tmp_path_factory.mktemp("ui-proof")) as out_dir:
            _check_component_gallery_lints_clean(static_server=static_server, browser=browser, out_dir=out_dir)
        with c.case("streamlit_welcome_view_lints_clean"), nullcontext(tmp_path_factory.mktemp("ui-proof")) as out_dir:
            _check_streamlit_welcome_view_lints_clean(streamlit_app=streamlit_app, browser=browser, out_dir=out_dir)
        for storage_key in [None, "fixture-theme"]:
            with c.case(f"capture_flips_both_themes_in_place_and_restores[{storage_key}]"), new_page() as page, pytest.MonkeyPatch.context() as monkeypatch, nullcontext(tmp_path_factory.mktemp("case")) as tmp_path:
                _surface_hook_checks.check_capture_flips_both_themes_in_place_and_restores(page=page, surface_server=surface_server, monkeypatch=monkeypatch, tmp_path=tmp_path, storage_key=storage_key)
        with c.case("a_throwing_script_is_recorded_not_swallowed"), new_page() as page, pytest.MonkeyPatch.context() as monkeypatch, nullcontext(tmp_path_factory.mktemp("case")) as tmp_path:
            _surface_hook_checks.check_a_throwing_script_is_recorded_not_swallowed(page=page, surface_server=surface_server, monkeypatch=monkeypatch, tmp_path=tmp_path)
        with c.case("two_runs_write_identical_json"), new_page() as page, pytest.MonkeyPatch.context() as monkeypatch, nullcontext(tmp_path_factory.mktemp("case")) as tmp_path:
            _surface_hook_checks.check_two_runs_write_identical_json(page=page, surface_server=surface_server, monkeypatch=monkeypatch, tmp_path=tmp_path)
        with c.case("no_playwright_process_roots_in_this_checkout"), new_page() as page:
            _cwd_isolation_checks.check_no_playwright_process_roots_in_this_checkout(page=page, playwright=playwright)
