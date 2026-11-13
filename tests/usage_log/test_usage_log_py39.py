"""`src/usage_log.py` stays importable on Python 3.9.

The module is vendored byte-for-byte into apps whose README promises 3.9/3.10, and
it deliberately has no `from __future__ import annotations` (FastAPI reads the
handler annotations at runtime), so a 3.10+ construct is an import-time failure
there. The gate runs a newer interpreter that would never notice one, so the
module is checked statically: it must parse as 3.9 and use none of the 3.10/3.11
spellings that parse fine but fail at runtime.
"""

from __future__ import annotations

import ast
from pathlib import Path

MODULE = Path(__file__).resolve().parents[2] / "src" / "usage_log.py"


def _tree() -> ast.Module:
    return ast.parse(MODULE.read_text(encoding="utf-8"), filename=str(MODULE), feature_version=(3, 9))


def _annotations(tree: ast.Module) -> list[ast.expr]:
    found: list[ast.expr] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            every = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
            found.extend(a.annotation for a in every if a is not None and a.annotation is not None)
            if node.returns is not None:
                found.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            found.append(node.annotation)
    return found


def test_module_parses_as_python_39() -> None:
    _tree()


def test_no_runtime_pipe_annotations() -> None:
    bad = sorted(
        {sub.lineno for ann in _annotations(_tree()) for sub in ast.walk(ann)
         if isinstance(sub, ast.BinOp) and isinstance(sub.op, ast.BitOr)}
    )
    assert not bad, f"`X | Y` annotation (3.10+) at lines {bad}: use Optional/Union from typing"


def test_no_datetime_utc() -> None:
    bad: list[int] = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.ImportFrom) and node.module == "datetime":
            bad += [node.lineno for alias in node.names if alias.name == "UTC"]
        elif isinstance(node, ast.Attribute) and node.attr == "UTC":
            bad.append(node.lineno)
        elif isinstance(node, ast.Name) and node.id == "UTC":
            bad.append(node.lineno)
    assert not bad, f"`datetime.UTC` (3.11+) at lines {sorted(set(bad))}: use datetime.timezone.utc"


def test_no_zip_strict() -> None:
    bad = [
        node.lineno
        for node in ast.walk(_tree())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "zip"
        and any(kw.arg == "strict" for kw in node.keywords)
    ]
    assert not bad, f"`zip(strict=)` (3.10+) at lines {bad}: drop it or check the lengths explicitly"
