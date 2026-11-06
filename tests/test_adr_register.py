"""The ADR register stays in sync with the `adr`-labelled issues.

`docs/architecture-decisions.md` lists every standing decision once, each entry
linking the `adr` issue that holds its reasoning. Prose kept it in sync only as
long as every author remembered, so this test checks it against a committed
snapshot of the issues (`docs/architecture-decisions.issues.json`), offline:

- every `adr` issue that is not superseded appears exactly once in the register;
- every register entry links exactly one issue, and that issue is in the snapshot;
- no superseded issue (closed as not planned) stays listed.

The snapshot is refreshed with the command in the register's "How it works"
section whenever an `adr` issue is filed, closed or superseded. This module is
scaffold-only: it is not in the `[components]` catalog, so a re-vendor never
carries it into an adopter.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTER = REPO_ROOT / "docs" / "architecture-decisions.md"
SNAPSHOT = REPO_ROOT / "docs" / "architecture-decisions.issues.json"

ISSUE_URL = "https://github.com/ferraroroberto/project-scaffolding/issues/"
ISSUE_LINE = re.compile(r"^Issue: " + re.escape(ISSUE_URL) + r"(\d+)\s*$")
IN_FORCE_HEADING = "## Decisions in force"


def parse_register(text: str) -> dict[str, list[int]]:
    """Map each `###` entry under "Decisions in force" to the issue numbers it links."""
    if IN_FORCE_HEADING not in text:
        raise AssertionError(f"register has no `{IN_FORCE_HEADING}` heading")
    body = text.split(IN_FORCE_HEADING, 1)[1]
    entries: dict[str, list[int]] = {}
    current: str | None = None
    for line in body.splitlines():
        if line.startswith("## "):
            break
        if line.startswith("### "):
            current = line[4:].strip()
            entries[current] = []
            continue
        match = ISSUE_LINE.match(line)
        if match:
            if current is None:
                raise AssertionError(f"issue link outside any entry: {line}")
            entries[current].append(int(match.group(1)))
    return entries


def is_superseded(issue: dict[str, Any]) -> bool:
    """A superseded decision is an `adr` issue closed as not planned."""
    return issue.get("state") == "CLOSED" and issue.get("stateReason") == "NOT_PLANNED"


def register_drift(entries: dict[str, list[int]], issues: list[dict[str, Any]]) -> list[str]:
    """Every way the register disagrees with the issue snapshot; empty means in sync."""
    problems: list[str] = []
    known = {int(i["number"]): i for i in issues}
    for title, numbers in entries.items():
        if len(numbers) != 1:
            problems.append(f"entry {title!r} links {len(numbers)} issues, expected exactly 1")
    listed = Counter(n for numbers in entries.values() for n in numbers)
    for number, count in sorted(listed.items()):
        if number not in known:
            problems.append(f"#{number} is listed but is not an `adr` issue in the snapshot")
        elif is_superseded(known[number]):
            problems.append(f"#{number} is superseded (closed as not planned) but still listed")
        if count > 1:
            problems.append(f"#{number} is listed {count} times, expected once")
    for number, issue in sorted(known.items()):
        if not is_superseded(issue) and number not in listed:
            problems.append(f"#{number} ({issue.get('title', '')}) is an `adr` issue missing from the register")
    return problems


def _load_snapshot() -> list[dict[str, Any]]:
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert isinstance(data, list), "snapshot must be the JSON list `gh issue list --json` prints"
    return data


def test_snapshot_is_well_formed() -> None:
    issues = _load_snapshot()
    numbers = [i["number"] for i in issues]
    assert numbers, "snapshot lists no `adr` issues"
    assert len(numbers) == len(set(numbers)), "snapshot repeats an issue number"
    for issue in issues:
        assert {"number", "title", "state", "stateReason"} <= issue.keys(), issue


def test_register_matches_adr_issues() -> None:
    entries = parse_register(REGISTER.read_text(encoding="utf-8"))
    problems = register_drift(entries, _load_snapshot())
    assert not problems, "ADR register out of sync:\n- " + "\n- ".join(problems)


def _issue(number: int, state: str = "OPEN", reason: str = "") -> dict[str, Any]:
    return {"number": number, "title": f"ADR {number}", "state": state, "stateReason": reason}


def _register(*sections: tuple[str, list[int]]) -> str:
    lines = ["# Architecture decisions", "", IN_FORCE_HEADING, ""]
    for title, numbers in sections:
        lines += [f"### {title}", "", "Decision text.", ""]
        lines += [f"Issue: {ISSUE_URL}{n}" for n in numbers]
        lines.append("")
    lines += ["## Afterword", f"Issue: {ISSUE_URL}999"]
    return "\n".join(lines)


def test_in_sync_register_has_no_drift() -> None:
    text = _register(("A", [1]), ("B", [2]))
    issues = [_issue(1, "CLOSED", "COMPLETED"), _issue(2), _issue(3, "CLOSED", "NOT_PLANNED")]
    assert register_drift(parse_register(text), issues) == []


@pytest.mark.parametrize(
    ("sections", "issues", "fragment"),
    [
        ((("A", [1]),), [_issue(1), _issue(2)], "#2 (ADR 2) is an `adr` issue missing"),
        ((("A", [1]), ("B", [4])), [_issue(1)], "#4 is listed but is not an `adr` issue"),
        ((("A", [1]), ("B", [1])), [_issue(1)], "#1 is listed 2 times"),
        ((("A", [1]),), [_issue(1, "CLOSED", "NOT_PLANNED")], "#1 is superseded"),
        ((("A", []),), [], "entry 'A' links 0 issues"),
        ((("A", [1, 2]),), [_issue(1), _issue(2)], "entry 'A' links 2 issues"),
    ],
)
def test_drift_is_reported(
    sections: tuple[tuple[str, list[int]], ...], issues: list[dict[str, Any]], fragment: str
) -> None:
    problems = register_drift(parse_register(_register(*sections)), issues)
    assert any(fragment in p for p in problems), problems


def test_missing_in_force_heading_fails() -> None:
    with pytest.raises(AssertionError):
        parse_register("# Architecture decisions\n\nnothing here\n")
