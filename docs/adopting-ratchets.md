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
| conventions | `conventions_ratchet.py`, `conventions_readers.py` | choose `rules` | fast | | [conventions-ratchet.md](conventions-ratchet.md) |
| runtime write | `runtime_write_ratchet.py`, `runtime_write_resolve.py` | a test command, for the probe | fast | yes | [runtime-write-ratchet.md](runtime-write-ratchet.md) |
| usage track | `usage_track_ratchet.py`, `usage_track_scan.py` | a web UI; choose `rules` | fast | | [usage-track-ratchet.md](usage-track-ratchet.md) |

Two of the reference docs' terms belong to the owner's fleet and can be ignored here: `/propagate-vendored` (a private re-vendoring skill) and the e2e routing step (only for repos that use this scaffold's e2e router). `[vendored]` is **not** fleet-only: the ratchets read its `dest` entries to skip their own copies, so keep it.

## Steps

Clone this repository anywhere (it is the source; nothing is installed from it), then work in the target repo.

1. **Copy and initialise in one command:**

   ```
   python <scaffold>/scripts/adopt_ratchets.py <target> [--ratchets comment,structure,runtime_write]
   ```

   `--ratchets` takes a comma list, `recommended` (the default, the **Start** column) or `all`. For each ratchet it copies the script and siblings into `<target>/scripts/`, records every copy in `<target>/.fleet.toml` under `[vendored]`, appends a minimal `[<name>_ratchet]` table with `enabled = true`, copies the runner `run_ratchets.py`, and runs `--init` to write the first baseline, printing each exit code. Run it again at any time: an identical copy, an existing table and an existing baseline are left alone. A copy that differs from the scaffold's is **refused, never overwritten**, and the run exits 1 naming it.

   Without the script, do the same by hand: copy the files from the table, add `[<name>_ratchet]` with `enabled = true` to `.fleet.toml`, add a `[vendored]` line `<module> = { src = "scripts/<file>", dest = "scripts/<file>" }` per copied file, and run `python scripts/<name>_ratchet.py --init` for each.

2. **Review the baselines.** Each `.<name>-ratchet-baseline.json` at the repo root is today's debt, one entry per line. Adoption never requires cleaning it up first.

3. **Commit** `scripts/`, `.fleet.toml` and the baseline files together.

4. **Wire the gate.** Run the runner wherever the repo's checks run (a pre-push script, a Makefile target, CI):

   ```
   python scripts/run_ratchets.py --tests python -m pytest -q
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

## Updating later

Re-run `adopt_ratchets.py` from a newer scaffold checkout. Unchanged copies are skipped. A copy the scaffold has since changed reads as "differs" and is refused, so delete the old copy first, re-run, and review the diff. The `sha` in each `[vendored]` line records which scaffold commit it came from.

## Prompt for an outside agent

Paste this into a coding agent working in the target repo:

> Adopt the baseline-and-ratchet gate stages from the public repository `ferraroroberto/project-scaffolding` in this repo. Clone it to a temporary folder outside this repo and read its `docs/adopting-ratchets.md`, which is the whole procedure. Check the prerequisites table first and tell me which are missing. Run `python <clone>/scripts/adopt_ratchets.py .` with the default set (add `--ratchets static` only if ruff is installed). Show me each printed exit code. Any exit other than 0 is a finding to report, never something to work around. Then run `python scripts/run_ratchets.py --tests <this repo's test command>`, show the summary, and wire that same command into this repo's existing check script or CI. Commit nothing until I have reviewed `scripts/`, `.fleet.toml` and the baseline files.
