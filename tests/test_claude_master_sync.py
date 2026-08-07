"""`docs/agents/CLAUDE.master.md` must stay byte-identical to `CLAUDE.md`'s body.

`docs/agents/README.md` ("Updating the master") states the rule in prose: this
repo's own `./CLAUDE.md` *is* the canonical template, copied verbatim, with only
the `## This repository` footer differing per repo. Prose alone did not hold —
the same drift had to be reconciled twice (`project-scaffolding#59`, then
`#211`), and it is silent *and* propagating: `docs/agents/ADAPT_PROMPT.md`
bootstraps a new repo by copying the master verbatim, so whatever the master is
missing, every repo stood up from it is missing too.

So the rule is enforced in the tool rather than in agent prose — the same
conclusion `#202` reached for the worktree-isolation mandate. This test runs in
the non-e2e phase of `scripts/verify-before-ship.ps1`, so editing one file
without mirroring the other fails the gate before it can ship.
"""

from __future__ import annotations

import difflib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = REPO_ROOT / "CLAUDE.md"
MASTER_MD = REPO_ROOT / "docs" / "agents" / "CLAUDE.master.md"

# The one intentional divergence: everything from this marker on is the
# per-repo footer. Split on it rather than on a bare `---` so a horizontal
# rule added inside the body can never be mistaken for the footer boundary.
FOOTER_MARKER = "\n---\n\n## This repository\n"


def _split_body(path: Path) -> str:
    """Return *path*'s shared body — everything above the per-repo footer."""
    text = path.read_text(encoding="utf-8")
    count = text.count(FOOTER_MARKER)
    assert count == 1, (
        f"{path.relative_to(REPO_ROOT)} has {count} `## This repository` footer "
        f"markers, expected exactly 1. The footer is the one section allowed to "
        f"differ between CLAUDE.md and the master template; it must stay a single, "
        f"unambiguous `---` + `## This repository` block at the end of the file."
    )
    return text.split(FOOTER_MARKER)[0]


def test_master_template_body_matches_claude_md() -> None:
    """The master template's body is CLAUDE.md's body, verbatim."""
    claude_body = _split_body(CLAUDE_MD)
    master_body = _split_body(MASTER_MD)

    if claude_body != master_body:
        diff = "\n".join(
            difflib.unified_diff(
                master_body.splitlines(),
                claude_body.splitlines(),
                fromfile="docs/agents/CLAUDE.master.md (body)",
                tofile="CLAUDE.md (body)",
                lineterm="",
            )
        )
        raise AssertionError(
            "docs/agents/CLAUDE.master.md has drifted from CLAUDE.md.\n"
            "Edit both in the same commit — the master is CLAUDE.md copied "
            "verbatim, only the `## This repository` footer differs "
            "(docs/agents/README.md, 'Updating the master').\n\n" + diff
        )


def test_footers_are_allowed_to_differ() -> None:
    """Guard the guard: the footer really is excluded from the comparison.

    If the marker ever stopped matching, `_split_body` would return the whole
    file for both and the equality test above would start failing for a reason
    that has nothing to do with drift. This pins the split's meaning: the two
    files' footers are genuinely different text, and the body test passes anyway.
    """
    claude_footer = CLAUDE_MD.read_text(encoding="utf-8").split(FOOTER_MARKER)[1]
    master_footer = MASTER_MD.read_text(encoding="utf-8").split(FOOTER_MARKER)[1]

    assert claude_footer != master_footer
    assert "Replaced per repo" in master_footer, (
        "The master's footer must stay the copy-me placeholder — a real repo's "
        "footer was pasted into the template."
    )
