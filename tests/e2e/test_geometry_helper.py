"""The rendered-geometry helper's own suite (issue #157).

Drives `_geometry.py` against the hermetic twins in `_fixtures/geometry/`:
every check must PASS on `compliant.html` and FAIL on `violating.html` at
every 320/390/430/772px x light/dark matrix leg. Each leg carries a theme
boot-check (the computed background actually flipped) so a matrix leg that
silently failed to apply can never read as conformance — the same fail-loud
idiom as `test_vendored_nav.py`'s coarse-pointer assert.

Both twins are **one test node per matrix leg**, not one per (check x leg):
the checks are independent by fixture construction, so a per-check split just
re-loads the same page four more times per leg to re-prove fixed-pixel facts.
Keep it that way — the suite is measured against CLAUDE.md's "< 15 tests"
rule in collected nodes, not in `def`s (#209).

Engines: the gate's bare `pytest` runs Chromium (like the vendored-component
suites); the geometry math is engine-agnostic. One manual two-engine pass
before re-vendoring:

    .venv\\Scripts\\python.exe -m pytest tests/e2e/test_geometry_helper.py \\
        --browser chromium --browser webkit
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Page

from tests.e2e._geometry import (
    MATRIX,
    apply_matrix_leg,
    assert_chart_ticks,
    assert_min_target,
    assert_no_horizontal_overflow,
    assert_no_overlap,
    chart_dataset_cues,
    effective_rect,
    effective_rects,
    matrix_id,
)
from tests.e2e.conftest import serve_directory

_FIXTURES = Path(__file__).resolve().parent / "_fixtures" / "geometry"

# demo.html's --bg per theme — the boot-check that a leg's theme actually took.
_EXPECTED_BG = {"light": "rgb(255, 255, 255)", "dark": "rgb(13, 17, 23)"}


@pytest.fixture(scope="session")
def geometry_server() -> Iterator[str]:
    """Serve tests/e2e/_fixtures/geometry over HTTP for the session."""
    with serve_directory(_FIXTURES) as base_url:
        yield base_url


def _load(page: Page, base_url: str, name: str) -> None:
    page.goto(f"{base_url}/{name}")
    page.wait_for_selector("body[data-fixture-ready='1']")


def _apply_leg_checked(page: Page, width: int, theme: str) -> None:
    """apply_matrix_leg + fail-loud guard that the theme really flipped."""
    apply_matrix_leg(page, width, theme)
    background = page.eval_on_selector(
        "body", "el => getComputedStyle(el).backgroundColor"
    )
    assert background == _EXPECTED_BG[theme], (
        f"matrix leg theme={theme} did not take: body background {background}"
    )


# ---------------------------------------------------------------------------
# Rect math

def test_pseudo_ring_expands_34px_visual_to_44px_effective(
    geometry_server: str, page: Page
) -> None:
    _load(page, geometry_server, "compliant.html")
    target = effective_rect(page.locator("#lonePlus"))
    assert target.visual.width == pytest.approx(34)
    assert target.visual.height == pytest.approx(34)
    assert target.effective.width == pytest.approx(44)
    assert target.effective.height == pytest.approx(44)


def test_switch_track_expands_26px_to_44px_vertically(
    geometry_server: str, page: Page
) -> None:
    _load(page, geometry_server, "compliant.html")
    target = effective_rect(page.locator("#loneToggle"))
    assert target.visual.height == pytest.approx(26)
    assert target.effective.width == pytest.approx(44)
    assert target.effective.height == pytest.approx(44)


def test_element_without_hit_pseudo_keeps_visual_rect(
    geometry_server: str, page: Page
) -> None:
    _load(page, geometry_server, "compliant.html")
    target = effective_rect(page.locator(".cluster .day").first)
    assert target.effective == target.visual


def test_zero_matches_fail_loud(geometry_server: str, page: Page) -> None:
    _load(page, geometry_server, "compliant.html")
    with pytest.raises(AssertionError, match="no elements match"):
        effective_rects(page.locator(".does-not-exist"))


# ---------------------------------------------------------------------------
# Compliant twin: every check passes at every matrix leg

@pytest.mark.parametrize(("width", "theme"), MATRIX, ids=map(matrix_id, MATRIX))
def test_compliant_twin_passes_all_checks(
    geometry_server: str, page: Page, width: int, theme: str
) -> None:
    _load(page, geometry_server, "compliant.html")
    _apply_leg_checked(page, width, theme)

    assert_min_target(page.locator("#lonePlus"))
    assert_min_target(page.locator("#loneToggle"))
    assert_min_target(page.locator(".cluster .day"))
    assert_no_overlap(page.locator(".cluster .day"))
    assert_no_horizontal_overflow(page)
    assert_chart_ticks(page, "#chart", max_ticks=4)
    cues = chart_dataset_cues(page, "#chart")
    assert len(cues) == 3


# ---------------------------------------------------------------------------
# Violating twin: every check fails at every matrix leg

# One entry per contract the violating twin breaks: a name for the failure
# report, the call under test, and the substring its AssertionError must carry.
# `violating.html` authors each violation on its own independently-targetable
# element, so the four checks below cannot mask one another.
_VIOLATIONS: tuple[tuple[str, Callable[[Page], None], str], ...] = (
    (
        "assert_min_target(#tinyClose)",
        lambda page: assert_min_target(page.locator("#tinyClose")),
        "below the 44px floor",
    ),
    (
        "assert_no_overlap(.crowded .icon-btn)",
        lambda page: assert_no_overlap(page.locator(".crowded .icon-btn")),
        "overlap",
    ),
    (
        "assert_chart_ticks(#badChart)",
        lambda page: assert_chart_ticks(page, "#badChart", max_ticks=8),
        "tick budget",
    ),
    (
        "assert_no_horizontal_overflow()",
        lambda page: assert_no_horizontal_overflow(page),
        "horizontal overflow",
    ),
)


@pytest.mark.parametrize(("width", "theme"), MATRIX, ids=map(matrix_id, MATRIX))
def test_violating_twin_fails_every_check(
    geometry_server: str, page: Page, width: int, theme: str
) -> None:
    """Every check FAILS on the violating twin, at every matrix leg.

    The mirror image of `test_compliant_twin_passes_all_checks`: one node per
    leg exercising all four contracts, not one node per (contract x leg). The
    four violations are fixed-pixel geometry and static Chart.js config, so
    each was previously re-proving the same fact across all eight legs — 32
    nodes for four facts, against this repo's own "< 15 tests" rule (#209).

    Every contract is still asserted at every leg, and each is reported by
    name: the loop collects outcomes instead of stopping at the first, so a
    check that silently stopped failing is named even when another regressed
    alongside it — strictly more diagnostic than the four `pytest.raises`
    blocks this replaces.
    """
    _load(page, geometry_server, "violating.html")
    _apply_leg_checked(page, width, theme)

    failures: list[str] = []
    for name, check, expected in _VIOLATIONS:
        try:
            check(page)
        except AssertionError as exc:
            if expected not in str(exc):
                failures.append(
                    f"{name}: failed as required, but the message is missing "
                    f"{expected!r} — got: {exc}"
                )
        else:
            failures.append(
                f"{name}: did NOT fail on the violating twin — the check has "
                "stopped catching its contract"
            )
    assert not failures, "\n".join(failures)


# ---------------------------------------------------------------------------
# Chart cue reads

def test_dataset_cues_round_trip(geometry_server: str, page: Page) -> None:
    _load(page, geometry_server, "compliant.html")
    cues = chart_dataset_cues(page, "#chart")
    assert [cue.label for cue in cues] == [
        "Generation",
        "Grid-supplied",
        "Consumption",
    ]
    assert [cue.border_dash for cue in cues] == [[], [8, 4], [2, 4]]
    assert [cue.point_style for cue in cues] == ["circle", "rectRot", "triangle"]


def test_chart_lookup_failures_are_named(geometry_server: str, page: Page) -> None:
    _load(page, geometry_server, "compliant.html")
    with pytest.raises(AssertionError, match="no canvas matches"):
        chart_dataset_cues(page, "#missingCanvas")
