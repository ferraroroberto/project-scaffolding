"""The state scoreboard's bug signal: closed bug issues that name a declared machine, before vs after a date.

Lagging and informative only, never a target: a count here moves with how bugs are written up, not
only with how the code behaves. It reads issues through `gh` (the one network input), so it is opt-in
and the committed-state numbers never depend on it. Only counts leave this module, never issue text.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from scripts.conventions_state import StateMachine
from scripts.state_scoreboard_read import ReadError, run_git
from src.no_window import NO_WINDOW

GH_TIMEOUT_S = 120
# Enough to cover a repo's whole bug history; a repo past it would be reported unknown, not truncated.
ISSUE_LIMIT = 1000
_REMOTE_RE = re.compile(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")

GhRunner = Callable[[Sequence[str]], str]


def run_gh(args: Sequence[str]) -> str:
    """`gh <args>` stdout; a missing `gh`, a timeout or a non-zero exit is a `ReadError`."""
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8", timeout=GH_TIMEOUT_S,
                              creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReadError(f"gh failed to run: {exc}") from exc
    if done.returncode != 0:
        raise ReadError(f"gh exited {done.returncode}")
    return done.stdout


def github_slug(repo: Path) -> str:
    """`owner/name` from the repo's `origin` remote; anything else is a `ReadError`."""
    done = run_git(repo, "remote", "get-url", "origin")
    match = _REMOTE_RE.search(done.stdout.decode("utf-8", "replace").strip()) if done.returncode == 0 else None
    if match is None:
        raise ReadError("no GitHub origin remote")
    return f"{match.group(1)}/{match.group(2)}"


def closed_bugs(slug: str, gh: GhRunner = run_gh) -> list[dict[str, str]]:
    """Every closed `bug`-labelled issue of `slug` as `{title, body, closedAt}`."""
    out = gh(["issue", "list", "-R", slug, "--state", "closed", "--label", "bug", "--limit", str(ISSUE_LIMIT),
              "--json", "title,body,closedAt"])
    try:
        issues = json.loads(out)
        if not isinstance(issues, list) or not all(isinstance(i, dict) for i in issues):
            raise ValueError("not a list of issues")
        if len(issues) >= ISSUE_LIMIT:
            raise ValueError(f"{ISSUE_LIMIT} or more closed bugs, a truncated read")
        return [{k: str(i.get(k) or "") for k in ("title", "body", "closedAt")} for i in issues]
    except ValueError as exc:
        raise ReadError(f"gh issue list gave unusable output: {exc}") from exc


def _word(term: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])", re.IGNORECASE)


def names_machine(text: str, machine: StateMachine, states: Sequence[str]) -> bool:
    """Whether an issue's text names the machine (its name or type) or at least two of its states."""
    if any(_word(term).search(text) for term in (machine.name, machine.type)):
        return True
    return sum(1 for state in states if _word(state).search(text)) >= 2


def count_bugs(issues: Sequence[dict[str, str]], machine: StateMachine, states: Sequence[str],
               split: str) -> dict[str, int]:
    """Bugs naming `machine`, closed before `split` (an ISO moment) and at or after it."""
    counts = {"before": 0, "after": 0}
    for issue in issues:
        if issue["closedAt"] and names_machine(f"{issue['title']}\n{issue['body']}", machine, states):
            counts["before" if issue["closedAt"] < split else "after"] += 1
    return counts
