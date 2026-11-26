"""Test support the browser suite imports from outside `tests/e2e/` still routes to it.

This repo's `.fleet.toml` routes `tests/` to no browser run, so a shared helper
kept there needs its own rule. The check follows the suite's imports rather
than a hand-kept list, so a new helper cannot slip through.
"""
from __future__ import annotations

import ast
from pathlib import Path

from scripts.classify_e2e import classify, load_config

REPO_ROOT = Path(__file__).resolve().parents[2]


def _imported_modules(source: Path) -> list[str]:
    modules: list[str] = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules += [node.module, *(f"{node.module}.{alias.name}" for alias in node.names)]
    return modules


def _loaded_by_the_suite() -> list[str]:
    """The suite, its root conftest and every `tests/` module they import, directly or not."""
    pending = [*(REPO_ROOT / "tests" / "e2e").rglob("*.py"), REPO_ROOT / "tests" / "conftest.py"]
    loaded = set(pending)
    while pending:
        for module in _imported_modules(pending.pop()):
            found = REPO_ROOT.joinpath(*module.split(".")).with_suffix(".py")
            if module.startswith("tests.") and found.is_file() and found not in loaded:
                loaded.add(found)
                pending.append(found)
    return sorted(f.relative_to(REPO_ROOT).as_posix() for f in loaded)


def test_real_test_support_the_suite_imports_never_skips_the_browser_run() -> None:
    cfg = load_config(REPO_ROOT / ".fleet.toml")
    paths = _loaded_by_the_suite()
    assert "tests/host/_synthetic_host.py" in paths, "the import walk found no support module"
    assert [p for p in paths if classify([p], cfg).tier == "skip"] == []
