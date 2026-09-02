"""Every subprocess spawn suppresses the Windows console window (#209).

`CLAUDE.md` -> "Windows console-subprocess suppression (`CREATE_NO_WINDOW`)"
requires two things, and prose alone did not hold either of them: a
`/codebase-audit` pass found one production spawn with no `creationflags` at
all, three more in `tests/`, and the same
`sys.platform == "win32"` ternary independently re-derived in six files.

So the mandate is enforced in the tool rather than in agent prose -- the same
conclusion `#202` reached for the worktree-isolation mandate and `#211` for the
CLAUDE.master.md sync. This test runs in the non-e2e phase of
`scripts/verify-before-ship.ps1`, so a new call site that forgets the flag, or
a seventh copy of the ternary, fails the gate before it can ship (and before it
propagates: this scaffold is cloned, and two of its files are vendored
byte-identical into every adopter repo).

Two escape hatches, both deliberate and both self-documenting:

* An inline ``# no-window-exempt: <reason>`` comment anywhere in the call's
  source lines. Used for genuinely POSIX-only branches and for the one harness
  that must *reproduce* an unsuppressed spawn.
* ``VENDOR_VERBATIM`` -- a file copied byte-identical into adopter repos cannot
  import `src/no_window.py` (the import would not resolve there, and the
  hash-verified bytes must stay self-contained), so it derives the flag
  locally on purpose.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: Trees that ship code. `data/`, `docs/` and `.venv/` are not scanned.
SCANNED_DIRS = ("app", "src", "scripts", "tests")

#: The one module allowed to define the flag, plus the vendor-verbatim files
#: that must keep a self-contained local definition (mirrors the
#: `$VendoredModules` entries in `scripts/verify-before-ship.ps1` that spawn
#: subprocesses). Anything else importing `src.no_window` is the rule.
FLAG_HOME = "src/no_window.py"
VENDOR_VERBATIM = frozenset({
    "tests/e2e/_browser_sweep.py",
    "scripts/classify_e2e.py",
    "src/build_info.py",
})

EXEMPT_MARKER = "no-window-exempt"

_SPAWN_ATTRS = frozenset({"run", "Popen", "call", "check_output", "check_call"})
_ASYNC_SPAWN_ATTRS = frozenset({"create_subprocess_exec", "create_subprocess_shell"})


def _python_files() -> list[Path]:
    files: list[Path] = []
    for name in SCANNED_DIRS:
        files.extend(sorted((REPO_ROOT / name).rglob("*.py")))
    return files


def _rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


def _is_spawn(node: ast.Call) -> bool:
    """True for `subprocess.<spawn>(...)` / `asyncio.create_subprocess_*(...)`."""
    func = node.func
    if not isinstance(func, ast.Attribute) or not isinstance(func.value, ast.Name):
        return False
    if func.value.id == "subprocess":
        return func.attr in _SPAWN_ATTRS
    if func.value.id == "asyncio":
        return func.attr in _ASYNC_SPAWN_ATTRS
    return False


def _is_flag_literal(node: ast.AST) -> bool:
    """True for a bare `subprocess.CREATE_NO_WINDOW` reference."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "CREATE_NO_WINDOW"
        and isinstance(node.value, ast.Name)
        and node.value.id == "subprocess"
    )


def _exempt(node: ast.AST, lines: list[str]) -> bool:
    """True if the node carries the exempt marker.

    Searched across the lines the node itself spans *plus* the contiguous
    comment block immediately above it -- the natural place to write a
    multi-line reason, and where `# type: ignore`-style trailing comments
    would not fit.
    """
    start = getattr(node, "lineno", 0)
    end = getattr(node, "end_lineno", start) or start
    above = start - 1
    while above > 0 and lines[above - 1].lstrip().startswith("#"):
        above -= 1
    return any(EXEMPT_MARKER in line for line in lines[above:end])


