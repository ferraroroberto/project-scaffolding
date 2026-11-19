"""Tests for the unit ledger: the writer, the run wrapper, the spawn probe and the pytest reporter.

`record_run` folds a run's unit report and every per-process spawn file into one row per unit plus a run
row, and writes nothing for a run that reported no unit. The run wrapper drives a real pytest session in
a throwaway git repo through `unit_ledger.py run` with the `unit_ledger_pytest` plugin: each test module
is one unit (pass, fail with its failure text, skip), spawns are attributed to the module that made
them, the start tree hash is recorded, and `FLEET_GATE_ONLY` runs only the named modules. The probe's
coverage half hands each module its own covered lines. The working-tree hash moves with an untracked
file and leaves the real index alone.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import unit_ledger as ul
from src.no_window import NO_WINDOW
from tests._git_repo import git, write

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
ALL_ENVS = (ul.UNIT_REPORT_ENV, ul.SPAWN_REPORT_ENV, ul.CURRENT_UNIT_ENV, ul.TREE_ENV, ul.ONLY_ENV,
            ul.COVERAGE_REPORT_ENV, ul.COVERAGE_ROOT_ENV)

TEST_A = """import subprocess, sys
from src.mod import double

def test_spawns_once():
    subprocess.run([sys.executable, "-c", "pass"], check=True)
    assert double(2) == 4
"""
TEST_B = """def test_breaks():
    assert 1 + 1 == 3, "arithmetic broke"

def test_fine():
    pass
"""
TEST_C = """import pytest

@pytest.mark.skip(reason="not here")
def test_skipped():
    pass
"""


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scaffold's own gate may run these tests under the reporters; none of that may leak in."""
    for name in ALL_ENVS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PYTHONPATH", str(SCRIPTS))


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root, ".gitignore", "__pycache__/\n")
    write(root, "pytest.ini", "[pytest]\ntestpaths = tests\npythonpath = .\n")
    write(root, "src/__init__.py", "")
    write(root, "src/mod.py", "def double(x):\n    return x * 2\n\n\ndef unused():\n    return 0\n")
    write(root, "tests/test_a.py", TEST_A)
    write(root, "tests/test_b.py", TEST_B)
    write(root, "tests/test_c.py", TEST_C)
    return root


PYTEST = [sys.executable, "-m", "pytest", "-q", "-p", "unit_ledger_pytest", "-p", "no:cacheprovider"]


def run_wrapper(project: Path, ledger: Path, *extra: str) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = ul.main(["run", "--ledger", str(ledger), "--label", "gate", "--repo", str(project), *extra, "--", *PYTEST])
    return code, out.getvalue()


def rows_by_unit(ledger: Path) -> dict[str, dict[str, Any]]:
    return {str(r["unit"]): r for r in ul.load(ledger) if r.get("kind") == "unit"}


def test_record_run_folds_units_and_every_spawn_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / ul.UNITS_FILE).write_text(
        json.dumps({"unit": "a", "status": "pass", "seconds": 1.5}) + "\n"
        + json.dumps({"unit": "b", "status": "fail", "seconds": 0.5, "output": "x" * (ul.OUTPUT_TAIL_CHARS + 50)}) + "\n"
        + "{half a line", encoding="utf-8")
    (run_dir / f"{ul.SPAWNS_FILE}.11").write_text(json.dumps({"unit": "a"}) + "\n" + json.dumps({"unit": ""}) + "\n",
                                                  encoding="utf-8")
    (run_dir / f"{ul.SPAWNS_FILE}.12").write_text(json.dumps({"unit": "a"}) + "\n", encoding="utf-8")
    ledger = tmp_path / "state" / "ledger.jsonl"
    written = ul.record_run(run_dir, ledger, label="gate", wtree="t1", exit_code=1, seconds=2.345, run_id="r1",
                            now="2026-01-01T00:00:00Z")
    assert written == 2
    rows = ul.load(ledger)
    units = {r["unit"]: r for r in rows if r["kind"] == "unit"}
    assert units["a"]["spawns"] == 2 and units["b"]["spawns"] == 0
    assert len(units["b"]["output"]) == ul.OUTPUT_TAIL_CHARS and "output" not in units["a"]
    run = next(r for r in rows if r["kind"] == "run")
    assert run == {"kind": "run", "run_id": "r1", "utc": "2026-01-01T00:00:00Z", "label": "gate", "wtree": "t1",
                   "exit": 1, "seconds": 2.35, "spawns": 3, "units": 2}, "a spawn outside any unit stays in the total"


