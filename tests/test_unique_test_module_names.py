"""One pytest run must collect the whole tree.

Without `__init__.py` files, two test modules sharing a basename make a single
`python -m pytest` stop at collection with "import file mismatch", and a gate that
runs unit and e2e as separate calls would hide it.
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS = REPO_ROOT / "tests"


def test_no_two_collected_test_modules_share_a_basename() -> None:
    by_name: dict[str, list[str]] = defaultdict(list)
    for path in sorted(TESTS.rglob("test_*.py")):
        rel = path.relative_to(TESTS)
        if rel.parts[0] == "_fixtures":  # conftest.collect_ignore: synthetic adopter repos, never collected
            continue
        by_name[path.name].append(rel.as_posix())
    clashes = {name: paths for name, paths in by_name.items() if len(paths) > 1}
    assert clashes == {}, f"rename one module of each pair so a single pytest run can collect both: {clashes}"
