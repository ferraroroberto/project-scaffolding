# Adopting the gate ratchets in any repo

The one entry point for bringing this scaffold's baseline-and-ratchet gate stages into a repository that is not part of the owner's fleet: a work repo, a fresh clone, any machine. You need nothing private, only this public repository.

A ratchet measures one kind of debt (issue references in comments, oversized files, writes into code folders...), records today's count in a committed baseline file, and fails the gate only when the count **rises**. Existing debt never blocks work; it just cannot grow. Each script is a single file (plus named sibling modules), Python standard library only, and does nothing until the repo opts in.

## Prerequisites

| Need | For | Without it |
|---|---|---|
| Python 3.11 or newer | every ratchet (`tomllib`) | the scripts do not start |
| `git`, target is a git work tree | every ratchet except static reads its file list from `git ls-files` | exit 3, not confirmed |
| `ruff` installed for the same Python | the static ratchet only | static is not adopted |
| Node with `npx` and network on first use | the static ratchet's duplicate check only | set `duplicates = false`; the check reports OFF |

Nothing else: no fleet tooling, no private skill, no configuration repository.

## The ratchets

Listed in gate stage order, the order `scripts/run_ratchets.py` runs them. **Siblings** are modules the script loads from its own folder; copy them with it or it exits 3. **Start** marks the recommended first set: Python only, nothing to choose, and the default of `adopt_ratchets.py`.

| Ratchet | Script and siblings | Extra prerequisites | Cost | Start | Reference |
|---|---|---|---|---|---|
| static | `static_ratchet.py` | ruff; Node for duplicates | slow first run (downloads jscpd) | | [static-ratchet.md](static-ratchet.md) |
| comment | `comment_ratchet.py` | - | fast | yes | [comment-ratchet.md](comment-ratchet.md) |
| docs | `docs_ratchet.py` | - | fast | yes | [docs-ratchet.md](docs-ratchet.md) |
| structure | `structure_ratchet.py`, `structure_layout.py`, `structure_band.py` | - | fast | yes | [structure-ratchet.md](structure-ratchet.md) |
| instruction | `instruction_ratchet.py`, `instruction_frontmatter.py`, `instruction_repeats.py` | - | fast | yes | [instruction-ratchet.md](instruction-ratchet.md) |
| doc refs | `doc_refs_ratchet.py` | - | fast | yes | [doc-refs-ratchet.md](doc-refs-ratchet.md) |
| dead code | `dead_code_ratchet.py` | - | fast | yes | [dead-code-ratchet.md](dead-code-ratchet.md) |
| conventions | `conventions_ratchet.py`, `conventions_readers.py`, `conventions_state.py` | choose `rules` | fast | | [conventions-ratchet.md](conventions-ratchet.md) |
| runtime write | `runtime_write_ratchet.py`, `runtime_write_resolve.py` | a test command, for the probe | fast | yes | [runtime-write-ratchet.md](runtime-write-ratchet.md) |
| usage track | `usage_track_ratchet.py`, `usage_track_scan.py` | a web UI; choose `rules` | fast | | [usage-track-ratchet.md](usage-track-ratchet.md) |

[ratchet-catalog.md](ratchet-catalog.md) lists every rule of every ratchet by category, with a bad and a fixed snippet for each; read it to learn what a ratchet will flag before you adopt it.

