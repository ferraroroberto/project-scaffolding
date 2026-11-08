"""The one place this repo's scripts write to a path a caller names.

A script argument (`--out`, `--state`, an adopter repo, a runner's step-summary
file) cannot be resolved by the runtime-write ratchet, so each such write used to
carry its own `runtime-write-exempt` marker. Here the guarantee is enforced when
the script runs instead: every path is resolved first and refused when it lands
under one of the code folders of this checkout, so a caller cannot send runtime
output to the place the ratchet exists to keep clear.

Gitignored state inside the checkout (``data/``, ``.claude/``) stays allowed.
The check is "not under a code folder", not "outside the checkout", because the
repo's own runtime output may sit in an ignored folder of it.

This module is repo-local on purpose: it is not a ``[components]`` entry, so it
is not copied to adopters, and a vendored script cannot import it.
"""

from __future__ import annotations

import os
from pathlib import Path

#: The folders the runtime-write ratchet holds clear of runtime output (its defaults).
CODE_FOLDERS: tuple[str, ...] = ("src", "app", "scripts", "hooks", "skills")

REPO_ROOT = Path(__file__).resolve().parents[1]


class RuntimeWriteRefused(ValueError):
    """A write was aimed at a code folder of this checkout."""


def checked(path: str | os.PathLike[str]) -> Path:
    """Return *path* resolved, or raise `RuntimeWriteRefused` when it is under a code folder."""
    resolved = Path(path).expanduser().resolve()
    for folder in CODE_FOLDERS:
        if resolved.is_relative_to(REPO_ROOT / folder):
            raise RuntimeWriteRefused(f"refusing to write under the code folder {folder}/: {resolved}")
    return resolved


def make_dirs(path: str | os.PathLike[str]) -> Path:
    """Create *path* and its parents; returns the resolved path."""
    target = checked(path)
    # runtime-write-exempt: the path was resolved and refused above when it is under a code folder
    target.mkdir(parents=True, exist_ok=True)
    return target


def _open(path: str | os.PathLike[str], mode: str, **kwargs):
    # runtime-write-exempt: the path was resolved and refused above when it is under a code folder
    return open(checked(path), mode, **kwargs)  # noqa: SIM115 -- the callers below close it


def save_text(path: str | os.PathLike[str], text: str, *, encoding: str = "utf-8", newline: str | None = None) -> None:
    """Replace the file at *path* with *text*."""
    with _open(path, "w", encoding=encoding, newline=newline) as fh:
        fh.write(text)


def save_bytes(path: str | os.PathLike[str], data: bytes) -> None:
    """Replace the file at *path* with *data*."""
    with _open(path, "wb") as fh:
        fh.write(data)


def append_text(path: str | os.PathLike[str], text: str, *, encoding: str = "utf-8") -> None:
    """Append *text* to the file at *path*, creating it when absent."""
    with _open(path, "a", encoding=encoding) as fh:
        fh.write(text)


def copy_file(src: str | os.PathLike[str], dest: str | os.PathLike[str]) -> None:
    """Copy *src* to *dest* byte for byte."""
    save_bytes(dest, Path(src).read_bytes())
