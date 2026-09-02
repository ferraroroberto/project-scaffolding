"""Unit tests for the `[components]` catalog reader (project-scaffolding#230).

Two jobs, mirroring `test_classify_e2e.py`'s split:

1. Prove the *mechanism* — parsing, the fatal-on-absent contract (an empty
   catalog must raise, never quietly yield nothing), and the Python-subset
   derivation that feeds `mypy --strict`.
2. Act as the **anti-drift guard** for this repo's own declaration — load the
   real `.fleet.toml` `[components]` block and assert every declared `src`
   exists, every `_vendored/` UI folder is declared, every historically-gated
   module is still in the mypy list, and `verify-before-ship.ps1` really derives
   its list from here instead of carrying a second hand-kept copy.

Job 2 is the load-bearing half. #230's defect was not a bug in any one file: it
was that "what this scaffold publishes" lived in three partial restatements, so
a component could be present in one and absent from the others with nothing to
notice. A catalog that can silently fall behind the tree reintroduces exactly
that, one component at a time.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.vendored_catalog import (
    CatalogError,
    load_catalog,
    mypy_targets,
    parse_components,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDORED_UI_DIR = REPO_ROOT / "app" / "webapp" / "static" / "_vendored"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify-before-ship.ps1"

# The mypy --strict list `verify-before-ship.ps1` carried by hand before #230.
# Every one of these must still be derived from the catalog — a refactor that
# quietly narrows the gate is the regression this pins.
HISTORICALLY_GATED = (
    "app/tray/single_instance.py",
    "app/tray/watchdog.py",
    "src/notify/",
    "src/doc_capture/",
    "tests/e2e/_geometry.py",
    "tests/e2e/_e2e_live_guard.py",
    "tests/e2e/_browser_sweep.py",
    "src/pooled_http.py",
    "scripts/classify_e2e.py",
    "src/build_info.py",
)


# --------------------------------------------------------------- mechanism

def test_parses_a_well_formed_table() -> None:
    catalog = parse_components(
        '[components]\n'
        'nav = { src = "app/webapp/static/_vendored/nav" }\n'
        'no_window = { src = "src/no_window.py" }\n'
    )
    assert catalog == {
        "nav": {"src": "app/webapp/static/_vendored/nav"},
        "no_window": {"src": "src/no_window.py"},
    }


@pytest.mark.parametrize(
    "toml_text",
    [
        pytest.param("", id="empty-file"),
        pytest.param('layer = "governance"\nicon = "x"\n', id="ordinary-fleet-toml"),
        pytest.param("[components]\n", id="declared-but-empty"),
    ],
)
def test_absent_catalog_raises_rather_than_returning_empty(toml_text: str) -> None:
    """No catalog is fatal, unlike an adopter's absent `[vendored]` table.

    An empty list would let the gate's `mypy --strict` stage pass while checking
    nothing, and the drift scan report "no undeclared carriers" while knowing of
    no components at all — a silent partial dressed as a clean result, which is
    the whole defect #230 is about.
    """
    with pytest.raises(CatalogError):
        parse_components(toml_text)


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param('nav = "app/webapp/static/_vendored/nav"', id="bare-string-not-a-table"),
        pytest.param("nav = { dest = \"x\" }", id="no-src-key"),
        pytest.param('nav = { src = "" }', id="empty-src"),
    ],
)
def test_malformed_entry_raises(entry: str) -> None:
    with pytest.raises(CatalogError):
        parse_components(f"[components]\n{entry}\n")


def test_mypy_targets_picks_python_only(tmp_path: Path) -> None:
    """A `.py` component passes through; a package gets a trailing slash; a
    directory with no Python in it (every `_vendored/` UI folder) is skipped."""
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("", encoding="utf-8")
    (tmp_path / "ui").mkdir()
    (tmp_path / "ui" / "nav.css").write_text("", encoding="utf-8")

    catalog = {
        "pkg": {"src": "pkg"},
        "ui": {"src": "ui"},
        "single": {"src": "a/b.py"},
    }
    assert mypy_targets(catalog, repo_root=tmp_path) == ["a/b.py", "pkg/"]


# ------------------------------------------------- anti-drift over the real repo

@pytest.fixture(scope="module")
def real_catalog() -> dict[str, dict[str, str]]:
    return load_catalog(REPO_ROOT)


def test_every_declared_component_exists(real_catalog: dict[str, dict[str, str]]) -> None:
    missing = sorted(k for k, v in real_catalog.items() if not (REPO_ROOT / v["src"]).exists())
    assert not missing, f"catalog declares components with no file on disk: {missing}"


def test_every_vendored_ui_component_is_declared(real_catalog: dict[str, dict[str, str]]) -> None:
    """A new `_vendored/<name>/` folder must be catalogued in the same PR.

    Undeclared is exactly the state #230 found across six repos: present on
    disk, invisible to `/propagate-vendored`, silently skipped by every wave.
    """
    on_disk = {p.name for p in VENDORED_UI_DIR.iterdir() if p.is_dir()}
    declared = {Path(v["src"]).name for v in real_catalog.values()
                if v["src"].startswith("app/webapp/static/_vendored/")}
    assert on_disk == declared, (
        f"undeclared UI components: {sorted(on_disk - declared)}; "
        f"declared but absent: {sorted(declared - on_disk)}"
    )


def test_mypy_gate_still_covers_every_historically_gated_module(
    real_catalog: dict[str, dict[str, str]],
) -> None:
    targets = set(mypy_targets(real_catalog, repo_root=REPO_ROOT))
    assert set(HISTORICALLY_GATED) <= targets, (
        f"the catalog-derived mypy list dropped: {sorted(set(HISTORICALLY_GATED) - targets)}"
    )


def test_verify_script_derives_its_list_from_the_catalog() -> None:
    """The gate must call the catalog, and must not have regrown a literal list."""
    text = VERIFY_SCRIPT.read_text(encoding="utf-8")
    assert "vendored_catalog.py" in text, "verify-before-ship.ps1 no longer reads the catalog"
    assert '"app/tray/single_instance.py"' not in text, (
        "verify-before-ship.ps1 has regrown a hand-maintained $VendoredModules list; "
        "the catalog in .fleet.toml [components] is the single source (#230)"
    )