Two of the reference docs' terms belong to the owner's fleet and can be ignored here: `/propagate-vendored` (a private re-vendoring skill) and the e2e routing step (only for repos that use this scaffold's e2e router). `[vendored]` is **not** fleet-only: the ratchets read its `dest` entries to skip their own copies, so keep it.

## Steps

Clone this repository anywhere (it is the source; nothing is installed from it), then work in the target repo.

1. **Copy and initialise in one command:**

   ```
   <scaffold>/.venv/Scripts/python.exe <scaffold>/scripts/tools/adopt_ratchets.py <target> [--ratchets comment,structure,runtime_write]
   ```

   `--ratchets` takes a comma list, `recommended` (the default, the **Start** column) or `all`. For each ratchet it copies the script and siblings into `<target>/scripts/`, records every copy in `<target>/.fleet.toml` under `[vendored]`, appends a minimal `[<name>_ratchet]` table with `enabled = true`, copies the runner `run_ratchets.py`, and runs `--init` to write the first baseline, printing each exit code. Run it again at any time: an identical copy, an existing table and an existing baseline are left alone. A copy that differs from the scaffold's is **refused, never overwritten**, and the run exits 1 naming it.

   Without the script, do the same by hand: copy the files from the table, add `[<name>_ratchet]` with `enabled = true` to `.fleet.toml`, add a `[vendored]` line `<module> = { src = "scripts/<file>", dest = "scripts/<file>" }` per copied file, and run `python scripts/<name>_ratchet.py --init` for each.

2. **Review the baselines.** Each `.<name>-ratchet-baseline.json` at the repo root is today's debt, one entry per line. Adoption never requires cleaning it up first.

3. **Commit** `scripts/`, `.fleet.toml` and the baseline files together.

4. **Wire the gate.** Run the runner wherever the repo's checks run (a pre-push script, a Makefile target, CI):

   ```
   .venv/Scripts/python.exe scripts/run_ratchets.py --tests .venv/Scripts/python.exe -m pytest -q
   ```

   Everything after `--tests` is the test command. The runner runs every enabled ratchet in stage order, then takes the runtime write snapshot, runs the tests and runs the probe, so a file the tests leave under a code folder fails the gate. Without `--tests` the probe prints OFF. On GitHub Actions, copy `.github/workflows/ci-ratchets.yml.template` to `ci-ratchets.yml` in the target's workflows folder.

   Never path-route a ratchet stage (run it only when some files changed): each one compares the whole tree with its baseline.

## Exit codes

Every ratchet and the runner share one contract; a state is never folded into a pass.

| Exit | Meaning | Gate |
|---|---|---|
| 0 | pass, or the ratchet is not enabled (an absent table is a declared skip) | passes |
| 1 | a count rose above the baseline, or the baseline file is missing | fails |
| 2 | bad configuration, baseline or arguments | fails |
| 3 | **not confirmed**: the check could not run (a sibling or tool missing, git unusable, a file it cannot read) | fails |

The runner adds two states of its own: no enabled ratchet at all is exit 2, and a failing test command is exit 1. A check that is switched off (`duplicates = false`, a probe without `--tests`) prints **OFF**, never "clean".

## Baselines burn down, never up

- When a counted hit disappears, the check still passes and prints a hint. Run `python scripts/<name>_ratchet.py --update-baseline` and commit the smaller file.
- `--update-baseline` refuses to add entries. A genuinely new, accepted hit needs `--update-baseline --allow-additions`, which shows up in review as added baseline lines. Re-baselining just to get green is the one thing the ratchet exists to stop.
- `--init` never overwrites an existing baseline.

## Turning on the state rules

Three rules of the conventions ratchet find **implicit state machines**: a concept that really has modes (stopped, loading, ready, failed) but never declares them as one official state. They flag suspects; a person or agent confirms each one before anything is declared. What a machine is and how to declare one well: [implicit-state-machines.md](implicit-state-machines.md); every rule with bad and fixed snippets: [conventions-ratchet.md](conventions-ratchet.md).

| Rule | A hit is |
|---|---|
| `state-literal` | a lifecycle string compared or stored as a state (`job.status == "running"`, `case 'failed':`) |
| `state-set-repeat` | one set of lifecycle strings spelled out in more than one module |
| `state-write` | a lifecycle-named flag (`load.ready = True`) written from more than one module |

**1. Turn them on.** The conventions ratchet is adopted first (the table above; `adopt_ratchets.py --ratchets conventions` copies all three files and writes a starter `rules` line). Add the three names to `rules` in `.fleet.toml`:

```toml
[conventions_ratchet]
enabled = true
rules   = ["subprocess-timeout", "state-literal", "state-set-repeat", "state-write"]
```

Python, JavaScript and TypeScript (`.js` `.mjs` `.cjs` `.ts` `.jsx` `.tsx`) are read with no further setting; test modules and minified bundles are skipped. Then record today's hits once. In a repo that already has a baseline, the new rules' hits read as additions, so the one time you run `python scripts/conventions_ratchet.py --update-baseline --allow-additions` and commit the larger file, say so in the pull request. On a first adoption `--init` writes it. Rules you did not list never appear, so a repo is never flagged for a rule it did not choose.

**2. Declare a machine.** When a suspect is confirmed, its owner is one module, declared as a top-level `[[state_machines]]` table in `.fleet.toml`. `name` is the concept, `module` the one file that owns it, `type` the declared state type defined there, `derive` the optional function that computes the state from the facts. Code in a declared module is never reported; any other module that re-derives the state stays a hit.

```toml
[[state_machines]]                       # a Python owner: a class, Enum or type alias
name   = "job"
module = "src/jobs/state.py"
type   = "JobState"
derive = "derive_job_state"

[[state_machines]]                       # a JavaScript or TypeScript owner: a top-level const, class, enum or type
name   = "upload"
module = "app/webapp/static/upload-state.js"
type   = "UploadState"
derive = "deriveUploadState"
```

A declaration that names a module, type or function that is not there is **not confirmed** (exit 3), never a skip. After declaring, migrate the other readers to the type or the derive function one at a time, then shrink the baseline (step 5).

**3. Add an illegal-transition test.** A machine counts as proven when at least one test shows it refuses a transition it must not allow. Mark that test with `state-machine-proof: <name>` (the machine's `name`) in the comment block right above its `def`, in its docstring or in a comment in its body:

```python
# state-machine-proof: job
def test_done_job_cannot_become_running():
    with pytest.raises(ValueError):
        derive_job_state(finished=True, process_alive=True)
```

Only Python functions named `test*` in a test file count; the scoreboard counts the marker, it does not run the test, so a reviewer checks that the test really asserts the refusal. A JavaScript or TypeScript test is marked the same way, in a `//` or `/* */` comment right above its `test(...)` / `it(...)` call or inside it:

```js
// state-machine-proof: job
test('a done job cannot become running', () => {
  assert.throws(() => deriveJobState({ finished: true, processAlive: true }));
});
```

**4. Read your row in the scoreboard.** `scripts/tools/state_scoreboard.py` is a scaffold script, not vendored; run it from a scaffold checkout with that checkout's interpreter and point `--root` at the folder holding your repos:

```
.venv/Scripts/python.exe scripts/tools/state_scoreboard.py --root <folder-with-your-repos> --repo <your-repo> --at default
```

The row carries the three rules' counts split Python / JavaScript, the duplicate derivations (`state-write` plus `state-set-repeat`: places outside the owner that write its flag or re-spell its states), the declared machines and how many of them have `no proof`. The first two targets are 0. A `?` means the repo could not be read (no committed baseline, a `.fleet.toml` that does not parse) and is never zero; `-` means the repo has not listed a state rule. The command reads committed state only, so the same commit prints the same bytes; the exit code is 3 when any repo is unknown. The columns are defined in [implicit-state-machines.md](implicit-state-machines.md), "Scoreboard".

**5. Burn the baseline to zero.** Work the repo's own list, one separable change at a time:

1. Run `python scripts/conventions_ratchet.py`; it prints every hit of a risen rule, and the baseline file lists the files that still carry debt.
2. For each file, confirm the suspect. A real implicit machine is declared (step 2) and its readers migrated; a vocabulary that belongs to a remote or browser API is translated once, in the derive function; a deliberate exception takes `# state-literal-exempt: <reason>` (`// state-literal-exempt: <reason>` in JavaScript) on the line or in the comment block above.
3. Run `python scripts/conventions_ratchet.py --update-baseline` and commit the smaller file with the fix. `--allow-additions` is never part of a burn-down.
4. Stop at 0 findings and 0 machines without proof, then keep the three rules in `rules`: from there a new lifecycle comparison fails the gate.

## Updating later

Re-run `adopt_ratchets.py` from a newer scaffold checkout. Unchanged copies are skipped. A copy the scaffold has since changed reads as "differs" and is refused, so delete the old copy first, re-run, and review the diff. The `sha` in each `[vendored]` line records which scaffold commit it came from.

## Prompt for an outside agent

Paste this into a coding agent working in the target repo:

> Adopt the baseline-and-ratchet gate stages from the public repository `ferraroroberto/project-scaffolding` in this repo. Clone it to a temporary folder outside this repo and read its `docs/adopting-ratchets.md`, which is the whole procedure. Check the prerequisites table first and tell me which are missing. Run `python <clone>/scripts/tools/adopt_ratchets.py .` with the default set (add `--ratchets static` only if ruff is installed). Show me each printed exit code. Any exit other than 0 is a finding to report, never something to work around. Then run `python scripts/run_ratchets.py --tests <this repo's test command>`, show the summary, and wire that same command into this repo's existing check script or CI. Commit nothing until I have reviewed `scripts/`, `.fleet.toml` and the baseline files.
