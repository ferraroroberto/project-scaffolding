# Test value ratchet

The test value family measures what a test suite costs and whether each new test earns its place. It is five vendored components, each off until a repo turns it on:

| Component | File | What it does |
|---|---|---|
| `unit_ledger` | `scripts/unit_ledger.py` | Runs the gate's test command under the reporters and appends one row per unit to the run ledger; reads the ledger back (`summary`). |
| `spawn_probe` | `scripts/spawn_probe/sitecustomize.py` | Loaded at interpreter start from `PYTHONPATH`: counts every `subprocess.Popen` per unit and, when asked, records each unit's covered lines. |
| `unit_ledger_pytest` | `scripts/unit_ledger_pytest.py` | pytest plugin: one test module is one unit; honours `FLEET_GATE_ONLY`. |
| `test_value_ratchet` | `scripts/test_value_ratchet.py` | The ratchet: four rules over the ledger and the run being checked. |
| `weekly_burst` | `scripts/weekly_burst.py` | The weekly job: burn and load units, a fresh-clone gate, the coverage map, the runtime medians. |

It holds the decision "A new test earns its place, and the suite's cost only shrinks" in [architecture decisions](architecture-decisions.md). The shared ratchet contract applies: stdlib-only scripts copied byte for byte, a committed baseline that only shrinks unless `--allow-additions` says otherwise in review, exit 3 as its own failing state, and a `test-value-exempt: <reason>` marker for a single exception.

It differs from the other ratchets in one way: it reads the results of a test run, so it runs **after** the tests, never as a pre-test stage, and `run_ratchets.py` does not run it.

## The unit

A **unit** is a whole check function or a whole test file, never one assertion. Under the pytest plugin a unit is a test module, named by its path from the rootdir (`tests/test_<name>.py`). A repo with its own dispatcher reports a unit per check function by calling `unit_ledger.begin_unit(name)` and `unit_ledger.end_unit(name, status, seconds, output)` around it.

## The rules

| Rule | Fails when | Runs |
|---|---|---|
| `new-test-value` | A unit missing from the baseline at the merge base with `base_ref` (new in the diff) shows none of: a `test-value-exempt: <reason>` marker; a ledger record of it failing on a tree other than this one (red before the fix); a covered source line that the weekly coverage map lacks. A missing or stale map is exit 3. | per change, new units only |
| `spawn-budget` | A unit's process spawns in this run rise above its baseline entry, or a unit has no entry. Spawns stand in for cost because they do not flake under box load. | per change |
| `flake-ledger` | Open flakes (a unit that passed and failed on one tree hash under the gate label, until one of the two closing routes below) rise above the baseline's `flake_count`, or one stays open past `flake_max_age_days`. The `host_unit` (the unit that runs this verdict) is not counted: it would fail itself on every run and never collect the passes that close its flake; its rows stay on the ledger and `new-test-value` and `spawn-budget` still judge it. | per change |
| `hermetic` | A unit red in the latest fresh-clone gate run is green in the latest checkout run, and is not in the baseline's `hermetic` list. No fresh-clone run in `hermetic_max_age_days` is exit 3. | weekly |

Wall-clock time is never a rule. The weekly burst records the medians; nothing fails on them.

**Exempt marker.** On a function unit: on its `def` line or in the comment block right above it. On a file unit: anywhere in the file's header, before its first `import`, `from`, `def` or `class` (the module docstring or the leading comments). Give a reason a reviewer can check: `test-value-exempt: renders a doc page, covers no source`.

**Closing a flake.** Two routes, and a flake closes by whichever comes first:

