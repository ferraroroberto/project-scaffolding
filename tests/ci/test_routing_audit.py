"""`scripts/routing_audit.py`: the nightly audit of what per-change routing skipped.

Builds a throwaway adopter repo (a `.fleet.toml` `[e2e]` table plus commits) and
drives `run_audit` over it. The point of the suite is the verdict logic: a miss
needs a failing node on a skip- or static-routed change, and anything the audit
cannot measure is `unknown` (exit 3), never clean.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import routing_audit as audit  # noqa: E402 -- needs the sys.path line above

FLEET = """
[e2e]
static_pytest_target = "tests/e2e/test_smoke.py"
full_pytest_target   = "tests/e2e"

[[e2e.rule]]
tier   = "none"
prefix = "docs/"

[[e2e.rule]]
tier   = "static"
prefix = "static/img/"

[[e2e.rule]]
tier   = "full"
prefix = "app/"
"""


# A machine-wide commit hook (an author allowlist) must not gate a throwaway fixture repo.
_NO_HOOKS = Path(tempfile.gettempdir()) / "routing-audit-no-hooks"


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
         "-c", "commit.gpgsign=false", "-c", f"core.hooksPath={_NO_HOOKS}", *args],
        capture_output=True, text=True, check=True, timeout=60,
        creationflags=audit.NO_WINDOW,
    )
    return out.stdout.strip()


def _commit(repo: Path, rel: str, text: str = "x") -> str:
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + str(len(list(repo.rglob("*")))), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"change {rel}")
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "adopter"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    (root / ".fleet.toml").write_text(FLEET, encoding="utf-8")
    (root / "tests" / "e2e").mkdir(parents=True)
    (root / "tests" / "e2e" / "test_smoke.py").write_text("", encoding="utf-8")
    (root / "tests" / "e2e" / "test_board.py").write_text("", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _junit(path: Path, failing: list[tuple[str, str]]) -> Path:
    cases = "".join(
        f'<testcase classname="{c}" name="{n}"><failure message="boom"/></testcase>' for c, n in failing
    )
    path.write_text(f'<testsuites><testsuite>{cases}<testcase classname="a.b" name="ok"/></testsuite></testsuites>',
                    encoding="utf-8")
    return path


def _green_baseline(repo: Path, state: Path) -> None:
    result = audit.run_audit(repo, "success", repo / "none.xml", state)
    assert result["outcome"] == "clean"


def test_green_night_is_clean_and_advances_the_baseline(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state" / "audit-state.json"
    result = audit.run_audit(repo, "success", repo / "missing.xml", state)
    assert (result["outcome"], result["nights"], result["misses"]) == ("clean", 1, 0)
    assert json.loads(state.read_text(encoding="utf-8"))["last_green_sha"] == _git(repo, "rev-parse", "HEAD")


def test_failure_on_a_skip_routed_commit_is_a_miss(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    _green_baseline(repo, state)
    _commit(repo, "docs/readme.md")
    junit = _junit(tmp_path / "j.xml", [("tests.e2e.test_board", "test_lane")])
    result = audit.run_audit(repo, "failure", junit, state)
    assert result["outcome"] == "miss"
    assert result["miss_nodes"] == ["tests/e2e/test_board.py::test_lane"]
    assert result["tiers"]["skip"] == 1


def test_static_routed_failure_outside_the_static_target_is_a_miss(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    _green_baseline(repo, state)
    _commit(repo, "static/img/logo.svg")
    junit = _junit(tmp_path / "j.xml", [("tests.e2e.test_board", "test_lane")])
    assert audit.run_audit(repo, "failure", junit, state)["outcome"] == "miss"


def test_static_routed_failure_inside_the_static_target_is_not_a_miss(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    _green_baseline(repo, state)
    _commit(repo, "static/img/logo.svg")
    junit = _junit(tmp_path / "j.xml", [("tests.e2e.test_smoke", "test_boot")])
    result = audit.run_audit(repo, "failure", junit, state)
    assert (result["outcome"], result["misses"]) == ("clean", 0)


def test_failure_when_every_commit_routed_full_is_not_a_miss(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    _green_baseline(repo, state)
    _commit(repo, "app/view.py")
    junit = _junit(tmp_path / "j.xml", [("tests.e2e.test_board", "test_lane")])
    result = audit.run_audit(repo, "failure", junit, state)
    assert (result["outcome"], result["misses"]) == ("clean", 0)


def test_a_red_night_does_not_advance_the_baseline(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    _green_baseline(repo, state)
    before = state.read_text(encoding="utf-8")
    _commit(repo, "docs/readme.md")
    junit = _junit(tmp_path / "j.xml", [("tests.e2e.test_board", "test_lane")])
    audit.run_audit(repo, "failure", junit, state)
    assert state.read_text(encoding="utf-8") == before


def test_unresolved_module_under_a_static_change_is_unknown(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    _green_baseline(repo, state)
    _commit(repo, "static/img/logo.svg")
    junit = _junit(tmp_path / "j.xml", [("ghost.module", "test_x")])
    assert audit.run_audit(repo, "failure", junit, state)["outcome"] == "unknown"


@pytest.mark.parametrize("outcome", ["skipped", "cancelled", ""])
def test_unmeasured_e2e_leg_is_unknown(repo: Path, tmp_path: Path, outcome: str) -> None:
    result = audit.run_audit(repo, outcome, tmp_path / "j.xml", tmp_path / "s.json")
    assert (result["outcome"], result["nights"]) == ("unknown", 0)


def test_no_baseline_is_unknown(repo: Path, tmp_path: Path) -> None:
    junit = _junit(tmp_path / "j.xml", [("tests.e2e.test_board", "test_lane")])
    result = audit.run_audit(repo, "failure", junit, tmp_path / "s.json")
    assert result["outcome"] == "unknown" and "earlier green" in result["reason"]


def test_missing_or_empty_junit_is_unknown(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    _green_baseline(repo, state)
    assert audit.run_audit(repo, "failure", tmp_path / "nope.xml", state)["outcome"] == "unknown"
    empty = _junit(tmp_path / "empty.xml", [])
    assert audit.run_audit(repo, "failure", empty, state)["outcome"] == "unknown"


def test_unusable_e2e_table_is_unknown(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    _green_baseline(repo, state)
    (repo / ".fleet.toml").write_text("not = [valid", encoding="utf-8")
    junit = _junit(tmp_path / "j.xml", [("tests.e2e.test_board", "test_lane")])
    assert audit.run_audit(repo, "failure", junit, state)["outcome"] == "unknown"


def test_baseline_missing_from_history_is_unknown(repo: Path, tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"last_green_sha": "deadbeefdeadbeef"}), encoding="utf-8")
    junit = _junit(tmp_path / "j.xml", [("tests.e2e.test_board", "test_lane")])
    assert audit.run_audit(repo, "failure", junit, state)["outcome"] == "unknown"


def test_cli_exit_codes_and_summary_line(repo: Path, tmp_path: Path) -> None:
    state, out, summary = tmp_path / "s.json", tmp_path / "run" / "audit.json", tmp_path / "summary.md"
    base = ["routing_audit.py", "audit", "--repo-dir", str(repo), "--repo", "adopter",
            "--junit", str(tmp_path / "j.xml"), "--state", str(state), "--out", str(out),
            "--summary-file", str(summary)]
    assert audit.main([*base, "--e2e-outcome", "skipped"]) == 3
    assert audit.main([*base, "--e2e-outcome", "success"]) == 0
    text = summary.read_text(encoding="utf-8")
    assert "nights audited 0, misses found 0, unknown" in text
    assert "nights audited 1, misses found 0." in text
    assert json.loads(out.read_text(encoding="utf-8"))["repo"] == "adopter"


# ------------------------------------------------------------------ file half
def _miss(nodes: list[str]) -> dict[str, object]:
    return {"repo": "adopter", "outcome": "miss", "miss_nodes": nodes, "misses": len(nodes),
            "tiers": {"skip": 2, "static": 0, "surface": 0, "full": 1}, "window_commits": 3}


def test_issue_body_carries_ids_and_counts_only_and_cannot_break_out() -> None:
    nodes = ["tests/e2e/test_a.py::test_x", "evil```\n@someone ping"]
    body = audit.issue_body(_miss(nodes))
    assert "skip: 2" in body and "tests/e2e/test_a.py::test_x" in body
    assert "```\nevil" in body and "```@" not in body
    assert body.count("```") == 2, "node ids must not close the fence"
    assert audit.marker(["b", "a"]) == audit.marker(["a", "b"]) and audit.marker(nodes) in body


def test_issue_body_caps_the_node_list() -> None:
    body = audit.issue_body(_miss([f"tests/e2e/t.py::n{i}" for i in range(80)]))
    assert body.count("tests/e2e/t.py::n") == audit.MAX_NODES_IN_ISSUE and "and 30 more" in body


def test_file_dedupes_to_one_issue(monkeypatch: pytest.MonkeyPatch) -> None:
    data = _miss(["tests/e2e/test_a.py::test_x"])
    calls: list[tuple[str, ...]] = []
    existing: dict[str, str] = {"list": "[]"}

    def fake(*args: str) -> str | None:
        calls.append(args)
        if args[1] == "list":
            return existing["list"]
        if args[1] == "create":
            return "https://github.com/o/adopter/issues/9\n"
        if args[1] == "view":
            return existing.get("view", "")
        return ""

    monkeypatch.setattr(audit, "_gh", fake)
    assert audit.file_issue(data, "o/adopter")[0] == "created"

    existing["list"] = json.dumps([{"number": 9, "title": audit.ISSUE_TITLE}])
    existing["view"] = "same night " + audit.marker(data["miss_nodes"])  # type: ignore[arg-type]
    assert audit.file_issue(data, "o/adopter") == ("unchanged", "#9")

    existing["view"] = "older findings"
    assert audit.file_issue(data, "o/adopter") == ("commented", "#9")
    created = [c for c in calls if c[1] == "create"]
    assert len(created) == 1 and "--label" in created[0] and "bug" in created[0]


def test_file_reports_unknown_when_gh_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit, "_gh", lambda *a: None)
    assert audit.file_issue(_miss(["n"]), "o/adopter")[0] == "unknown"


def test_file_cli_files_nothing_for_clean_or_unknown_and_rejects_bad_shapes(tmp_path: Path) -> None:
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps({"repo": "adopter", "outcome": "unknown", "miss_nodes": [], "tiers": {}}),
                     encoding="utf-8")
    assert audit.main(["x", "file", "--audit", str(clean)]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"repo": "../evil", "outcome": "miss", "miss_nodes": [], "tiers": {}}), encoding="utf-8")
    assert audit.main(["x", "file", "--audit", str(bad)]) == 3
    assert audit.main(["x", "file", "--audit", str(tmp_path / "absent.json")]) == 3
