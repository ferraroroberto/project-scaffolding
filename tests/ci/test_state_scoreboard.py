"""Tests for the fleet state scoreboard (`scripts/state_scoreboard.py` and its readers).

Each case builds throwaway git repos in a temp "fleet root" and reads them back: the numbers come
from committed state at a commit, two runs agree byte for byte, and whatever cannot be read is
`unknown` rather than zero.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import pytest

from scripts import state_scoreboard as sb
from scripts.conventions_state import js_state_names
from scripts.state_scoreboard_bugs import count_bugs, github_slug
from scripts.state_scoreboard_read import ReadError, read_machines, resolve_ref, state_names
from src.no_window import NO_WINDOW
from tests._git_repo import git, write

RULES = '["state-literal", "state-set-repeat", "state-write"]'
MACHINE = '[[state_machines]]\nname = "job"\nmodule = "src/job_state.py"\ntype = "JobState"\n'
ENUM = "import enum\n\nclass JobState(enum.Enum):\n    IDLE = 'idle'\n    RUNNING = 'running'\n"


def toml(rules: str = RULES, machines: str = MACHINE, enabled: str = "true") -> str:
    return f"[conventions_ratchet]\nenabled = {enabled}\nrules = {rules}\n{machines}"


def baseline(entries: list[dict[str, object]]) -> str:
    return json.dumps({"version": 1, "entries": entries})


# A machine-wide commit hook (an author allowlist) must not gate a throwaway fixture repo.
NO_HOOKS = Path(tempfile.gettempdir()) / "state-scoreboard-no-hooks"


def commit(root: Path, when: str, message: str = "c") -> None:
    env = {**os.environ, "GIT_COMMITTER_DATE": when, "GIT_AUTHOR_DATE": when}
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                    "-c", f"core.hooksPath={NO_HOOKS}", "commit", "-q", "-m", message],
                   cwd=root, check=True, capture_output=True, env=env, creationflags=NO_WINDOW)


def make_repo(fleet: Path, name: str, files: dict[str, str], when: str = "2026-01-10T12:00:00+00:00") -> Path:
    root = fleet / name
    root.mkdir(parents=True)
    git(root, "init", "-q")
    for rel, text in files.items():
        write(root, rel, text)
    commit(root, when)
    return root


def good_files(**extra: str) -> dict[str, str]:
    entries = [{"key": "src/a.py", "counts": {"state-literal": 4, "state-write": 1}},
               {"key": "src/b.py", "counts": {"state-set-repeat": 2}},
               {"key": "web/app.js", "counts": {"state-literal": 3}}]
    return {".fleet.toml": toml(), ".conventions-ratchet-baseline.json": baseline(entries),
            "src/job_state.py": ENUM, **extra}


def run(fleet: Path, *args: str) -> tuple[int, dict[str, Any]]:
    rows = [sb.measure(p, "HEAD") for p in sb.discover(fleet, [])]
    return (3 if any(r["status"] == "unknown" for r in rows) else 0), {r["repo"]: r for r in rows}


def test_findings_split_by_language_and_duplicates_sum_write_and_set_repeat(tmp_path: Path) -> None:
    make_repo(tmp_path, "alpha", good_files())
    _, rows = run(tmp_path)
    findings = rows["alpha"]["findings"]
    assert findings["by_rule"] == {"state-literal": {"py": 4, "js": 3}, "state-set-repeat": {"py": 2, "js": 0},
                                   "state-write": {"py": 1, "js": 0}}
    assert findings["duplicate_derivations"] == 3
    assert rows["alpha"]["status"] == "ok"


def test_two_runs_at_one_commit_are_byte_identical(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, "alpha", good_files())
    make_repo(tmp_path, "beta", {".fleet.toml": toml(rules='["no-window"]', machines="")})
    outputs = []
    for flags in ([], ["--json"]):
        pair = []
        for _ in range(2):
            assert sb.main(["--root", str(tmp_path), *flags]) == 0
            pair.append(capsys.readouterr().out)
        assert pair[0] == pair[1]
        outputs.append(pair[0])
    assert "alpha" in outputs[0] and json.loads(outputs[1])["totals"]["repos"] == 2


def test_unreadable_baseline_is_unknown_never_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    make_repo(tmp_path, "missing", {".fleet.toml": toml(), "src/job_state.py": ENUM})
    make_repo(tmp_path, "broken", {**good_files(), ".conventions-ratchet-baseline.json": "{not json"})
    make_repo(tmp_path, "badtoml", {".fleet.toml": "[[oops"})
    code, rows = run(tmp_path)
    assert code == 3
    for name in ("missing", "broken", "badtoml"):
        assert rows[name]["status"] == "unknown"
        assert rows[name]["findings"]["status"] == "unknown"
        assert "by_rule" not in rows[name]["findings"]
    assert sb.main(["--root", str(tmp_path)]) == 3
    table = capsys.readouterr().out
    assert " ?" in table.splitlines()[3]
    assert "baseline .conventions-ratchet-baseline.json is not committed" in table


def test_not_enrolled_is_not_counted_as_zero(tmp_path: Path) -> None:
    make_repo(tmp_path, "plain", {".fleet.toml": toml(rules='["no-window"]', machines="")})
    make_repo(tmp_path, "off", {".fleet.toml": toml(enabled="false", machines="")})
    _, rows = run(tmp_path)
    for name in ("plain", "off"):
        assert rows[name]["status"] == "not-enrolled"
        assert rows[name]["findings"]["status"] == "not-enrolled"
    totals = sb.totals(list(rows.values()))
    assert totals["findings_repos"] == 0 and totals["by_status"] == {"not-enrolled": 2}


def test_a_date_before_history_is_absent_and_a_date_picks_the_older_numbers(tmp_path: Path) -> None:
    root = make_repo(tmp_path, "alpha", good_files(), when="2026-03-01T12:00:00+00:00")
    write(root, ".conventions-ratchet-baseline.json", baseline([]))
    commit(root, "2026-06-01T12:00:00+00:00")
    assert sb.measure(root, "2026-02-01")["status"] == "absent"
    old, new = sb.measure(root, "2026-04-01"), sb.measure(root, "2026-07-01")
    assert old["findings"]["by_rule"]["state-literal"] == {"py": 4, "js": 3}
    assert new["findings"]["by_rule"]["state-literal"] == {"py": 0, "js": 0}
    assert sb.measure(root, old["sha"])["sha"] == old["sha"]
    assert resolve_ref(root, "2026-02-01") is None
    with pytest.raises(ReadError):
        resolve_ref(root, "deadbeef0000")


def test_proof_tests_are_counted_per_machine_and_a_machine_without_one_is_flagged(tmp_path: Path) -> None:
    tests = (
        "def helper():\n    pass\n\n"
        "# state-machine-proof: job\ndef test_comment_above():\n    pass\n\n"
        "def test_docstring():\n    '''state-machine-proof: job'''\n\n"
        "def test_other_machine():\n    # state-machine-proof: elsewhere\n    pass\n\n"
        "def test_unmarked():\n    pass\n"
    )
    make_repo(tmp_path, "proven", good_files(**{"tests/test_job.py": tests}))
    make_repo(tmp_path, "bare", good_files())
    make_repo(tmp_path, "prod_marker", good_files(**{"src/notes.py": "# state-machine-proof: job\n"}))
    _, rows = run(tmp_path)
    assert rows["proven"]["machines"]["items"][0]["proof_tests"] == 2
    assert rows["bare"]["machines"]["items"][0]["proof_tests"] == 0
    assert rows["prod_marker"]["machines"]["items"][0]["proof_tests"] == 0
    totals = sb.totals(list(rows.values()))
    assert totals["machines"] == 3 and totals["machines_without_proof"] == 2


def test_an_unparseable_test_module_makes_the_proof_unknown(tmp_path: Path) -> None:
    make_repo(tmp_path, "alpha", good_files(**{"tests/test_job.py": "# state-machine-proof: job\ndef test_x(:\n"}))
    _, rows = run(tmp_path)
    item = rows["alpha"]["machines"]["items"][0]
    assert item["proof_tests"] is None and rows["alpha"]["status"] == "unknown"
    assert sb.totals(list(rows.values()))["machines_proof_unknown"] == 1


JS_PROOFS = (
    "import { test, it, describe } from 'node:test';\n\n"
    "// the closed set is exhaustive\n// state-machine-proof: job\ntest('refuses an illegal move', () => {\n  run();\n});\n\n"
    "it.skip('marker in the body', () => {\n  /* state-machine-proof: job */\n  run();\n});\n\n"
    "// state-machine-proof: job\ndescribe('a suite is not a test', () => {});\n\n"
    "test('other machine', () => {\n  // state-machine-proof: elsewhere\n});\n\n"
    "test('unmarked', () => {\n  const s = 'state-machine-proof: job';\n});\n\n"
    "// state-machine-proof: job\n\nit('a blank line breaks the block', () => {});\n"
)


def test_proof_tests_in_javascript_are_counted_by_test_and_it_calls_only(tmp_path: Path) -> None:
    make_repo(tmp_path, "jsproof", good_files(**{"test/job.test.js": JS_PROOFS}))
    make_repo(tmp_path, "tsspec", good_files(**{"web/job.spec.ts": JS_PROOFS.replace("node:test", "vitest")}))
    make_repo(tmp_path, "prod", good_files(**{"web/job.js": JS_PROOFS}))
    make_repo(tmp_path, "pyonly", good_files(**{"tests/test_job.py": "# state-machine-proof: job\ndef test_a():\n    pass\n"}))
    _, rows = run(tmp_path)
    assert rows["jsproof"]["machines"]["items"][0]["proof_tests"] == 2
    assert rows["tsspec"]["machines"]["items"][0]["proof_tests"] == 2
    assert rows["prod"]["machines"]["items"][0]["proof_tests"] == 0
    assert rows["pyonly"]["machines"]["items"][0]["proof_tests"] == 1


def test_javascript_and_python_proofs_add_up(tmp_path: Path) -> None:
    files = {"test/job.test.mjs": JS_PROOFS, "tests/test_job.py": "# state-machine-proof: job\ndef test_a():\n    pass\n"}
    make_repo(tmp_path, "both", good_files(**files))
    _, rows = run(tmp_path)
    assert rows["both"]["machines"]["items"][0]["proof_tests"] == 3


def test_an_unreadable_javascript_test_makes_the_proof_unknown(tmp_path: Path) -> None:
    make_repo(tmp_path, "alpha", good_files(**{"test/job.test.js": "// state-machine-proof: job\ntest('x', () => {\n"}))
    _, rows = run(tmp_path)
    assert rows["alpha"]["machines"]["items"][0]["proof_tests"] is None and rows["alpha"]["status"] == "unknown"


def test_a_malformed_machine_table_is_unknown_machines_but_findings_still_read(tmp_path: Path) -> None:
    make_repo(tmp_path, "alpha", {**good_files(), ".fleet.toml": toml(machines='[[state_machines]]\nname = "job"\n')})
    _, rows = run(tmp_path)
    assert rows["alpha"]["machines"]["status"] == "unknown"
    assert rows["alpha"]["findings"]["status"] == "ok"
    assert rows["alpha"]["status"] == "unknown"


def _git_tree(root: Path) -> dict[str, tuple[int, int]]:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns) for p in root.rglob("*") if p.is_file()}


def test_the_scoreboard_never_writes_to_a_repo(tmp_path: Path) -> None:
    root = make_repo(tmp_path, "alpha", good_files())
    before = _git_tree(root)
    assert sb.main(["--root", str(tmp_path)]) == 0
    assert _git_tree(root) == before


def test_state_names_reads_enum_members_and_literal_aliases() -> None:
    assert state_names(ENUM, "JobState") == ["idle", "running"]
    assert state_names("from typing import Literal\nJobState = Literal['Up', 'down']\n", "JobState") == ["down", "up"]
    assert state_names("class Other:\n    pass\n", "JobState") == []
    assert state_names("def (:", "JobState") == []


def test_js_state_names_reads_the_declared_type_in_every_js_shape() -> None:
    assert js_state_names("export enum JobState { Idle = 'idle', Running = 'running' }", "JobState") == ["idle", "running"]
    assert js_state_names("export type JobState = 'Up' | 'down';", "JobState") == ["down", "up"]
    multiline = "type JobState =\n  | 'idle'\n  | 'running';\ntype Other = 'x' | 'y';"
    assert js_state_names(multiline, "JobState") == ["idle", "running"]
    assert js_state_names("export const JobState = Object.freeze({ IDLE: 'idle', RUNNING: 'running' });", "JobState") == [
        "idle", "running"]
    assert js_state_names("const JobState = ['idle', 'running'];", "JobState") == ["idle", "running"]
    assert js_state_names("const JobState = new Set(['idle', 'running']);", "JobState") == ["idle", "running"]
    assert js_state_names("class JobState { static IDLE = 'idle'; static RUNNING = 'running'; go() { return 'x'; } }",
                          "JobState") == ["idle", "running"]
    assert js_state_names("const Other = { A: 'a' };", "JobState") == []
    assert js_state_names("const JobState = {{{", "JobState") == []


def test_a_js_declared_owner_shows_its_state_count(tmp_path: Path) -> None:
    machine = '[[state_machines]]\nname = "session"\nmodule = "src/session_end.ts"\ntype = "SessionEnd"\n'
    owner = "export type SessionEnd = 'idle' | 'ending' | 'ended';\n"
    make_repo(tmp_path, "jsrepo", good_files(**{".fleet.toml": toml(machines=machine), "src/session_end.ts": owner}))
    make_repo(tmp_path, "pyrepo", good_files())
    _, rows = run(tmp_path)
    assert rows["jsrepo"]["machines"]["items"][0]["states"] == 3
    assert rows["pyrepo"]["machines"]["items"][0]["states"] == 2


def test_bug_signal_counts_only_issues_naming_the_machine(tmp_path: Path) -> None:
    root = make_repo(tmp_path, "alpha", good_files())
    git(root, "remote", "add", "origin", "https://github.com/someone/alpha.git")
    assert github_slug(root) == "someone/alpha"
    machine = read_machines({"state_machines": [{"name": "job", "module": "m.py", "type": "JobState"}]})[0]
    issues = [
        {"title": "JobState wrong after crash", "body": "", "closedAt": "2026-01-01T00:00:00Z"},
        {"title": "x", "body": "idle then running", "closedAt": "2026-09-01T00:00:00Z"},
        {"title": "only idle here", "body": "", "closedAt": "2026-09-01T00:00:00Z"},
        {"title": "rejobbed", "body": "", "closedAt": "2026-09-01T00:00:00Z"},
    ]
    assert count_bugs(issues, machine, ["idle", "running"], "2026-06-01T00:00:00Z") == {"before": 1, "after": 1}

    def fake_gh(args: object) -> str:
        return json.dumps(issues)

    row = sb.measure(root, "HEAD", "2026-06-01T00:00:00Z", fake_gh)
    assert row["machines"]["items"][0]["bugs"] == {"before": 1, "after": 1}

    def failing_gh(args: object) -> str:
        raise ReadError("gh exited 1")

    bad = sb.measure(root, "HEAD", "2026-06-01T00:00:00Z", failing_gh)["machines"]["items"][0]["bugs"]
    assert bad == {"status": "unknown", "reason": "gh exited 1"}


def test_arguments_are_validated(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert sb.main(["--root", str(tmp_path / "missing")]) == 2
    assert sb.main(["--root", str(tmp_path), "--bug-split", "not-a-date"]) == 2
    assert "state_scoreboard:" in capsys.readouterr().err
