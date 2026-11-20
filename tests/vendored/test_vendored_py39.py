"""The vendored Python modules stay valid on Python 3.9.

`scripts/tools/vendored_py39_check.py` reads each module with `ast`, so the gate
(which runs a newer interpreter that never notices) still fails on 3.10+ syntax or
on an `X | Y` that 3.9 evaluates. Two halves: the rules fire on a bad module, and
the real catalog is clean.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.tools.vendored_py39_check import check_source
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "tools" / "vendored_py39_check.py"


@pytest.mark.parametrize(
    ("source", "rule"),
    [
        ("def f(x):\n    match x:\n        case 1:\n            return 1\n", "syntax"),
        ("try:\n    pass\nexcept* ValueError:\n    pass\n", "syntax"),
        ("def f(x: int | None) -> int:\n    return 1\n", "annotation-union"),
        ("class C:\n    field: str | None = None\n", "annotation-union"),
        ("Alias = int | None\n", "runtime-union"),
        ("from __future__ import annotations\nAlias = tuple[str, ...] | str\n", "runtime-union"),
        ("def f(x):\n    return isinstance(x, int | str)\n", "runtime-union"),
    ],
)
def test_rule_fires_on_a_bad_module(source: str, rule: str) -> None:
    hits = check_source(source, "bad.py")
    assert hits, f"expected a {rule} hit"
    assert all(f": {rule}:" in hit for hit in hits), hits


@pytest.mark.parametrize(
    "source",
    [
        "from __future__ import annotations\n\n\ndef f(x: int | None) -> str | None:\n    return None\n",
        "from typing import Optional, Union\n\nAlias = Optional[int]\nOther = Union[int, str]\n",
        "def f(x: 'int | None') -> None:\n    y: int | None = x\n    return None\n",
        "FLAGS = 1 | 2\n\n\ndef g(a, b):\n    return a | b\n",
        "with (open('a') as p, open('b') as q):\n    pass\n",
    ],
)
def test_clean_modules_pass(source: str) -> None:
    assert check_source(source, "ok.py") == []


def test_hit_names_file_and_line() -> None:
    (hit,) = check_source("x = 1\nAlias = int | None\n", "pkg/mod.py")
    assert hit.startswith("pkg/mod.py:2: runtime-union:")


def test_vendored_catalog_is_clean() -> None:
    proc = subprocess.run(
        [sys.executable, "-I", str(SCRIPT)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        creationflags=NO_WINDOW,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.splitlines()[-1].startswith("PY39=clean files=")
