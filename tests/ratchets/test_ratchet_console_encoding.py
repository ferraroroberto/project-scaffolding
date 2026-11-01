"""The ratchet scripts print non-ASCII reports without crashing on a cp1252 console."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW
from tests._git_repo import git, write

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
RATCHETS = sorted(p.name for p in SCRIPTS.glob("*_ratchet.py"))


def test_doc_refs_report_with_non_ascii_survives_a_cp1252_stream(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    write(tmp_path, ".fleet.toml", "[doc_refs_ratchet]\nenabled = true\n")
    write(tmp_path, "docs/keep.md", "x\n")
    write(tmp_path, "README.md", "Nothing dangling yet.\n")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONUTF8"}
    env["PYTHONIOENCODING"] = "cp1252"  # the stream a Windows console gives a captured child
    cmd = [sys.executable, str(SCRIPTS / "doc_refs_ratchet.py"), "--root", str(tmp_path)]
    init = subprocess.run([*cmd, "--init"], capture_output=True, env=env, creationflags=NO_WINDOW, check=False)
    assert init.returncode == 0, init.stderr.decode("utf-8", "replace")
    write(tmp_path, "README.md", "Maps → `docs/missing.md` for details.\n")
    proc = subprocess.run(cmd, capture_output=True, env=env, creationflags=NO_WINDOW, check=False)
    assert b"Traceback" not in proc.stderr, proc.stderr.decode("utf-8", "replace")
    assert proc.returncode == 1, proc.stderr.decode("utf-8", "replace")
    assert "→".encode() in proc.stdout


@pytest.mark.parametrize("name", RATCHETS)
def test_every_ratchet_entry_point_reconfigures_both_streams(name: str) -> None:
    text = (SCRIPTS / name).read_text(encoding="utf-8")
    block = text.split('if __name__ == "__main__":', 1)[1]
    assert "(sys.stdout, sys.stderr)" in block and '.reconfigure(encoding="utf-8")' in block, name
