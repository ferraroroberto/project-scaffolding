"""`st.set_page_config(...)` is the first Streamlit call in the entry point (#256).

`docs/streamlit-conventions.md` requires it; prose alone could not hold it (#254
had to reword the rule as unenforced guidance), so it is checked here, the same
way `tests/test_no_window_convention.py` enforces the `CREATE_NO_WINDOW` rule.
Its sibling rule, the UI-import boundary, is enforced by ruff `TID251`
(`pyproject.toml`), not by this file.

The check parses `app/app.py` with `ast` and walks its module-level statements
in source order. Function and class bodies are skipped: they run later, when
called, so a Streamlit call inside `_inject_css` is not an import-time call.
Calls hidden inside imported view modules are out of scope. Stdlib only.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT = REPO_ROOT / "app" / "app.py"

RULE = (
    "st.set_page_config(...) must be the first Streamlit call in the app entry "
    "point; see docs/streamlit-conventions.md"
)

_DEFERRED = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)


def _streamlit_aliases(tree: ast.Module) -> set[str]:
    """Names bound by module-level `import streamlit [as X]`."""
    aliases: set[str] = set()
    for stmt in tree.body:
        if isinstance(stmt, ast.Import):
            aliases.update(
                alias.asname or alias.name
                for alias in stmt.names
                if alias.name == "streamlit"
            )
    return aliases


def _root_name(node: ast.expr) -> str | None:
    """`st` for `st.sidebar.button`, None when not rooted at a plain name."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _calls_outside_deferred(node: ast.AST) -> list[ast.Call]:
    """Every call under *node*, not descending into function/class/lambda bodies."""
    found: list[ast.Call] = []
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, _DEFERRED):
            continue
        if isinstance(current, ast.Call):
            found.append(current)
        stack.extend(ast.iter_child_nodes(current))
    return found


def first_streamlit_call(source: str) -> str | None:
    """Dotted name of the first module-level Streamlit call, e.g. `st.set_page_config`."""
    tree = ast.parse(source)
    aliases = _streamlit_aliases(tree)
    for stmt in tree.body:
        calls = [
            call
            for call in _calls_outside_deferred(stmt)
            if _root_name(call.func) in aliases
        ]
        if calls:
            first = min(calls, key=lambda call: (call.lineno, call.col_offset))
            return ast.unparse(first.func)
    return None


def _assert_page_config_first(source: str, label: str) -> None:
    first = first_streamlit_call(source)
    assert first is not None, f"{label}: no module-level Streamlit call found. {RULE}"
    assert first.rsplit(".", 1)[-1] == "set_page_config", (
        f"{label}: first Streamlit call is `{first}(...)`, not "
        f"`set_page_config(...)`. {RULE}"
    )


def test_entry_point_calls_set_page_config_first() -> None:
    _assert_page_config_first(ENTRY_POINT.read_text(encoding="utf-8"), "app/app.py")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "import streamlit as st\nst.set_page_config()\nst.title('x')\n",
            "st.set_page_config",
            id="page-config-first",
        ),
        pytest.param(
            "import streamlit as st\nst.title('x')\nst.set_page_config()\n",
            "st.title",
            id="other-call-first",
        ),
        pytest.param(
            "import streamlit as st\n"
            "def helper():\n    st.markdown('later')\n"
            "st.set_page_config()\n",
            "st.set_page_config",
            id="function-body-skipped",
        ),
        pytest.param(
            "import streamlit\nwith streamlit.sidebar:\n    streamlit.toggle('t')\n"
            "streamlit.set_page_config()\n",
            "streamlit.toggle",
            id="unaliased-import-inside-with",
        ),
        pytest.param(
            "import streamlit as st\nlog = make_logger()\nst.set_page_config()\n",
            "st.set_page_config",
            id="non-streamlit-call-ignored",
        ),
    ],
)
def test_first_streamlit_call_detection(source: str, expected: str) -> None:
    assert first_streamlit_call(source) == expected
