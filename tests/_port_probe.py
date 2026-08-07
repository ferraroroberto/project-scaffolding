"""Which PIDs are LISTENing on a local TCP port.

Both lifecycle harnesses need that answer before they can reclaim a port:
`tests/_streamlit_lifecycle.py` kills whatever holds the e2e Streamlit port, and
`tests/e2e/_tray_harness.py` checks the real `tray_lifecycle.ps1` reclaim
actually freed the test's own ephemeral port. Each had hand-copied the same
`netstat -ano -p TCP` parse — same field indices, same
`parts[3] == "LISTENING"` / `parts[1].endswith(f":{port}")` predicate — so a fix
to the parse (a new netstat column, an IPv6 shape) had to be found and applied
twice. This is the single copy (`project-scaffolding#208`).

Test-only plumbing, and deliberately **not** a vendor-verbatim primitive: it is
imported by this repo's own harnesses only.
"""

from __future__ import annotations

import subprocess
import sys

from src.no_window import NO_WINDOW


def listening_pids(port: int) -> list[str]:
    """PIDs LISTENing on ``port`` (Windows netstat / POSIX lsof), sorted."""
    if sys.platform == "win32":
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, check=False,
            creationflags=NO_WINDOW,
        ).stdout
        pids = set()
        for line in out.splitlines():
            parts = line.split()
            if (
                len(parts) >= 5
                and parts[3] == "LISTENING"
                and parts[1].endswith(f":{port}")
            ):
                pids.add(parts[4])
        return sorted(pids)
    out = subprocess.run(
        # no-window-exempt: POSIX-only branch (guarded by sys.platform above);
        # CREATE_NO_WINDOW does not exist off Windows.
        ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
        capture_output=True, text=True, check=False,
    ).stdout
    return [pid for pid in out.split() if pid]
