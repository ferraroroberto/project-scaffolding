"""The ratchet catalog lists every rule the vendored scripts enforce, once.

`docs/ratchet-catalog.md` is derived from the scripts' own rule tables. A rule is listed once, as a
`####` heading or as the first cell of a table row. This test reads each registry from the script and
fails when the catalog is missing a rule, lists one twice, or still lists one a script dropped.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts import (
    comment_ratchet,
    conventions_ratchet,
    instruction_ratchet,
    runtime_write_ratchet,
    static_ratchet,
    structure_ratchet,
    usage_track_ratchet,
)

CATALOG = Path(__file__).resolve().parents[2] / "docs" / "ratchet-catalog.md"
TEXT = CATALOG.read_text(encoding="utf-8")

# Rules the scripts do not keep in one table: the detectors of the comment, docs, doc-references,
# dead-code and static ratchets, and the structure ratchet's bands and root-layout check.
NAMED_IN_CODE = (
    "comment-issue-reference", "docstring-issue-reference", "history-phrase",
    "readme-size", "doc-issue-reference", "dated-heading", "heading-changelog",
    "path", "module", "link", "port", "retired",
    "dead-definition",
    "duplicate-block", "F401", "F841",
    "near-limit-files", "near-limit-functions", "root-layout",
    "probe",
)


def listed(rule: str) -> int:
    """How many headings or table rows open with `rule`."""
    pattern = re.compile(rf"^(?:#{{3,4}} |\| ){re.escape(f'`{rule}`')}(?: |$)", re.MULTILINE)
    return len(pattern.findall(TEXT))


def expected_rules() -> list[str]:
    return [
        *conventions_ratchet.RULES,
        *usage_track_ratchet.RULES,
        *instruction_ratchet.RULES,
        *instruction_ratchet.SHAPE_RULES,
        *static_ratchet.DEFAULT_RULES,
        *structure_ratchet.KINDS,
        *runtime_write_ratchet.KINDS,
        *NAMED_IN_CODE,
    ]


def test_every_rule_is_listed_exactly_once() -> None:
    wrong = {rule: listed(rule) for rule in expected_rules() if listed(rule) != 1}
    assert not wrong, f"rules the catalog lists a number of times other than once: {wrong}"


def test_every_history_phrase_is_listed() -> None:
    missing = [phrase for phrase in comment_ratchet.HISTORY_PHRASES if f"`{phrase}`" not in TEXT]
    assert not missing, f"history phrases missing from the catalog: {missing}"


def test_the_catalog_lists_no_rule_a_script_dropped() -> None:
    known = set(expected_rules())
    listed_ids = set(re.findall(r"^\| `((?:R|S)-\d+|[BSIF]\d{3})` \|", TEXT, re.MULTILINE))
    assert listed_ids <= known, f"rows for rules no script defines: {sorted(listed_ids - known)}"
