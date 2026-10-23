"""README's e2e file inventory may not drift from tests/e2e/ on disk.

The e2e section of the README names every `test_*.py` file under
`tests/e2e/` one by one, so a reader sees the regression suite's shape
without listing it themselves. A file added or removed from `tests/e2e/`
without updating that prose is exactly the kind of staleness an audit keeps
re-finding: the list silently drifting while the suite moves on.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
E2E_DIR = REPO_ROOT / "tests" / "e2e"
README = REPO_ROOT / "README.md"


def _actual_test_files() -> set[str]:
    return {p.name for p in E2E_DIR.glob("test_*.py")}


def _mentioned_test_files() -> set[str]:
    text = README.read_text(encoding="utf-8")
    return set(re.findall(r"`(test_\w+\.py)`", text))


def test_every_e2e_test_file_is_named_in_the_readme() -> None:
    missing = _actual_test_files() - _mentioned_test_files()
    assert not missing, (
        f"tests/e2e/ has {sorted(missing)} but README.md's e2e section never "
        "names them -- update the file list there."
    )


def test_readme_names_no_e2e_test_file_that_no_longer_exists() -> None:
    stale = _mentioned_test_files() - _actual_test_files()
    assert not stale, (
        f"README.md names {sorted(stale)} as a tests/e2e/ file, but it no "
        "longer exists there -- the prose is stale."
    )
