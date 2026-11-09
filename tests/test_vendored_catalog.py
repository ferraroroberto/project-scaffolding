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

import ast
import tomllib
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
ARCHITECTURE_DOC = REPO_ROOT / "docs" / "architecture.mmd"

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


def test_every_requires_names_a_declared_component(real_catalog: dict[str, dict[str, str]]) -> None:
    """`/propagate-vendored` expands a component with its `requires`; a name that
    is not in the catalog would send a wave looking for a file that does not exist."""
    table = tomllib.loads((REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8"))["components"]
    requires = {k: v["requires"] for k, v in table.items() if "requires" in v}
    assert requires.get("conventions_ratchet") == ["conventions_readers", "conventions_state"], (
        "conventions_ratchet imports scripts/conventions_readers.py and conventions_state.py; re-vendoring it alone exits 3"
    )
    unknown = sorted(d for deps in requires.values() for d in deps if d not in real_catalog)
    assert not unknown, f"`requires` names components the catalog does not declare: {unknown}"


def _loaded_siblings(script: Path) -> set[str]:
    """Module names a script loads through its `_load_sibling("<name>")` helper."""
    tree = ast.parse(script.read_text(encoding="utf-8"))
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_load_sibling"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def test_every_loaded_sibling_is_required() -> None:
    """A script that loads a sibling through `_load_sibling` exits 3 when the sibling is
    missing beside it, so its entry must `requires` the sibling or `/propagate-vendored`
    re-vendors the script alone and the adopter's gate goes red."""
    table = tomllib.loads((REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8"))["components"]
    by_src = {v["src"]: k for k, v in table.items()}
    missing: list[str] = []
    for key, entry in sorted(table.items()):
        script = REPO_ROOT / entry["src"]
        if script.suffix != ".py" or not script.is_file():
            continue
        for sibling in sorted(_loaded_siblings(script)):
            sibling_key = by_src.get(f"scripts/{sibling}.py")
            if sibling_key is None:
                missing.append(f"{key} loads scripts/{sibling}.py, which the catalog does not declare")
            elif sibling_key not in entry.get("requires", []):
                missing.append(f'{key} loads {sibling_key} but its entry has no requires = ["{sibling_key}"]')
    assert not missing, "\n".join(missing)


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


def test_every_declared_component_is_in_the_architecture_diagram(
    real_catalog: dict[str, dict[str, str]],
) -> None:
    """Structural-check for project-scaffolding#502 (recurring docs audit
    finding): `src/compression.py` and `scripts/box_lock_gate.ps1` landed
    without a node in `docs/architecture.mmd`, which `CLAUDE.md`'s "Internal
    architecture" section requires in the same PR. A catalog entry is the
    cheapest proxy for "this component exists" — its basename, `.py`/`.ps1`
    extension included, must appear somewhere in the diagram text; a
    directory-shaped component (its `src` has no suffix) is checked without
    one, since the diagram and `.fleet.toml` both drop it for those (e.g.
    `notify/`, `day-row/`).
    """
    text = ARCHITECTURE_DOC.read_text(encoding="utf-8")
    missing = sorted(
        name for name in (Path(v["src"]).name for v in real_catalog.values())
        if name not in text
    )
    assert not missing, (
        f"docs/architecture.mmd has no node naming: {missing} — add one in the "
        f"same PR that added the component (CLAUDE.md 'Internal architecture')"
    )