def test_record_run_writes_nothing_for_a_silent_run(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    assert ul.record_run(tmp_path, ledger, label="gate", wtree=None, exit_code=0, seconds=1.0) == 0
    assert not ledger.exists()


def test_run_wrapper_records_each_pytest_module(project: Path, tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    code, out = run_wrapper(project, ledger, "--run-id", "r1")
    assert code == 1, "the wrapper exits with the gate command's own code"
    assert "UNIT_LEDGER=recorded run_id=r1 units=3" in out
    units = rows_by_unit(ledger)
    assert set(units) == {"tests/test_a.py", "tests/test_b.py", "tests/test_c.py"}
    assert units["tests/test_a.py"]["status"] == "pass" and units["tests/test_a.py"]["spawns"] >= 1
    assert units["tests/test_b.py"]["status"] == "fail" and "arithmetic broke" in units["tests/test_b.py"]["output"]
    assert units["tests/test_c.py"]["status"] == "skip" and units["tests/test_c.py"]["spawns"] == 0
    assert units["tests/test_a.py"]["wtree"] == ul.tree_hash(project) and units["tests/test_a.py"]["wtree"]


def test_only_env_runs_only_the_named_modules(project: Path, tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ul.ONLY_ENV, "tests/test_a.py")
    ledger = tmp_path / "ledger.jsonl"
    code, _out = run_wrapper(project, ledger)
    assert code == 0
    assert set(rows_by_unit(ledger)) == {"tests/test_a.py"}


def test_the_probe_hands_each_module_its_covered_lines(project: Path, tmp_path: Path) -> None:
    report = tmp_path / "coverage.jsonl"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(ul.PROBE_DIR), str(SCRIPTS)]),
           ul.COVERAGE_REPORT_ENV: str(report), ul.COVERAGE_ROOT_ENV: str(project), ul.ONLY_ENV: "tests/test_a.py"}
    subprocess.run(PYTEST, cwd=project, env=env, capture_output=True, timeout=300, check=False,
                   creationflags=NO_WINDOW)
    rows = ul.read_report(report)
    lines = {(rel, text) for r in rows if r["unit"] == "tests/test_a.py" for rel, _n, text in r["lines"]}
    assert ("src/mod.py", "return x * 2") in lines
    assert ("src/mod.py", "return 0") not in lines, "a line nobody ran is not covered"


def test_tree_hash_moves_with_an_untracked_file_and_spares_the_index(project: Path) -> None:
    index = project / ".git" / "index"
    before_index = index.read_bytes()
    first = ul.tree_hash(project)
    (project / "new_file.txt").write_text("x", encoding="utf-8")
    second = ul.tree_hash(project)
    assert first and second and first != second
    assert index.read_bytes() == before_index
    assert ul.tree_hash(project.parent) is None, "not a git tree: unknown, never a hash"


def test_summary_reads_the_last_runs(tmp_path: Path) -> None:
    ledger = tmp_path / "ledger.jsonl"
    rows = [{"kind": "unit", "run_id": f"r{i}", "label": "gate", "unit": "u", "status": "pass", "seconds": float(i)}
            for i in (1, 2, 3)] + [{"kind": "run", "run_id": f"r{i}", "label": "gate", "seconds": float(i), "spawns": 1}
                                   for i in (1, 2, 3)]
    ledger.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = ul.main(["summary", "--ledger", str(ledger), "--runs", "2"])
    data = json.loads(out.getvalue())
    assert code == 0 and data["runs"] == 2 and data["top"] == [{"unit": "u", "median_seconds": 2.5}]
    with contextlib.redirect_stdout(io.StringIO()):
        assert ul.main(["summary", "--ledger", str(tmp_path / "none.jsonl")]) == 1, "no run is not a summary"
