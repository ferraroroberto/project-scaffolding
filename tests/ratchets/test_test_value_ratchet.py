"""Tests for the test-value ratchet (`scripts/test_value_ratchet.py`).

Each rule is driven through the script's own `main()` against a throwaway git repo, a fake unit ledger
and fake reports:

  spawn-budget    a unit above its entry fails, a unit at or below passes, a unit with no entry fails;
  flake-ledger    a pass and a fail on one tree is an open flake; more open flakes than the baseline fail;
                  `flake_clear_runs` passes in a row close it, or one pass after a commit with a
                  `Flake-Fixed: <unit>` trailer; a fail after that fix reopens it; one open past the age cap fails;
  new-test-value  a unit missing from the merge base's baseline is new; an exempt marker (on a function,
                  or in a test file's header), or a red record on another tree, passes it; a red record on
                  this very tree does not; with neither, a missing or stale coverage map is exit 3 with its
                  own message, a unique covered line passes and no unique line fails;
  hermetic        red in the fresh clone and green in the primary fails, a baselined one passes, no recent
                  clone run is exit 3;
  --run-id        the recorded run stands in for the live reports; an unknown run id is exit 3;
  --update-baseline  shrinks entries, adds a unit only with --allow-additions.

No report of the run or no ledger is exit 3, never a pass.
"""

from __future__ import annotations

import contextlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts import test_value_ratchet as tvr
from tests._git_repo import git, write

NOW = datetime.now(UTC)
CONFIG = """[test_value_ratchet]
enabled = true
base_ref = "main"
unit_runner = ["fake_runner.py"]
flake_clear_runs = 2
"""
# Stands in for the gate's unit runner: reports covered lines for the units FLEET_GATE_ONLY names.
FAKE_RUNNER = """import json, os
lines = {"_new_unit_check": [["src/app.py", 2, "return 2"]], "_dull_unit_check": [["src/app.py", 1, "return 1"]]}
with open(os.environ["FLEET_GATE_COVERAGE_REPORT"], "a", encoding="utf-8") as fh:
    for unit in os.environ["FLEET_GATE_ONLY"].split(","):
        fh.write(json.dumps({"unit": unit, "lines": lines.get(unit, [])}) + "\\n")
"""


