"""Check the vendor-verbatim Python modules against a Python 3.9 target.

Some adopters run Python 3.9, so a vendored module that only parses or imports on
3.10+ breaks them after a propagation wave. This stage fails the gate on that
before it ships, with no 3.9 interpreter needed: it reads each module's source
with the stdlib `ast` module.

The module list is the Python subset of `.fleet.toml`'s `[components]` catalog,
read through `scripts/vendored_catalog.py` (the list `mypy --strict` uses), so a
new Python component is covered the day it lands.

Rules (a hit names `<file>:<line>: <rule>: <detail>`):

  syntax            the module does not parse with the 3.9 grammar (`match`,
                    `except*`, ...), via `ast.parse(feature_version=(3, 9))`.
  annotation-union  `X | Y` in an annotation of a module without
                    `from __future__ import annotations`: 3.9 evaluates it at
                    definition time and raises `TypeError`.
  runtime-union     `X | Y` evaluated at run time anywhere else, recognised by
                    an operand that is `None` or a builtin type name, or by the
                    second argument of `isinstance` / `issubclass`.

Not covered: standard-library names missing on 3.9 (`tomllib`, `typing.Self`, ...)
and a union of two names this script cannot tell from a bitwise or.

Ends on one line: ``PY39=clean files=N`` (exit 0), ``PY39=violations N files=M``
(exit 1) or ``PY39=unknown reason=...`` (exit 3), which is never folded into
clean: an unreadable catalog or module means the claim was not established.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # a script's own dir is sys.path[0], not the repo root

from scripts.vendored_catalog import (  # noqa: E402 -- needs the sys.path line above
    CatalogError,
    load_catalog,
    mypy_targets,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TARGET = (3, 9)
# Builtin classes that appear in a runtime union; a bare `int | str` is a type union.
BUILTIN_TYPES = frozenset({
    "int", "str", "float", "bool", "bytes", "bytearray", "complex", "list", "dict",
    "set", "frozenset", "tuple", "type", "object", "range",
})


def _is_type_operand(node: ast.expr) -> bool:
    """True when `node` can only be a type (or `None`) in a union."""
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.Name):
        return node.id in BUILTIN_TYPES
    if isinstance(node, ast.Subscript):
        return _is_type_operand(node.value)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _is_type_operand(node.left) or _is_type_operand(node.right)
    return False


def _unions(node: ast.AST) -> list[ast.BinOp]:
    """Every `X | Y` expression under `node`."""
    return [n for n in ast.walk(node) if isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr)]


def _annotation_nodes(tree: ast.Module) -> tuple[list[ast.expr], list[ast.expr]]:
    """The annotations of a module as `(evaluated, never_evaluated)`.

    Definition-time annotations (arguments, returns, module and class variables)
    are evaluated when the definition runs; a variable annotation inside a
    function never is.
    """
    evaluated: list[ast.expr] = []
    skipped: list[ast.expr] = []

    def visit(node: ast.AST, in_function: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            every = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
            evaluated.extend(a.annotation for a in every if a is not None and a.annotation is not None)
            if node.returns is not None:
                evaluated.append(node.returns)
            in_function = True
        elif isinstance(node, ast.AnnAssign):
            (skipped if in_function else evaluated).append(node.annotation)
        for child in ast.iter_child_nodes(node):
            visit(child, in_function)

    visit(tree, False)
    return evaluated, skipped


def _has_future_annotations(tree: ast.Module) -> bool:
    return any(
        isinstance(n, ast.ImportFrom) and n.module == "__future__" and any(a.name == "annotations" for a in n.names)
        for n in tree.body
    )


def check_source(source: str, name: str = "<module>") -> list[str]:
    """The rule hits for one module's source, as `name:line: rule: detail` lines."""
    try:
        tree = ast.parse(source, filename=name, feature_version=TARGET)
    except SyntaxError as exc:
        return [f"{name}:{exc.lineno or 1}: syntax: {exc.msg} (not valid on Python 3.9)"]

    lazy = _has_future_annotations(tree)
    evaluated, skipped = _annotation_nodes(tree)
    annotated = {id(u) for root in [*evaluated, *skipped] for u in _unions(root)}
    hits: set[tuple[int, str]] = set()

    if not lazy:
        for union in (u for root in evaluated for u in _unions(root)):
            hits.add((union.lineno, "annotation-union: `X | Y` annotation needs `from __future__ import annotations` on 3.9"))

    for union in _unions(tree):
        if id(union) not in annotated and (_is_type_operand(union.left) or _is_type_operand(union.right)):
            hits.add((union.lineno, "runtime-union: `X | Y` between types fails when evaluated on 3.9"))
    for call in ast.walk(tree):
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in {"isinstance", "issubclass"} and len(call.args) == 2:
            for union in _unions(call.args[1]):
                hits.add((union.lineno, f"runtime-union: `{call.func.id}(..., X | Y)` fails on 3.9; pass a tuple"))
    return [f"{name}:{line}: {detail}" for line, detail in sorted(hits)]


def python_files(targets: list[str], root: Path = REPO_ROOT) -> list[Path]:
    """Expand catalog targets (a `.py` file or a `dir/` package) to module paths."""
    files: list[Path] = []
    for target in targets:
        path = root / target
        files.extend([path] if target.endswith(".py") else sorted(path.rglob("*.py")))
    return files


def main() -> int:
    try:
        files = python_files(mypy_targets(load_catalog()))
    except CatalogError as exc:
        print(f"PY39=unknown reason={exc}")
        return 3
    if not files:
        print("PY39=unknown reason=catalog declares no Python components")
        return 3

    violations: list[str] = []
    for path in files:
        rel = path.relative_to(REPO_ROOT).as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"PY39=unknown reason=cannot read {rel}: {exc}")
            return 3
        violations.extend(check_source(source, rel))

    for line in violations:
        print(line)
    if violations:
        print(f"PY39=violations {len(violations)} files={len(files)}")
        return 1
    print(f"PY39=clean files={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