def _scan() -> tuple[list[str], list[str], list[str]]:
    """Return (unflagged spawns, stray flag literals, exemption reasons)."""
    unflagged: list[str] = []
    rederived: list[str] = []
    exemptions: list[str] = []

    for path in _python_files():
        rel = _rel(path)
        source = path.read_text(encoding="utf-8")
        lines = source.splitlines()
        tree = ast.parse(source, filename=str(path))

        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_spawn(node):
                if any(kw.arg == "creationflags" for kw in node.keywords):
                    continue
                where = f"{rel}:{node.lineno}"
                if _exempt(node, lines):
                    exemptions.append(where)
                else:
                    unflagged.append(where)

            elif _is_flag_literal(node) and rel != FLAG_HOME:
                if rel in VENDOR_VERBATIM:
                    continue
                where = f"{rel}:{getattr(node, 'lineno', 0)}"
                if _exempt(node, lines):
                    exemptions.append(where)
                else:
                    rederived.append(where)

    return unflagged, rederived, exemptions


def test_every_subprocess_spawn_passes_creationflags() -> None:
    """No spawn of an external executable may omit `creationflags`.

    A console-less parent -- a `pythonw` tray, a scheduled task, an agent's
    captured shell -- gets Windows to allocate a fresh console per child
    otherwise, flashing a window on screen for every call.
    """
    unflagged, _, _ = _scan()
    assert not unflagged, (
        "subprocess spawn(s) missing `creationflags=NO_WINDOW`:\n  "
        + "\n  ".join(unflagged)
        + "\n\nAdd `creationflags=NO_WINDOW` (`from src.no_window import "
        "NO_WINDOW`), or, if the call is genuinely POSIX-only or must "
        "reproduce an unsuppressed spawn, annotate it with an inline "
        f"`# {EXEMPT_MARKER}: <reason>` comment."
    )


def test_the_no_window_flag_is_defined_in_exactly_one_place() -> None:
    """Only `src/no_window.py` derives the flag; everyone else imports it.

    The exceptions are the vendor-verbatim files, which are copied
    byte-identical into adopter repos and so cannot import a module of this
    repo's -- their local definition is the documented exception, not drift.
    """
    _, rederived, _ = _scan()
    assert not rederived, (
        "`subprocess.CREATE_NO_WINDOW` re-derived outside "
        f"`{FLAG_HOME}`:\n  " + "\n  ".join(rederived)
        + "\n\nImport it instead (`from src.no_window import NO_WINDOW`). Only "
        "a vendor-verbatim file may keep a local copy -- add it to "
        "VENDOR_VERBATIM here and to `$VendoredModules` in "
        "scripts/verify-before-ship.ps1 if that is what it is."
    )


def test_every_exemption_states_a_reason() -> None:
    """Guard the guard: the escape hatch must never be a bare marker.

    An exemption is only legitimate when the next reader can see *why*, so the
    marker must be followed by prose. Without this, `# no-window-exempt` becomes
    a silent opt-out and the two tests above decay into decoration.
    """
    _, _, exemptions = _scan()
    assert exemptions, (
        "expected at least one annotated exemption (the POSIX-only branches in "
        "tests/_port_probe.py and tests/_streamlit_lifecycle.py, and the "
        "deliberate unsuppressed reproduction in tests/e2e/_tray_harness.py) -- "
        "if they were all removed, delete this test rather than weakening it"
    )

    bare: list[str] = []
    for where in exemptions:
        rel, _, lineno = where.rpartition(":")
        lines = (REPO_ROOT / rel).read_text(encoding="utf-8").splitlines()
        marked = [ln for ln in lines if EXEMPT_MARKER in ln]
        if not any(ln.split(EXEMPT_MARKER, 1)[1].strip(" :#").strip() for ln in marked):
            bare.append(where)

    assert not bare, (
        f"`# {EXEMPT_MARKER}` with no reason after it:\n  " + "\n  ".join(bare)
    )
