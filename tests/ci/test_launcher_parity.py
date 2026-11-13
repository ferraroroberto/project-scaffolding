"""The POSIX and Windows launchers start Streamlit with the same flags.

A clone must behave the same on either OS, and a flag only one twin passes (an XSRF or CORS switch
on a tunnel-shared launcher) is a silent per-OS difference. Each pair is compared by the set of
`--server.*` / `--browser.*` flag names it hands to `streamlit run`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PAIRS = [("launch_app.sh", "launch_app.bat"), ("launch_server.sh", "launch_server.bat")]
_FLAG = re.compile(r"--(?:server|browser)\.\w+")


def _flags(name: str) -> set[str]:
    return set(_FLAG.findall((REPO_ROOT / name).read_text(encoding="utf-8")))


@pytest.mark.parametrize(("posix", "windows"), PAIRS)
def test_launcher_twins_pass_the_same_streamlit_flags(posix: str, windows: str) -> None:
    assert _flags(posix), f"{posix} passes no Streamlit flag; this guard has gone stale"
    assert _flags(posix) == _flags(windows)
