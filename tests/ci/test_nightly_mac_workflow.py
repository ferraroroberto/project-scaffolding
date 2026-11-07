"""`.github/workflows/nightly-mac.yml` keeps the self-hosted runner safe.

The workflow runs on a self-hosted Mac registered on a public repo. Anything
that lets an outsider's code start it (a pull-request trigger, a fork event, a
write token, an uploaded artifact holding a rendered page) turns the Mac into
someone else's machine. Each rule in docs/mac-runner.md -> "Safety" is
asserted here, so a later edit cannot quietly loosen one.

Line-based on the executable body (comments stripped), like
`test_ci_template.py`, so no YAML dependency is needed. The job guard is also
evaluated as a dry run against the event payloads that must and must not
start the job.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly-mac.yml"


def _body() -> str:
    lines = []
    for line in WORKFLOW.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(re.sub(r"\s+#\s.*$", "", line))
    return "\n".join(lines)


def _on_block() -> str:
    match = re.search(r"^on:\n((?:[ \t]+.*\n|\n)+)", _body() + "\n", re.M)
    assert match, "no top-level `on:` block"
    return match.group(1)


def _job_guard() -> str:
    match = re.search(r"^    if: >-\n((?:      .*\n)+)", _body() + "\n", re.M)
    assert match, "the platform job has no folded `if: >-` guard"
    return " ".join(line.strip() for line in match.group(1).splitlines())


_ATOM = re.compile(r"^\s*([\w.]+)\s*(==|!=)\s*('[^']*'|true|false)\s*$")


def _evaluate(guard: str, repository: str, event_name: str, fork: bool | None) -> bool:
    """A dry run of the job's `if:` for one event: `&&` of `||`-groups of `==`/`!=` atoms."""
    context: dict[str, object] = {
        "github.repository": repository,
        "github.event_name": event_name,
        "github.event.pull_request.head.repo.fork": fork,
    }

    def atom(text: str) -> bool:
        match = _ATOM.match(text)
        assert match, f"guard atom the dry run cannot read: {text!r}"
        name, op, raw = match.groups()
        assert name in context, f"guard reads {name}, which the dry run does not model"
        literal: object = {"true": True, "false": False}.get(raw, raw.strip("'"))
        return (context[name] == literal) is (op == "==")

    return all(
        any(atom(part) for part in clause.strip().strip("()").split("||"))
        for clause in guard.split("&&")
    )


def test_triggers_are_schedule_and_dispatch_only() -> None:
    on = _on_block()
    triggers = set(re.findall(r"^  (\w+):", on, re.M))
    assert triggers == {"schedule", "workflow_dispatch"}
    body = _body()
    for forbidden in ("pull_request", "pull_request_target", "workflow_run", "issue_comment"):
        assert forbidden not in body.replace("github.event.pull_request", ""), forbidden


def test_schedule_is_in_the_quiet_hours() -> None:
    crons = re.findall(r'cron:\s*"([^"]+)"', _on_block())
    assert crons == ["0 2 * * *"], "02:00 UTC is 03:00 CET / 04:00 CEST, inside 02:00-05:00 local"


@pytest.mark.parametrize(
    ("repository", "event", "fork", "runs"),
    [
        ("ferraroroberto/project-scaffolding", "schedule", None, True),
        ("ferraroroberto/project-scaffolding", "workflow_dispatch", None, True),
        ("ferraroroberto/project-scaffolding", "pull_request", True, False),
        ("ferraroroberto/project-scaffolding", "pull_request", False, False),
        ("ferraroroberto/project-scaffolding", "pull_request_target", True, False),
        ("ferraroroberto/project-scaffolding", "push", None, False),
        ("someone/project-scaffolding", "schedule", None, False),
        ("someone/project-scaffolding", "workflow_dispatch", None, False),
    ],
)
def test_job_guard_dry_run(repository: str, event: str, fork: bool | None, runs: bool) -> None:
    assert _evaluate(_job_guard(), repository, event, fork) is runs


def test_runs_only_on_the_labelled_mac() -> None:
    assert re.search(r"^    runs-on: \[self-hosted, macos, arm64, iphone-sim\]$", _body(), re.M)


def test_least_privilege_and_no_secrets() -> None:
    body = _body()
    assert re.search(r"^permissions:\n  contents: read\n(?!  )", body + "\n", re.M)
    assert "secrets." not in body
    assert body.count("persist-credentials: false") == body.count("actions/checkout@")


def test_no_artifact_upload() -> None:
    assert "upload-artifact" not in _body(), "results stay on the runner host; the repo is public"


def test_one_run_at_a_time_and_a_wedge_is_capped() -> None:
    body = _body()
    assert "max-parallel: 1" in body
    assert re.search(r"concurrency:\n  group: nightly-mac\n  cancel-in-progress: false", body)
    assert re.search(r"timeout-minutes: \d+", body)


def test_action_majors_are_node_24() -> None:
    assert set(re.findall(r"uses:\s*(\S+)", _body())) == {"actions/checkout@v6", "actions/setup-python@v6"}


def test_home_automation_is_the_first_adopter() -> None:
    assert re.search(r"^          - repo: home-automation$", _body(), re.M)
