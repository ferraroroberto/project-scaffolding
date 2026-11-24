"""Tests for the weekly burst (`scripts/weekly_burst.py`).

Real throwaway git repos hold fake test commands that report units the way a unit reporter does, so each
case drives the real `unit_ledger.py run` -> ledger -> verdict path: all green exits 0 with a summary in
the results folder and the hermetic gate's coverage built into the coverage map; a red unit exits 1 and
is named; the hermetic legs run in a detached clone that lacks an ignored file the working tree has; a
clone that cannot be made, a skipped leg, no gate history and a green exit with no ledger row are each
`not-confirmed` (exit 3), never green; old summaries are pruned; the `.fleet.toml` table is off by
default and a bad one is exit 2.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from scripts import unit_ledger as ul
from scripts import weekly_burst as wb
from tests._git_repo import git, write

RATCHET = Path(__file__).resolve().parents[2] / "scripts" / "test_value_ratchet.py"

# Reports the way a unit reporter does: one JSON line per unit to FLEET_GATE_UNIT_REPORT.
FAKE = """\
import json, os, sys
from pathlib import Path
marker = Path(__file__).resolve().parent.parent / 'IGNORED_MARKER'
rows = [{'unit': 'steady', 'status': 'pass', 'seconds': 0.1}]
if os.environ.get('FAKE_RED') and Path(__file__).name == 'run_gate.py':
    rows.append({'unit': 'broken', 'status': 'fail', 'seconds': 0.2})
if marker.exists():
    rows.append({'unit': 'sees_ignored_file', 'status': 'pass', 'seconds': 0.1})
if os.environ.get('FLEET_GATE_COVERAGE_REPORT'):
    Path(os.environ['FLEET_GATE_COVERAGE_REPORT']).write_text(json.dumps(
        {'unit': 'steady', 'lines': [['src.py', 1, 'VALUE = 1'], ['elsewhere.py', 1, 'x']]}) + chr(10),
        encoding='utf-8')
if not os.environ.get('FAKE_SILENT'):
    Path(os.environ['FLEET_GATE_UNIT_REPORT']).write_text(
        ''.join(json.dumps(r) + chr(10) for r in rows), encoding='utf-8')
