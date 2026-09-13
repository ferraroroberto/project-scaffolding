"""Unit tests for the diff-proportionate e2e classifier (project-scaffolding#180).

Two jobs:

1. Prove the *mechanism* — first-match-wins rule ordering, the STATIC/FULL/NONE
   tier maths across a mixed diff, and above all the **fail-safe**: an empty
   diff, an unmatched path, a missing/empty/invalid `[e2e]` table all route to
   the full suite. Uncertainty must never narrow coverage.
2. Act as the **anti-drift guard** for this repo's own declaration — load the
   real `.fleet.toml` `[e2e]` block and assert representative paths land in the
   tier their rule intends, so a later edit that silently under-routes a real
   surface fails here.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.classify_e2e import (
    Category,
    E2EConfig,
    Rule,
    Surface,
    classify,
    load_config,
    load_surfaces,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
REAL_FLEET_TOML = REPO_ROOT / ".fleet.toml"


# --------------------------------------------------------------- fail-safe core

def _cfg(*rules: Rule, **kw: object) -> E2EConfig:
    """A 'declared' config from explicit rules for mechanism tests."""
    return E2EConfig(rules=list(rules), source="declared", **kw)  # type: ignore[arg-type]


def test_missing_table_routes_full() -> None:
    cfg = E2EConfig(rules=[], source="missing")
    r = classify(["app/webapp/static/x.svg"], cfg)
    assert r.tier == "full"
    assert "fail-safe" in r.reasons[0]


def test_empty_table_routes_full() -> None:
    cfg = E2EConfig(rules=[], source="empty")
    assert classify(["src/foo.py"], cfg).tier == "full"


def test_invalid_toml_routes_full() -> None:
    cfg = E2EConfig(rules=[], source="invalid")
    assert classify(["docs/x.md"], cfg).tier == "full"


def test_empty_diff_routes_full() -> None:
    cfg = _cfg(Rule(tier=Category.NONE, prefix="src/"))
    r = classify([], cfg)
    assert r.tier == "full"
    assert "empty-diff" in r.reasons[0]


def test_unmatched_path_is_fail_safe_full() -> None:
    # A path matching no declared rule must escalate to full, not fall to skip.
    cfg = _cfg(Rule(tier=Category.NONE, prefix="src/"))
    r = classify(["totally/unknown/thing.xyz"], cfg)
    assert r.tier == "full"
    assert any("unclassified" in reason for reason in r.reasons)


# --------------------------------------------------------------- tier maths

def test_static_only_routes_static() -> None:
    cfg = _cfg(
        Rule(tier=Category.STATIC, prefix="static/", extensions=("svg",)),
        static_pytest_target="tests/e2e/test_smoke.py",
        static_browsers=("chromium",),
    )
    r = classify(["static/a.svg"], cfg)
    assert r.tier == "static"
    assert r.pytest_target == "tests/e2e/test_smoke.py"
    assert r.browsers == ["chromium"]


def test_none_only_routes_skip() -> None:
    cfg = _cfg(Rule(tier=Category.NONE, prefix="src/", extensions=("py",)))
    r = classify(["src/a.py"], cfg)
    assert r.tier == "skip"
    assert r.pytest_target == ""


def test_mixed_static_and_full_takes_full() -> None:
    cfg = _cfg(
        Rule(tier=Category.STATIC, prefix="static/", extensions=("svg",)),
        Rule(tier=Category.FULL, prefix="app/"),
    )
    assert classify(["static/a.svg", "app/x.py"], cfg).tier == "full"


def test_mixed_none_and_static_takes_static() -> None:
    cfg = _cfg(
        Rule(tier=Category.STATIC, prefix="static/", extensions=("svg",)),
        Rule(tier=Category.NONE, prefix="src/"),
    )
    assert classify(["static/a.svg", "src/x.py"], cfg).tier == "static"


def test_first_match_wins() -> None:
    # The more-specific STATIC rule is declared first, so an html under the
    # vendored dir is STATIC even though a later FULL rule also prefix-matches.
    cfg = _cfg(
        Rule(tier=Category.STATIC, prefix="app/static/_vendored/", extensions=("html",)),
        Rule(tier=Category.FULL, prefix="app/static/"),
    )
    assert classify(["app/static/_vendored/nav.html"], cfg).tier == "static"
    # ...but a .css under the same vendored dir misses the html-only STATIC rule
    # and falls through to the FULL prefix rule.
    assert classify(["app/static/_vendored/nav.css"], cfg).tier == "full"


def test_bare_rule_matches_nothing() -> None:
    # A rule with neither prefix/path/extensions must not match everything.
    cfg = _cfg(Rule(tier=Category.NONE))
    # 'src/a.py' matches no real rule -> fail-safe full, not skip.
    assert classify(["src/a.py"], cfg).tier == "full"


def test_backslash_paths_normalized() -> None:
    cfg = _cfg(Rule(tier=Category.NONE, prefix="src/", extensions=("py",)))
    assert classify(["src\\a.py"], cfg).tier == "skip"


# ------------------------------------------------ anti-drift guard (real .fleet.toml)

def test_real_fleet_toml_declares_usable_e2e_table() -> None:
    cfg = load_config(REAL_FLEET_TOML)
    assert cfg.source == "declared", (
        "this repo's .fleet.toml must declare a usable [e2e] table"
    )
    assert cfg.rules, "at least one [[e2e.rule]] must be declared"


def test_real_rules_route_representative_paths() -> None:
    """Representative paths land in the tier their rule intends.

    Fails loudly if a future edit to the .fleet.toml [e2e] block silently
    under-routes a real e2e surface (the anti-drift requirement in #180).
    """
    cfg = load_config(REAL_FLEET_TOML)

    def tier(*paths: str) -> str:
        return classify(list(paths), cfg).tier

    # Real browser surface -> full. A vendored component's .css/.js is a
    # full-tier path its declared surface narrows (#258) -- never skip/static.
    assert tier("app/webapp/static/_vendored/card/card.css") == "surface"
    assert tier("app/webapp/static/_vendored/nav/nav-tabs.js") == "surface"
    assert tier("app/app.py") == "full"
    assert tier("app/views/welcome.py") == "full"
    assert tier("app/styles/light.css") == "full"
    assert tier("app/tray/single_instance.py") == "full"
    assert tier("tests/e2e/test_smoke.py") == "full"
    assert tier("tests/_streamlit_lifecycle.py") == "full"
    assert tier("tests/_port_probe.py") == "full"

    # Inert static assets -> static.
    assert tier("app/webapp/static/icons/foo.svg") == "static"
    assert tier("app/webapp/static/_vendored/nav/nav-tabs.html") == "static"

    # Backend / tooling / docs -> skip.
    assert tier("src/pipeline/example.py") == "skip"
    assert tier("tests/test_config.py") == "skip"
    assert tier("docs/e2e-routing.md") == "skip"
    assert tier("README.md") == "skip"
    assert tier("scripts/classify_e2e.py") == "skip"
    assert tier(".fleet.toml") == "skip"
    assert tier(".github/workflows/main-gate-watch.yml.template") == "skip"

    # Mixed real diff (static asset + backend) -> static; add a page -> full.
    assert tier("app/webapp/static/icons/foo.svg", "src/x.py") == "static"
    assert tier("app/webapp/static/icons/foo.svg", "app/app.py") == "full"


# ------------------------------------------------ surface tier (#258)

def _surf(name: str, targets: tuple[str, ...], *, prefixes: tuple[str, ...] = (),
          paths: tuple[str, ...] = ()) -> Surface:
    return Surface(name=name, pytest_targets=targets, prefixes=prefixes, paths=paths)


_SURFACE_RULES = (
    Rule(tier=Category.STATIC, prefix="app/static/", extensions=("svg",)),
    Rule(tier=Category.FULL, prefix="app/"),
    Rule(tier=Category.FULL, prefix="tests/e2e/"),
    Rule(tier=Category.NONE, prefix="docs/"),
)


def _surface_cfg(*surfaces: Surface, note: str = "") -> E2EConfig:
    return _cfg(
        *_SURFACE_RULES,
        static_pytest_target="tests/e2e/test_smoke.py",
        surfaces=list(surfaces),
        surfaces_note=note,
    )


_BOARD = _surf("board", ("tests/e2e/test_board.py",),
               prefixes=("app/board/", "app/static/board/"), paths=("tests/e2e/test_board.py",))
_JOBS = _surf("jobs", ("tests/e2e/test_jobs.py", "tests/e2e/test_jobs_agenda.py"),
              prefixes=("app/jobs/",))


def test_single_surface_diff_routes_surface() -> None:
    r = classify(["app/board/board.js", "tests/e2e/test_board.py", "docs/x.md"],
                 _surface_cfg(_BOARD, _JOBS))
    assert r.tier == "surface"
    assert r.surface == "board"
    assert r.pytest_target == "tests/e2e/test_board.py"
    assert r.browsers == []  # suite-default browsers, exactly like full


def test_surface_target_list_is_space_separated() -> None:
    r = classify(["app/jobs/jobs.css"], _surface_cfg(_BOARD, _JOBS))
    assert r.tier == "surface"
    assert r.pytest_target == "tests/e2e/test_jobs.py tests/e2e/test_jobs_agenda.py"


def test_static_path_riding_a_surface_adds_the_smoke_target() -> None:
    r = classify(["app/board/board.js", "app/static/board/icon.svg"], _surface_cfg(_BOARD))
    assert r.tier == "surface"
    assert r.pytest_target == "tests/e2e/test_board.py tests/e2e/test_smoke.py"


def test_static_path_outside_the_surface_keeps_whole_full() -> None:
    # "Inert" markup can be the page another harness drives, so a static path
    # the winning surface does not own must not ride along on a smoke run.
    r = classify(["app/board/board.js", "app/static/icon.svg"], _surface_cfg(_BOARD))
    assert r.tier == "full"
    assert r.pytest_target == "tests/e2e"


def test_no_surfaces_declared_keeps_whole_full() -> None:
    r = classify(["app/board/board.js"], _surface_cfg())
    assert r.tier == "full"
    assert r.pytest_target == "tests/e2e"


def test_unclassified_path_keeps_whole_full_even_inside_a_surface() -> None:
    # `legacy/` matches no rule, yet a surface claims it: unclassified must win.
    legacy = _surf("legacy", ("tests/e2e/test_board.py",), prefixes=("legacy/",))
    r = classify(["legacy/thing.xyz"], _surface_cfg(legacy))
    assert r.tier == "full"
    assert r.pytest_target == "tests/e2e"


def test_full_path_outside_every_surface_keeps_whole_full() -> None:
    r = classify(["app/board/board.js", "app/shared/styles.css"], _surface_cfg(_BOARD))
    assert r.tier == "full"
    assert r.pytest_target == "tests/e2e"


def test_multi_surface_diff_keeps_whole_full() -> None:
    r = classify(["app/board/board.js", "app/jobs/jobs.css"], _surface_cfg(_BOARD, _JOBS))
    assert r.tier == "full"
    assert r.pytest_target == "tests/e2e"


def test_path_in_two_surfaces_keeps_whole_full() -> None:
    overlap = _surf("board-too", ("tests/e2e/test_other.py",), prefixes=("app/board/",))
    r = classify(["app/board/board.js"], _surface_cfg(_BOARD, overlap))
    assert r.tier == "full"
    assert r.pytest_target == "tests/e2e"


def test_empty_diff_keeps_whole_full_with_surfaces() -> None:
    r = classify([], _surface_cfg(_BOARD))
    assert r.tier == "full"
    assert r.pytest_target == "tests/e2e"


def test_missing_table_keeps_whole_full_with_surfaces() -> None:
    cfg = E2EConfig(rules=[], source="missing", surfaces=[_BOARD])
    assert classify(["app/board/board.js"], cfg).tier == "full"


def test_none_only_diff_still_skips_with_surfaces() -> None:
    assert classify(["docs/x.md"], _surface_cfg(_BOARD)).tier == "skip"


def test_disabled_surfaces_note_is_surfaced_in_full_reasons() -> None:
    r = classify(["app/board/board.js"], _surface_cfg(note="surfaces disabled: because"))
    assert r.tier == "full"
    assert "surfaces disabled: because" in r.reasons


def _write_targets(root: Path, *names: str) -> None:
    for name in names:
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text("", encoding="utf-8")


def test_load_surfaces_absent_is_no_surfaces_and_no_note(tmp_path: Path) -> None:
    assert load_surfaces(None, tmp_path) == ([], "")


def test_load_surfaces_rejects_targets_outside_the_suite(tmp_path: Path) -> None:
    _write_targets(tmp_path, "tests/e2e/test_board.py", "tests/test_unit.py", "outside/t.py")
    outside = str((tmp_path / "outside" / "t.py").resolve())
    for target in ("../outside/t.py", "tests/e2e/../../outside/t.py", outside, "tests", "tests/test_unit.py"):
        surfaces, note = load_surfaces(
            [{"name": "board", "prefixes": ["app/board/"], "pytest_targets": ["tests/e2e/test_board.py", target]}],
            tmp_path,
        )
        assert surfaces == [], target
        assert "surfaces disabled" in note, target


def test_load_surfaces_parses_a_valid_entry(tmp_path: Path) -> None:
    _write_targets(tmp_path, "tests/e2e/test_board.py")
    surfaces, note = load_surfaces(
        [{"name": "board", "prefixes": ["app/board/"], "pytest_targets": ["tests/e2e/test_board.py"]}],
        tmp_path,
    )
    assert note == ""
    assert [s.name for s in surfaces] == ["board"]


def test_load_surfaces_missing_target_disables_every_surface(tmp_path: Path) -> None:
    _write_targets(tmp_path, "tests/e2e/test_board.py")
    surfaces, note = load_surfaces(
        [
            {"name": "board", "prefixes": ["app/board/"], "pytest_targets": ["tests/e2e/test_board.py"]},
            {"name": "jobs", "prefixes": ["app/jobs/"], "pytest_targets": ["tests/e2e/test_gone.py"]},
        ],
        tmp_path,
    )
    assert surfaces == []
    assert "does not exist" in note


def test_load_surfaces_malformed_entries_disable_every_surface(tmp_path: Path) -> None:
    _write_targets(tmp_path, "tests/e2e/t.py")
    good = {"name": "ok", "prefixes": ["app/ok/"], "pytest_targets": ["tests/e2e/t.py"]}
    malformed = [
        "not a table",
        {"prefixes": ["app/x/"], "pytest_targets": ["tests/e2e/t.py"]},                 # no name
        {"name": "x", "prefixes": ["app/x/"]},                                 # no targets
        {"name": "x", "prefixes": ["app/x/"], "pytest_targets": []},           # empty targets
        {"name": "x", "prefixes": ["app/x/"], "pytest_targets": "tests/e2e/t.py"},       # not a list
        {"name": "x", "pytest_targets": ["tests/e2e/t.py"]},                             # no matcher
        {"name": "x", "prefixes": [""], "pytest_targets": ["tests/e2e/t.py"]},           # empty prefix
        {"name": "x", "prefixes": ["app/x/"], "pytest_targets": ["a b.py"]},   # whitespace
        {"name": "ok", "prefixes": ["app/y/"], "pytest_targets": ["tests/e2e/t.py"]},    # duplicate name
        {"name": " ", "prefixes": ["app/x/"], "pytest_targets": ["tests/e2e/t.py"]},     # blank name
        {"name": "x\nE2E_TIER=skip", "prefixes": ["app/x/"], "pytest_targets": ["tests/e2e/t.py"]},  # forged line
        {"name": "x", "prefixes": "app/x/", "paths": ["a"], "pytest_targets": ["tests/e2e/t.py"]},  # str prefixes
        {"name": "x", "prefixes": ["app/x/"], "paths": "a", "pytest_targets": ["tests/e2e/t.py"]},  # str paths
        {"name": "x", "prefixes": ["app/board"], "pytest_targets": ["tests/e2e/t.py"]},  # no dir boundary
    ]
    for bad in malformed:
        surfaces, note = load_surfaces([good, bad], tmp_path)
        assert surfaces == [], bad
        assert "surfaces disabled" in note, bad
    assert load_surfaces({"name": "x"}, tmp_path)[0] == []  # not a list at all


def test_load_config_reads_surfaces_relative_to_the_toml(tmp_path: Path) -> None:
    _write_targets(tmp_path, "tests/e2e/test_board.py")
    toml = tmp_path / ".fleet.toml"
    toml.write_text(
        '[e2e]\n'
        '[[e2e.rule]]\ntier = "full"\nprefix = "app/"\n'
        '[[e2e.surface]]\nname = "board"\nprefixes = ["app/board/"]\n'
        'pytest_targets = ["tests/e2e/test_board.py"]\n',
        encoding="utf-8",
    )
    cfg = load_config(toml)
    assert [s.name for s in cfg.surfaces] == ["board"]
    assert classify(["app/board/x.js"], cfg).tier == "surface"


def test_real_surfaces_route_representative_paths() -> None:
    """This repo's declared surfaces narrow what they own and nothing shared (#258)."""
    cfg = load_config(REAL_FLEET_TOML)
    assert cfg.surfaces_note == "", cfg.surfaces_note
    assert {s.name for s in cfg.surfaces} == {"nav", "components", "geometry"}

    def route(*paths: str) -> tuple[str, str]:
        r = classify(list(paths), cfg)
        return r.tier, r.pytest_target

    assert route("app/webapp/static/_vendored/nav/nav-tabs.css") == (
        "surface", "tests/e2e/test_vendored_nav.py")
    assert route("app/webapp/static/_vendored/card/card.css") == (
        "surface", "tests/e2e/test_vendored_components.py tests/e2e/test_vendored_nav.py")
    assert route("tests/e2e/_geometry.py") == ("surface", "tests/e2e/test_geometry_helper.py")

    # Shared infrastructure belongs to no surface -> whole suite.
    assert route("tests/e2e/conftest.py") == ("full", "tests/e2e")
    assert route("tests/e2e/_color_assertions.py") == ("full", "tests/e2e")
    assert route("app/webapp/static/_vendored/demo.html") == ("full", "tests/e2e")
    # A shared static path riding along with a surface change keeps the whole suite.
    assert route("app/webapp/static/_vendored/nav/nav-tabs.css",
                 "app/webapp/static/_vendored/icons/icons-sprite.html") == ("full", "tests/e2e")
    assert route("app/webapp/static/_vendored/icons/icons.js") == ("full", "tests/e2e")
    assert route("app/app.py") == ("full", "tests/e2e")
    # Two surfaces in one diff -> whole suite.
    assert route("app/webapp/static/_vendored/nav/nav-tabs.css",
                 "app/webapp/static/_vendored/card/card.css") == ("full", "tests/e2e")


def test_real_surface_helpers_are_only_imported_by_their_own_targets() -> None:
    """A surface-owned `tests/e2e/_*.py` helper must not be imported outside it.

    Otherwise editing the helper would narrow to a surface that does not run
    every test the edit can break.
    """
    cfg = load_config(REAL_FLEET_TOML)
    suite = REPO_ROOT / "tests" / "e2e"
    for surface in cfg.surfaces:
        for helper in (p for p in surface.paths if Path(p).name.startswith("_") and p.endswith(".py")):
            module = Path(helper).stem
            pattern = re.compile(rf"^\s*(from|import)\s.*\b{re.escape(module)}\b", re.MULTILINE)
            importers = {
                f"tests/e2e/{f.relative_to(suite).as_posix()}"
                for f in suite.rglob("*.py")
                if f.name != Path(helper).name and pattern.search(f.read_text(encoding="utf-8"))
            }
            assert importers <= set(surface.pytest_targets), (surface.name, helper, importers)