- *No known cause:* `flake_clear_runs` gate passes of the unit in a row after the flake. A fail in between restarts the count.
- *Named fix:* a commit in the history of `HEAD`, dated after the flake, carries the trailer `Flake-Fixed: <unit>` (the unit's name exactly as the ledger holds it; one trailer per unit), and the unit then passes once under the gate label. The trailer is read from the commit message, so the fix is reviewable in the same change as the code. A fail of the unit after the trailer's commit voids that fix: it reopens a flake the fix had closed, and the fix must be named again in a later commit (or the 10 passes collected). A trailer dated before the flake, or on another unit, closes nothing.

The pass is matched to the fix by time (a ledger pass after the fix commit's date), not by tree hash, so run the gate on the branch that carries the fix before relying on it. A commit history git cannot read yields no named fixes: the flake stays open, never closed.

**Red before the fix.** Run the new test on the pre-fix tree through the wrapper with `FLEET_GATE_ONLY=<unit>`; its failing row, on a tree the fix then changes, is the evidence.

## Configuration

```toml
[test_value_ratchet]
enabled     = true
baseline    = ".test-value-ratchet-baseline.json"   # the default
unit_roots  = ["tests"]                            # where units are declared, and their exempt markers
unit_runner = ["-m", "pytest", "-q", "-p", "scripts.unit_ledger_pytest"]   # argv after the interpreter
base_ref    = "origin/main"
label       = "gate"                               # the ledger label of per-change runs
capture_runs = 3                                   # --update-baseline takes each unit's max over these
flake_clear_runs = 10
host_unit   = ""                                   # the unit that evaluates this ratchet; its own flake is not counted
coverage_map_max_age_days = 8
hermetic_label = "weekly-hermetic-gate"
hermetic_max_age_days = 8
coverage_timeout_s = 1800

[test_value_burst]
enabled = true
gate    = ["-m", "pytest", "-q", "-p", "scripts.unit_ledger_pytest", "--ignore=tests/weekly"]
weekly  = ["-m", "pytest", "-q", "-p", "scripts.unit_ledger_pytest", "tests/weekly"]   # optional
```

Every key but `enabled` is optional. The `[test_value_ratchet]` values above are its defaults; the burst's `gate` defaults to the `unit_runner` value without the `--ignore`, and `weekly` has no default (without it the burst runs no weekly-units legs). An unknown key is exit 2. `unit_runner` and `gate` are the argv after the interpreter; a first item that is not a flag is a repo-relative script.

Machine-local paths are arguments, never config: the ledger, the coverage map, the burst's results folder. Keep all three in the repo's runtime state location (for a scaffold app, beside its runtime data, `runtime_db_path(<app>, ...)`'s folder; never a tracked path). The ledger is history for this machine; it is never committed.

## Steps

1. Vendor the five components (`/propagate-vendored` carries `requires` along) and list them under `[vendored]`.
2. Move every burn, load or wall-clock proof out of the per-change suite into the weekly set: for pytest, one folder (`tests/weekly/` below) that the per-change command skips with `--ignore` and the `weekly` command names.
3. Wrap the gate's test command and run the ratchet after it, with one run id:

   ```powershell
   $runId  = [guid]::NewGuid().ToString("N")
   $ledger = "<state dir>\gate-unit-ledger.jsonl"
   & $py scripts/unit_ledger.py run --ledger $ledger --label gate --run-id $runId -- `
       $py -m pytest -q -p scripts.unit_ledger_pytest --ignore=tests/weekly
   & $py scripts/test_value_ratchet.py --ledger $ledger --run-id $runId `
       --coverage-map "<state dir>\test-value-coverage-map.json" --probe-dir scripts/spawn_probe
   ```

   The wrapper exits with the tests' own code. The ratchet's exit 3 fails the gate.
4. Run the gate three times, then write the baseline: `test_value_ratchet.py --update-baseline --allow-additions --ledger <ledger>`. Commit `.test-value-ratchet-baseline.json`.
5. Schedule the burst weekly on the main machine (an app-launcher Job calling the script directly, no model): `weekly_burst.py --ledger <ledger> --coverage-map <map> --results-dir <state dir>\weekly-burst`. Run it once by hand: `new-test-value` stays exit 3 until the first coverage map exists.
6. Turn on both tables.

A repo whose gate already runs through a gate-evidence helper that sets the same report variables (`FLEET_GATE_UNIT_REPORT`, `FLEET_GATE_SPAWN_REPORT`, `FLEET_GATE_WTREE` and the probe on `PYTHONPATH`) can run the ratchet inside the gate on the live reports instead: `--units-report`, `--spawns-report`, `--tree`. A repo with its own leg runner builds a `weekly_burst.Burst` with `leg_argv` and calls `weekly_burst.main(argv, burst)`.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Every rule passed, or the table is off. |
| 1 | A rule failed, or the baseline is missing. |
| 2 | Bad `.fleet.toml` table, baseline or arguments. |
| 3 | Not confirmed: no ledger, no report of the run, a missing or stale coverage map, no merge base, no recent fresh-clone run. A failure, never a pass. |

The burst exits 0 when every leg is green, 1 when a unit is red, 3 when a leg could not be established (no clone, no ledger row for a green exit, a skipped leg, no gate history).

## Baselines burn down

`--update-baseline` lowers a unit's spawn entry to the highest count over the last `capture_runs` gate runs and never raises one; `--allow-additions` records new units and shows in review. `flake_count` only falls. The `hermetic` list keeps only units the runs still see. Existing units are never failed for low value: merge candidates go to a person through a report, never through the gate.