sys.exit(1 if any(r['status'] == 'fail' for r in rows) else 0)
"""


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (ul.UNIT_REPORT_ENV, ul.SPAWN_REPORT_ENV, ul.CURRENT_UNIT_ENV, ul.TREE_ENV, ul.ONLY_ENV,
                 ul.COVERAGE_REPORT_ENV, ul.COVERAGE_ROOT_ENV, "FAKE_RED", "FAKE_SILENT"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def burst(tmp_path: Path) -> wb.Burst:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "core.hooksPath", str(tmp_path / "no-hooks"))  # the machine's commit hooks are not under test
    for name in ("run_weekly.py", "run_gate.py"):
        write(repo, f"tests/{name}", FAKE)
    write(repo, ".gitignore", "IGNORED_MARKER\n")
    (repo / "IGNORED_MARKER").write_text("only the working tree has this\n", encoding="utf-8")
    write(repo, "src.py", "VALUE = 1\n")
    write(repo, ".fleet.toml", "[test_value_ratchet]\nenabled = true\n")
    write(repo, ".ratchets/test-value.json", '{"units": {}}\n')
    git(repo, "commit", "-q", "-m", "fake commands")
    state = tmp_path / "state"
    return wb.Burst(repo=repo, ledger=state / "ledger.jsonl", coverage_map=state / "map.json",
                    results_dir=state / "weekly-burst", ratchet=RATCHET, gate=["tests/run_gate.py"],
                    weekly=["tests/run_weekly.py"])


def seed_gate_history(burst: wb.Burst) -> None:
    rows = [{"kind": "unit", "run_id": "g1", "label": "gate", "unit": "steady", "status": "pass", "seconds": 2.0},
            {"kind": "run", "run_id": "g1", "label": "gate", "exit": 0, "seconds": 2.0, "spawns": 1, "units": 1}]
    burst.ledger.parent.mkdir(parents=True, exist_ok=True)
    with burst.ledger.open("a", encoding="utf-8") as fh:
        fh.write("".join(json.dumps(r) + "\n" for r in rows))


def run_burst(burst: wb.Burst, *args: str) -> tuple[int, str, dict[str, Any]]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = wb.main(list(args), burst)
    newest = sorted(burst.results_dir.glob("*.json"))[-1]
    return code, out.getvalue(), json.loads(newest.read_text(encoding="utf-8"))


def test_every_leg_green(burst: wb.Burst) -> None:
    seed_gate_history(burst)
    code, text, summary = run_burst(burst)
    assert code == 0 and summary["verdict"] == "green", text[-500:]
    assert [leg["leg"] for leg in summary["legs"]] == ["units", "hermetic-units", "hermetic-gate", "coverage-map",
                                                        "hermetic-rule"]
    cov_map = json.loads(burst.coverage_map.read_text(encoding="utf-8"))
    assert len(cov_map["lines"]) == 1 and cov_map["lines"][0].startswith("src.py:") and cov_map["units"] == {"steady": 1}
    assert summary["medians"]["state"] == "green" and summary["medians"]["top"][0]["unit"] == "steady"
    assert all((burst.results_dir / leg["log"]).is_file() for leg in summary["legs"])
    assert sorted(p.name for p in burst.repo.iterdir()) == sorted(
        [".fleet.toml", ".git", ".gitignore", ".ratchets", "IGNORED_MARKER", "src.py", "tests"]), \
        "nothing is written next to the code"
    in_tree = {r["unit"] for r in ul.load(burst.ledger, label="weekly-units") if r.get("kind") == "unit"}
    in_clone = {r["unit"] for r in ul.load(burst.ledger, label="weekly-hermetic-gate") if r.get("kind") == "unit"}
    assert "sees_ignored_file" in in_tree and "sees_ignored_file" not in in_clone, "the clone lacks the ignored file"


def test_a_red_unit_is_red_and_named(burst: wb.Burst, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_gate_history(burst)
    monkeypatch.setenv("FAKE_RED", "1")
    code, text, summary = run_burst(burst)
    red = [leg for leg in summary["legs"] if leg["state"] == "red"]
    assert code == 1 and summary["verdict"] == "red" and red and red[0]["red_units"] == ["broken"]
    assert "broken" in text


def test_a_green_exit_with_no_ledger_row_is_not_a_pass(burst: wb.Burst, monkeypatch: pytest.MonkeyPatch) -> None:
    seed_gate_history(burst)
    monkeypatch.setenv("FAKE_SILENT", "1")
    code, _text, summary = run_burst(burst, "--skip-hermetic")
    assert code == 3 and summary["legs"][0]["state"] == "not-confirmed"


def test_a_skipped_hermetic_leg_is_never_green(burst: wb.Burst) -> None:
    seed_gate_history(burst)
    code, _text, summary = run_burst(burst, "--skip-hermetic")
    assert code == 3 and summary["verdict"] == "not-confirmed" and summary["legs"][1]["state"] == "not-confirmed"


def test_no_gate_history_leaves_the_medians_unconfirmed(burst: wb.Burst) -> None:
    code, _text, summary = run_burst(burst)
    assert code == 3 and summary["medians"]["state"] == "not-confirmed" and summary["verdict"] == "not-confirmed"


def test_a_clone_that_cannot_be_made(burst: wb.Burst, tmp_path: Path) -> None:
    plain = tmp_path / "nogit"
    (plain / "tests").mkdir(parents=True)
    shutil.copy(burst.repo / "tests" / "run_weekly.py", plain / "tests" / "run_weekly.py")
    burst.repo = plain
    seed_gate_history(burst)
    code, _text, summary = run_burst(burst)
    clone_leg = next((leg for leg in summary["legs"] if leg["leg"] == "hermetic"), None)
    assert code == 3 and clone_leg == {"leg": "hermetic", "state": "not-confirmed", "reason": "clone or detach failed"}


def test_old_summaries_are_pruned_with_their_logs(tmp_path: Path) -> None:
    for n in range(wb.KEEP_RUNS + 3):
        (tmp_path / f"2000010{n:02d}T000000Z.json").write_text("{}", encoding="utf-8")
        (tmp_path / f"2000010{n:02d}T000000Z-units.log").write_text("", encoding="utf-8")
    wb.prune(tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == wb.KEEP_RUNS
    assert len(list(tmp_path.glob("*-units.log"))) == wb.KEEP_RUNS


def test_the_config_table(tmp_path: Path) -> None:
    def cli(*args: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = wb.main(["--repo", str(tmp_path), *args])
        return code, out.getvalue()

    assert cli() == (0, "weekly burst: not enabled in .fleet.toml\n")
    (tmp_path / ".fleet.toml").write_text("[test_value_burst]\nenabled = true\n", encoding="utf-8")
    code, out = cli()
    assert code == 2 and "--ledger, --coverage-map, --results-dir" in out
    (tmp_path / ".fleet.toml").write_text("[test_value_burst]\nenabled = true\ngate = []\n", encoding="utf-8")
    code, out = cli("--ledger", "l", "--coverage-map", "m", "--results-dir", "d")
    assert code == 2 and "gate must be a non-empty list of strings" in out
    (tmp_path / ".fleet.toml").write_text("[test_value_burst]\nenabled = true\nnightly = true\n", encoding="utf-8")
    code, out = cli()
    assert code == 2 and "unknown key(s): nightly" in out


def test_the_ratchets_labels_and_unit_runner_reach_the_burst(tmp_path: Path) -> None:
    paths = {"ledger": tmp_path / "l", "coverage_map": tmp_path / "m", "results_dir": tmp_path / "d", "ratchet": None}
    args = type("Args", (), paths)()
    toml = tmp_path / ".fleet.toml"
    toml.write_text("[test_value_burst]\nenabled = true\n", encoding="utf-8")
    burst = wb._from_config(tmp_path, args)  # type: ignore[arg-type]
    assert burst is not None and (burst.gate_label, burst.hermetic_label) == ("gate", "weekly-hermetic-gate")
    toml.write_text(
        '[test_value_ratchet]\nenabled = true\nlabel = "ci"\nhermetic_label = "nightly-hermetic"\n'
        'unit_runner = ["-m", "pytest", "-q", "-p", "mine"]\n[test_value_burst]\nenabled = true\n',
        encoding="utf-8",
    )
    burst = wb._from_config(tmp_path, args)  # type: ignore[arg-type]
    assert burst is not None
    assert (burst.gate_label, burst.hermetic_label) == ("ci", "nightly-hermetic")
    assert burst.gate == ["-m", "pytest", "-q", "-p", "mine"]
    # An explicit `gate` in the burst table still wins over the ratchet's runner.
    toml.write_text(toml.read_text(encoding="utf-8") + 'gate = ["-m", "pytest"]\n', encoding="utf-8")
    burst = wb._from_config(tmp_path, args)  # type: ignore[arg-type]
    assert burst is not None and burst.gate == ["-m", "pytest"]
    toml.write_text("[test_value_ratchet]\nenabled = true\nlabel = 3\n[test_value_burst]\nenabled = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="label must be a non-empty string"):
        wb._from_config(tmp_path, args)  # type: ignore[arg-type]
