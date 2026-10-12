"""`.github/workflows/ci.yml.template` keeps its contract (#351).

The template is the web-app CI gate every adopting repo copies, so the rules in
`docs/ci-conventions.md` that make it *correct* are asserted here instead of
left to a careful reader. A scaffold that drifted back to `windows-latest` or a
Node-20 action major would propagate that into every new adopter.

Checks are line-based on the executable body (comments stripped), the same
approach as `test_main_gate_watch_template.py`, so no YAML dependency is needed.
The structural lint (`actionlint`) is run by hand on a `.yml` copy; see
`docs/ci-conventions.md` -> "Web-app CI template".
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
TEMPLATE = WORKFLOW_DIR / "ci.yml.template"


def _text() -> str:
    assert TEMPLATE.is_file(), (
        f"{TEMPLATE.relative_to(REPO_ROOT)} is missing. The scaffold ships the "
        f"web-app CI gate as a copy-to-adapt template (#351)."
    )
    return TEMPLATE.read_text(encoding="utf-8")


def _body() -> str:
    """The template minus its comment lines and trailing comments."""
    lines = []
    for line in _text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        lines.append(re.sub(r"\s+#\s.*$", "", line))
    return "\n".join(lines)


def test_is_inert_in_the_scaffold() -> None:
    """Actions loads every `.yml`/`.yaml`; the `.template` suffix keeps it inert."""
    assert TEMPLATE.suffix == ".template"
    assert not list(WORKFLOW_DIR.glob("ci.y*ml")), (
        "a live ci workflow exists in the scaffold, whose gate is local-only"
    )


def test_runner_is_pinned_to_a_dated_image() -> None:
    body = _body()
    assert re.search(r"runs-on:\s*windows-2025\s*$", body, re.M)
    assert "windows-latest" not in body


def test_action_majors_are_node_24() -> None:
    uses = re.findall(r"uses:\s*(\S+)", _body())
    assert set(uses) == {
        "actions/checkout@v6",
        "actions/setup-python@v6",
        "actions/upload-artifact@v7",
    }, f"unexpected action set: {uses}"


def test_triggers_once_per_commit() -> None:
    body = _body()
    on_block = body.split("concurrency:")[0]
    assert re.search(r"push:\s*\n\s*branches:\s*\[main\]", on_block)
    assert re.search(r"pull_request:\s*\n\s*branches:\s*\[main\]", on_block)
    assert "branches-ignore" not in on_block


def test_a_wedge_is_capped() -> None:
    assert re.search(r"timeout-minutes:\s*\d+", _body())


def test_quiet_by_design_no_secrets_no_services() -> None:
    body = _body()
    assert "secrets." not in body, "the template must need no secret"
    assert "permissions:\n  contents: read" in body, "token must be read-only"
    assert not re.search(r"\bsecrets\b", body)


def test_artifacts_upload_only_on_failure() -> None:
    body = _body()
    step = body.split("actions/upload-artifact@v7")[0].rsplit("- name:", 1)[1]
    assert "if: failure()" in step, "a green run must upload nothing"


def test_no_native_command_failure_is_swallowed() -> None:
    """A pwsh step only fails on its LAST command's exit code: install checks each."""
    body = _body()
    install = body.split("Install Playwright browsers")[0]
    assert install.count("$LASTEXITCODE -ne 0") >= 3