def stamp(days_ago: float = 0, minutes: int = 0) -> str:
    return (NOW - timedelta(days=days_ago) + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return path


def unit_row(unit: str, status: str, tree: str, utc: str, label: str = "gate", spawns: int = 0) -> dict[str, Any]:
    return {"kind": "unit", "run_id": f"{tree}-{utc}", "label": label, "wtree": tree, "unit": unit,
            "status": status, "seconds": 1.0, "spawns": spawns, "utc": utc}


def set_baseline(repo: Path, **fields: Any) -> None:
    data: dict[str, Any] = {"units": {}, "flake_count": 0, "flake_max_age_days": 14, "hermetic": []}
    data.update(fields)
    (repo / ".ratchets").mkdir(exist_ok=True)
    (repo / ".ratchets/test-value.json").write_text(json.dumps(data), encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """`main` holds a baseline with `_old_unit_check`; the checked-out `feature` branch adds units."""
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "t")
    git(root, "config", "core.hooksPath", str(tmp_path / "no-hooks"))  # the machine's commit hooks are not under test
    write(root, ".fleet.toml", CONFIG)
    set_baseline(root, units={"_old_unit_check": 5})
    git(root, "add", ".ratchets/test-value.json")
    write(root, "fake_runner.py", FAKE_RUNNER)
    write(root, "src/app.py", "def a():\n    return 1\n    return 2\n")
    write(root, "tests/t.py", "def _old_unit_check():\n    pass\n")
    git(root, "commit", "-q", "-m", "base")
    git(root, "checkout", "-q", "-b", "feature")
    write(root, "tests/t.py",
          "def _old_unit_check():\n    pass\n\n"
          "# test-value-exempt: a doc scanner, it covers no source\n"
          "def _marked_unit_check():\n    pass\n\n"
          "def _new_unit_check():\n    pass\n\n"
          "def _dull_unit_check():\n    pass\n")
    write(root, "tests/test_marked_file.py", '"""A file unit.\n\ntest-value-exempt: renders text only\n"""\nimport os\n')
    write(root, "tests/test_late_marker.py", "import os\n# test-value-exempt: below the header, so not a marker\n")
    git(root, "commit", "-q", "-m", "feature")
    return root


def run(repo: Path, *args: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = tvr.main(["--repo", str(repo), *args])
    return code, out.getvalue()


def test_spawn_budget(repo: Path, tmp_path: Path) -> None:
    units, spawns = tmp_path / "units.jsonl", tmp_path / "spawns.jsonl"
    base = ["--rules", "spawn-budget", "--units-report", str(units), "--spawns-report", str(spawns)]
    write_jsonl(units, [{"unit": "_old_unit_check", "status": "pass"}])
    write_jsonl(spawns, [{"unit": "_old_unit_check"}] * 5)
    assert run(repo, *base)[0] == 0
    write_jsonl(spawns, [{"unit": "_old_unit_check"}] * 6)
    code, out = run(repo, *base)
    assert code == 1 and "_old_unit_check: 6 spawns, above its baseline of 5" in out
    write_jsonl(units, [{"unit": "_old_unit_check"}, {"unit": "_brand_new"}])
    write_jsonl(spawns, [])
    code, out = run(repo, *base)
    assert code == 1 and "_brand_new: 0 spawns and no baseline entry" in out


def test_flake_ledger(repo: Path, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    flags = ["--rules", "flake-ledger", "--ledger", str(ledger)]
    flaky = [unit_row("u", "fail", "t1", stamp(2)), unit_row("u", "pass", "t1", stamp(2, 5))]
    write_jsonl(ledger, flaky)
    code, out = run(repo, *flags)
    assert code == 1 and "u: open flake since" in out and "1 open flakes, above the baseline of 0" in out
    write_jsonl(ledger, flaky + [unit_row("u", "fail", "t2", stamp(2, 6), label="weekly-hermetic-gate")])
    set_baseline(repo, flake_count=1)
    assert run(repo, *flags)[0] == 0, "another label's rows do not count"
    write_jsonl(ledger, flaky + [unit_row("u", "pass", "t2", stamp(1)), unit_row("u", "pass", "t3", stamp(0.5))])
    set_baseline(repo, flake_count=0)
    code, out = run(repo, *flags)
    assert code == 0 and "no open flake" in out
    write_jsonl(ledger, flaky + [unit_row("u", "pass", "t2", stamp(1)), unit_row("u", "fail", "t3", stamp(0.9)),
                                 unit_row("u", "pass", "t4", stamp(0.5))])
    assert run(repo, *flags)[0] == 1, "a fail between the passes restarts the count"
    write_jsonl(ledger, [unit_row("u", "fail", "t1", stamp(20)), unit_row("u", "pass", "t1", stamp(20, 5))])
    set_baseline(repo, flake_count=1, flake_max_age_days=14)
    code, out = run(repo, *flags)
    assert code == 1 and "past the 14-day cap" in out
    code, out = run(repo, "--rules", "flake-ledger", "--ledger", str(tmp_path / "absent.jsonl"))
    assert code == 3 and "the unit ledger is missing" in out


def test_flake_ledger_fix_route(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ledger = tmp_path / "ledger.jsonl"
    flags = ["--rules", "flake-ledger", "--ledger", str(ledger)]
    flaky = [unit_row("u", "fail", "t1", stamp(2)), unit_row("u", "pass", "t1", stamp(2, 5))]

    def fix_commit(unit: str, days_ago: float) -> None:
        monkeypatch.setenv("GIT_COMMITTER_DATE", stamp(days_ago))
        git(repo, "commit", "-q", "--allow-empty", "-m", f"fix: {unit}", "-m", f"Flake-Fixed: {unit}")

    write_jsonl(ledger, flaky + [unit_row("u", "pass", "t2", stamp(1))])
    assert run(repo, *flags)[0] == 1, "no fix marker: one pass does not close it, flake_clear_runs is 2"
    fix_commit("other_unit", 1.5)
    assert run(repo, *flags)[0] == 1, "a marker naming another unit does not close it"
    fix_commit("u", 1.5)
    code, out = run(repo, *flags)
    assert code == 0 and "no open flake" in out, "a marked fix and one pass after it close the flake"
    write_jsonl(ledger, flaky + [unit_row("u", "pass", "t2", stamp(1.8))])
    assert run(repo, *flags)[0] == 1, "a pass from before the fix commit proves nothing about the fix"
    write_jsonl(ledger, flaky)
    assert run(repo, *flags)[0] == 1, "the marker alone, with no pass after it, leaves it open"
    closed = flaky + [unit_row("u", "pass", "t2", stamp(1))]
    write_jsonl(ledger, closed + [unit_row("u", "fail", "t3", stamp(0.5))])
    code, out = run(repo, *flags)
    assert code == 1 and "u: open flake since" in out, "a fail after the fix reopens the flake"
    write_jsonl(ledger, closed + [unit_row("u", "fail", "t3", stamp(0.5)), unit_row("u", "pass", "t4", stamp(0.4))])
    assert run(repo, *flags)[0] == 1, "one pass does not re-close it: the fix was voided, not renewed"
    fix_commit("u", 0.3)
    write_jsonl(ledger, closed + [unit_row("u", "fail", "t3", stamp(0.5)), unit_row("u", "pass", "t4", stamp(0.2))])
    assert run(repo, *flags)[0] == 0, "naming the fix again and passing once closes it"
    write_jsonl(ledger, flaky + [unit_row("u", "fail", "t2", stamp(1.7)), unit_row("u", "pass", "t3", stamp(1.6))])
    assert run(repo, *flags)[0] == 1, "a fail after the marker's commit time but before the pass voids it"


def test_flake_ledger_skips_its_own_host_unit(repo: Path, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    flags = ["--rules", "flake-ledger", "--ledger", str(ledger)]
    write(repo, ".fleet.toml", CONFIG + 'host_unit = "_host_check"\n')
    host = [unit_row("_host_check", "fail", "t1", stamp(2)), unit_row("_host_check", "pass", "t1", stamp(2, 5))]
    write_jsonl(ledger, host)
    code, out = run(repo, *flags)
    assert code == 0 and "_host_check: host unit, not counted" in out, "the host unit's own flake cannot hold it red"
    other = [unit_row("u", "fail", "t1", stamp(2)), unit_row("u", "pass", "t1", stamp(2, 5))]
    write_jsonl(ledger, host + other)
    code, out = run(repo, *flags)
    assert code == 1 and "u: open flake since" in out and "1 open flakes, above the baseline of 0" in out
    cfg = tvr.load_config(repo)
    assert cfg is not None
    ledger_rows = host + [{"kind": "run", "run_id": "r", "label": "gate"}]
    new, _ = tvr.update_baseline(None, ledger_rows, cfg, allow_additions=True)
    assert new["flake_count"] == 0, "the baseline does not record the host unit's flake"


def test_new_test_value(repo: Path, tmp_path: Path) -> None:
    ledger, units, cov = tmp_path / "ledger.jsonl", tmp_path / "units.jsonl", tmp_path / "map.json"
    write_jsonl(ledger, [unit_row("_new_unit_check", "fail", "older-tree", stamp(1))])
    write_jsonl(units, [{"unit": u} for u in ("_old_unit_check", "_marked_unit_check", "_new_unit_check",
                                              "tests/test_marked_file.py")])
    ntv = ["--rules", "new-test-value", "--ledger", str(ledger), "--units-report", str(units), "--tree", "this-tree",
           "--coverage-map", str(cov)]
    code, out = run(repo, *ntv)
    assert code == 0, out
    assert "_marked_unit_check: test-value-exempt marker" in out
    assert "tests/test_marked_file.py: test-value-exempt marker" in out
    assert "_new_unit_check: seen red before the fix" in out and "_old_unit_check" not in out
    write_jsonl(ledger, [unit_row("_new_unit_check", "fail", "this-tree", stamp(1))])
    code, out = run(repo, *ntv)
    assert code == 3 and "the coverage map does not exist yet" in out, "red on this very tree is no evidence"
    cov.write_text(json.dumps({"built_utc": stamp(9), "lines": []}), encoding="utf-8")
    code, out = run(repo, *ntv)
    assert code == 3 and "the coverage map is stale" in out
    cov.write_text(json.dumps({"built_utc": stamp(1), "lines": [tvr.line_key("src/app.py", "return 1")]}),
                   encoding="utf-8")
    code, out = run(repo, *ntv)
    assert code == 0 and "_new_unit_check: covers 1 line(s) no other unit covers" in out
    write_jsonl(units, [{"unit": "_dull_unit_check"}, {"unit": "tests/test_late_marker.py"}])
    code, out = run(repo, *ntv)
    assert code == 1 and "_dull_unit_check: NEW unit with no red-before-fix record" in out
    assert "tests/test_late_marker.py: NEW unit" in out, "a marker below the file's header does not count"
    code, out = run(repo, "--rules", "new-test-value", "--ledger", str(ledger), "--tree", "this-tree")
    assert code == 3 and "no live unit report" in out


def test_run_id_reads_the_recorded_run(repo: Path, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    rows = [dict(unit_row("_old_unit_check", "pass", "this-tree", stamp(0), spawns=6), run_id="r1")]
    write_jsonl(ledger, rows)
    code, out = run(repo, "--rules", "spawn-budget", "--ledger", str(ledger), "--run-id", "r1")
    assert code == 1 and "_old_unit_check: 6 spawns, above its baseline of 5" in out
    rows[0]["spawns"] = 5
    write_jsonl(ledger, rows)
    assert run(repo, "--rules", "spawn-budget", "--ledger", str(ledger), "--run-id", "r1")[0] == 0
    code, out = run(repo, "--rules", "spawn-budget", "--ledger", str(ledger), "--run-id", "missing")
    assert code == 3 and "the ledger holds no unit of run missing" in out


def test_hermetic(repo: Path, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    rows = [unit_row("h", "pass", "t1", stamp(1)), unit_row("h", "fail", "t1", stamp(0.5), label="weekly-hermetic-gate"),
            {"kind": "run", "run_id": "t1-" + stamp(0.5), "label": "weekly-hermetic-gate", "utc": stamp(0.5)}]
    write_jsonl(ledger, rows)
    code, out = run(repo, "--rules", "hermetic", "--ledger", str(ledger))
    assert code == 1 and "h: red in a fresh clone, green in the primary checkout" in out
    set_baseline(repo, hermetic=["h"])
    code, out = run(repo, "--rules", "hermetic", "--ledger", str(ledger))
    assert code == 0 and "(baselined)" in out
    write_jsonl(ledger, rows[:1])
    code, out = run(repo, "--rules", "hermetic", "--ledger", str(ledger))
    assert code == 3 and "no `weekly-hermetic-gate` run" in out


def test_update_baseline(repo: Path, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    set_baseline(repo, units={"a": 9, "b": 2})
    write_jsonl(ledger, [unit_row("a", "pass", "t1", stamp(1), spawns=4), unit_row("b", "pass", "t1", stamp(1), spawns=7),
                         unit_row("c", "pass", "t1", stamp(1), spawns=3),
                         {"kind": "run", "run_id": "t1-" + stamp(1), "label": "gate", "utc": stamp(1)}])
    run(repo, "--update-baseline", "--ledger", str(ledger))
    got = json.loads((repo / ".ratchets/test-value.json").read_text(encoding="utf-8"))["units"]
    assert got == {"a": 4, "b": 2}, "shrinks an entry, never raises one, adds nothing"
    run(repo, "--update-baseline", "--allow-additions", "--ledger", str(ledger))
    got = json.loads((repo / ".ratchets/test-value.json").read_text(encoding="utf-8"))["units"]
    assert got == {"a": 4, "b": 2, "c": 3}


def test_update_baseline_drops_a_unit_no_run_reports(repo: Path, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    set_baseline(repo, units={"a": 9, "gone": 2})
    write_jsonl(ledger, [unit_row("a", "pass", "t1", stamp(1), spawns=4),
                         {"kind": "run", "run_id": "t1-" + stamp(1), "label": "gate", "utc": stamp(1)}])
    code, out = run(repo, "--update-baseline", "--ledger", str(ledger))
    got = json.loads((repo / ".ratchets/test-value.json").read_text(encoding="utf-8"))["units"]
    assert got == {"a": 4}, "a deleted unit leaves the baseline, so re-creating it is a new unit again"
    assert code == 0 and "dropped gone" in out


def test_off_by_default_and_bad_config(tmp_path: Path) -> None:
    assert run(tmp_path, "--ledger", str(tmp_path / "l.jsonl"))[0] == 0, "no .fleet.toml: not enabled, exit 0"
    (tmp_path / ".fleet.toml").write_text("[test_value_ratchet]\nenabled = true\nbogus = 1\n", encoding="utf-8")
    code, out = run(tmp_path)
    assert code == 2 and "unknown key 'bogus'" in out
    (tmp_path / ".fleet.toml").write_text("[test_value_ratchet]\nenabled = true\n", encoding="utf-8")
    code, out = run(tmp_path)
    assert code == 1 and "is missing" in out, "an enabled ratchet with no baseline fails"
