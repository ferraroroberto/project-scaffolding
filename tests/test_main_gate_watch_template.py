"""`.github/workflows/main-gate-watch.yml.template` keeps its contract (#222).

The template files a `ci-red-main` tracking issue the moment the adopting repo's
gate goes red on a push to `main` — the fix for "a red default branch is nobody's
finding" (`whatsapp-radar#258`: four days red, discounted in turn by two
unrelated PRs). It is inherited by every clone, so the properties that make it
*correct* are asserted here rather than left to a careful reader:

* it is still a **template** (one unreplaced token, no hardcoded gate name and
  no hardcoded assignee) — a scaffold that shipped a half-adapted file would
  propagate `e2e` into repos whose gate is called something else;
* it only fires on a **failed** run of the gate **on `main`** — a PR's own gate
  is already visible in its own checks;
* it is **idempotent** — repeated failures comment on the open issue instead of
  filing a duplicate every run.

The last test is the anti-false-coverage guard: a `workflow_run` watcher can
only observe a gate that runs in Actions, so installing it live in a repo with
no such gate yields a file that never fires — coverage that reads as green
because nothing ever reports. That precondition is prose in `CLAUDE.md`; here it
is enforced in the tool, the same conclusion `test_claude_master_sync.py` and
`#202` reached about load-bearing prose.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
TEMPLATE = WORKFLOW_DIR / "main-gate-watch.yml.template"
TOKEN = "__GATE_WORKFLOW_NAME__"


def _text() -> str:
    assert TEMPLATE.is_file(), (
        f"{TEMPLATE.relative_to(REPO_ROOT)} is missing. The scaffold ships the "
        f"red-main watcher as a copy-to-adapt template (#222); a clone inherits "
        f"nothing without it."
    )
    return TEMPLATE.read_text(encoding="utf-8")


def _executable_body(text: str) -> str:
    """The template minus its comment lines — what Actions actually runs."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_is_inert_until_adopted() -> None:
    """The `.template` suffix is load-bearing: Actions must not load this file."""
    assert TEMPLATE.suffix == ".template", (
        "Actions loads every `.yml`/`.yaml` under .github/workflows/. This repo's "
        "gate is local-only, so a live copy here could never fire — keep the "
        "`.template` suffix."
    )
    assert TOKEN in _text(), (
        f"{TOKEN} is gone — the template has been adapted in place. Adaptation "
        f"belongs in the adopting repo's copy, not in the scaffold's master."
    )


def test_gate_workflow_name_is_parameterised() -> None:
    """No hardcoded gate name (or maintainer) survives into a clone's copy."""
    text = _text()
    body = _executable_body(text)

    assert re.search(rf'workflows:\s*\["{re.escape(TOKEN)}"\]', body), (
        "The `workflows:` trigger must name the token, not a literal workflow — "
        "the gate is called `e2e` in some fleet repos and something else in others."
    )
    assert f"GATE_WORKFLOW: {TOKEN}" in body, (
        "The issue title/body/label description must read the gate name from the "
        "`GATE_WORKFLOW` env var so adopting is a single-token replace."
    )
    assert "e2e" not in body, (
        "A literal `e2e` survives in the executable body — the template would "
        "file 'main's e2e gate is red' in a repo whose gate is not called e2e."
    )
    assert "ferraroroberto" not in text, (
        "Hardcoded assignee. Use ${{ github.repository_owner }} — every clone "
        "inherits this file, and not every clone is owned by the same account."
    )


def test_fires_only_on_a_failed_gate_run_on_main() -> None:
    body = _executable_body(_text())

    assert "workflow_run:" in body
    assert "types: [completed]" in body
    assert "branches: [main]" in body, (
        "Without the branch filter the watcher also fires for PR runs of the "
        "gate, whose result is already visible in the PR's own checks."
    )
    assert "github.event.workflow_run.conclusion == 'failure'" in body, (
        "The job must be gated on a failed conclusion; a completed *green* run "
        "would otherwise file a red-main issue."
    )
    assert re.search(r"permissions:\s*\n\s*issues:\s*write", body), (
        "The default GITHUB_TOKEN cannot create issues without `issues: write`."
    )


def test_repeated_failures_comment_instead_of_filing_duplicates() -> None:
    """Idempotency — the property that keeps a week of red main to one issue."""
    body = _executable_body(_text())

    assert "gh label create ci-red-main" in body and "--force" in body, (
        "`gh label create --force` is what makes the label step idempotent on "
        "the second and every later failure."
    )
    assert "--label ci-red-main --state open" in body, (
        "The existing-issue lookup must be by the `ci-red-main` label and open "
        "state — that is the dedupe key."
    )
    assert "gh issue comment" in body, "No comment-on-existing branch."
    assert "gh issue create" in body, "No file-a-new-issue branch."
    assert "Still red on main at" in body, (
        "The follow-up comment must carry the new sha + run URL, otherwise a "
        "long-lived issue records only the first failure."
    )


def test_a_live_watcher_would_have_a_gate_to_watch() -> None:
    """Anti-false-coverage: never install the watcher where nothing can fire it.

    Scoped to this repo (whose gate is local-only, so the live file must not
    exist at all today). If a real Actions gate is ever added here and the
    watcher installed alongside it, this keeps the two consistent: the name in
    `workflows:` must match a workflow that actually exists.
    """
    live = WORKFLOW_DIR / "main-gate-watch.yml"
    if not live.is_file():
        return

    watched = re.search(r"workflows:\s*\[([^\]]*)\]", live.read_text(encoding="utf-8"))
    assert watched, "A live main-gate-watch.yml with no `workflows:` trigger."
    wanted = {name.strip().strip("\"'") for name in watched.group(1).split(",")}

    defined = set()
    for path in sorted(WORKFLOW_DIR.glob("*.y*ml")):
        if path == live:
            continue
        found = re.search(r"^name:\s*(.+)$", path.read_text(encoding="utf-8"), re.M)
        if found:
            defined.add(found.group(1).strip().strip("\"'"))

    missing = wanted - defined
    assert not missing, (
        f"main-gate-watch.yml watches {sorted(missing)}, but no workflow in "
        f"{WORKFLOW_DIR.relative_to(REPO_ROOT)} defines that name. A watcher over "
        f"a gate that does not run in Actions never fires — that is false "
        f"coverage, not cheap coverage (#222)."
    )
