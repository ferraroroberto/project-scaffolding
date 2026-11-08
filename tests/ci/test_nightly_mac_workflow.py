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
ADOPTERS = REPO_ROOT / ".github" / "nightly-adopters.txt"


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


def _jobs() -> dict[str, str]:
    """Each job's body, keyed by job id."""
    jobs_block = _body().split("\njobs:\n", 1)[1] + "\n"
    parts = re.split(r"^  ([\w-]+):\n", jobs_block, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def _job_guard(job: str) -> str:
    match = re.search(r"^    if: >-\n((?:      .*\n)+)", _jobs()[job], re.M)
    assert match, f"the {job} job has no folded `if: >-` guard"
    return " ".join(line.strip() for line in match.group(1).splitlines())


def _run_scripts() -> list[str]:
    """The text of every `run:` script, inline or block."""
    scripts: list[str] = []
    current: list[str] | None = None
    indent = 0
    for line in _body().splitlines():
        if current is not None:
            if line.strip() and len(line) - len(line.lstrip()) <= indent:
                scripts.append("\n".join(current))
                current = None
            else:
                current.append(line)
                continue
        found = re.match(r"^(\s*)(?:- )?run:\s*(.*)$", line)
        if found:
            indent = len(found.group(1))
            if found.group(2) in ("|", ">"):
                current = []
            else:
                scripts.append(found.group(2))
    if current is not None:
        scripts.append("\n".join(current))
    return scripts


_ATOM = re.compile(r"^\s*([\w.]+)\s*(==|!=)\s*('[^']*'|true|false)\s*$")


def _evaluate(guard: str, repository: str, event_name: str, fork: bool | None, count: str = "1") -> bool:
    """A dry run of a job's `if:` for one event: `&&` of `||`-groups of `==`/`!=` atoms."""
    context: dict[str, object] = {
        "github.repository": repository,
        "github.event_name": event_name,
        "github.event.pull_request.head.repo.fork": fork,
        "needs.select.outputs.count": count,
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
    assert crons == ["17 1 * * *"], "01:17 UTC is 02:17 CET / 03:17 CEST, inside 02:00-05:00 local"
    assert not crons[0].startswith("0 "), "the top of the hour is GitHub's high-load slot"


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
    assert set(_jobs()) == {"select", "platform"}
    for job in _jobs():
        assert _evaluate(_job_guard(job), repository, event, fork) is runs, job


def test_an_empty_matrix_skips_the_platform_job() -> None:
    guard = _job_guard("platform")
    assert not _evaluate(guard, "ferraroroberto/project-scaffolding", "schedule", None, count="0")
    assert re.search(r"^    needs: select$", _jobs()["platform"], re.M)


def test_runs_only_on_the_labelled_mac() -> None:
    for job, body in _jobs().items():
        assert re.search(r"^    runs-on: \[self-hosted, macos, arm64, iphone-sim\]$", body, re.M), job


def test_no_expression_text_inside_run_scripts() -> None:
    """Adopter settings come from their .fleet.toml: they reach scripts as env vars, never as script text."""
    scripts = _run_scripts()
    assert len(scripts) >= 10, "the run-script parser lost track of the steps"
    for script in scripts:
        assert "${{" not in script, script[:120]


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
    names = [ln.split("#", 1)[0].strip() for ln in ADOPTERS.read_text(encoding="utf-8").splitlines()]
    assert "home-automation" in names
    assert "include:" not in _body(), "the matrix is built from the adopters' [ci.nightly] tables, never hand-written"


def test_adopters_are_read_anonymously_in_the_select_job_only() -> None:
    jobs = _jobs()
    assert "--url-base https://github.com/ferraroroberto/" in jobs["select"]
    assert "https://" not in jobs["platform"]
    assert "matrix: ${{ fromJSON(needs.select.outputs.matrix) }}" in jobs["platform"]
    assert "ref: ${{ matrix.sha }}" in jobs["platform"], "test the exact commit the select job read"


def test_delivery_is_pull_only_no_outbound_calls() -> None:
    body = _body()
    for forbidden in ("curl ", "wget ", "scp ", "rsync ", "ssh ", "nc ", "gh ", "git push"):
        assert forbidden not in body, f"delivery is pull-only; the workflow must not call {forbidden.strip()}"


def test_routing_audit_step_stays_on_the_runner() -> None:
    body = _body()
    step = body.split("name: Routing audit", 1)[1].split("      - name:", 1)[0]
    assert "scripts/routing_audit.py audit" in step, "the runner half is the `audit` subcommand only"
    assert " file " not in step, "filing needs `gh`; it runs on the trusted host, never here"
    assert "!cancelled()" in step, "an audit must run after a red e2e leg, which is when it matters"
    assert '--junit "$RESULTS/junit.xml"' in step and '--junit "$RESULTS/junit.xml"' in _jobs()["platform"].split(
        "name: Routing audit", 1)[0], "the audit reads the e2e leg's first-attempt junit file"
    assert re.search(r"^          fetch-depth: 0$", body, re.M), "the audit walks the adopter's history"
    assert '--audit "$AUDIT"' in body, "READY carries the audit outcome for the puller"
