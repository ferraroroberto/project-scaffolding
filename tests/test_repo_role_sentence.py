"""The repo's two-role description is one sentence, identical in README and CLAUDE.md.

The README opening and CLAUDE.md's `## This repository` section both state what
this repo is: a starter to clone and the fleet's canonical source of components,
ratchets and conventions. Two hand-typed copies drift; an agent loading only
CLAUDE.md would then miss the repo's primary role.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ROLE_MARKER = "canonical source of"


def _role_sentence(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    matches = [
        line.strip()
        for line in text.splitlines()
        if ROLE_MARKER in line and line.lstrip().startswith("A starter to clone")
    ]
    assert len(matches) == 1, f"{path.name} must carry exactly one role sentence, found {len(matches)}"
    return re.split(r"(?<=conventions\.) ", matches[0])[0]


def test_readme_and_claude_md_state_the_same_role_sentence() -> None:
    readme = _role_sentence(REPO_ROOT / "README.md")
    claude = _role_sentence(REPO_ROOT / "CLAUDE.md")
    assert readme == claude, "README.md and CLAUDE.md describe the repo's role differently -- keep them identical."
