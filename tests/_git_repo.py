"""Throwaway git repos for the ratchet tests: run git in one, write and track a file."""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.no_window import NO_WINDOW


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, creationflags=NO_WINDOW)


def write(root: Path, rel: str, text: str, *, track: bool = True) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    if track:
        git(root, "add", "-f", rel)
