# Clean tree ratchet

`scripts/clean_tree_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It records `git status --porcelain`, runs the repo's declared start smoke once, records the status again, and **fails when the smoke added, modified or deleted a path** the committed baseline does not list. Existing debt never blocks work; it cannot grow either.

It enforces the decision "A clean pull plus restart is the whole update" in [architecture-decisions.md](architecture-decisions.md): starting, restarting and gating a repo leaves `git status` unchanged, with runtime output in ignored state dirs or the runtime data root. A start that regenerates a tracked file, appends to a script, or drops a log or cache next to the code turns the next `git pull --ff-only` into a conflict or a pile of untracked files. It is the decision's second check; the first, the [port host ratchet](port-host-ratchet.md), keeps machine-local values out of tracked scripts and code.

It has the shape of the other ratchets ([adopting-ratchets.md](adopting-ratchets.md)): an opt-in `.fleet.toml` table, a named rule, a committed baseline, the same flags, and exit 3 for "not confirmed". It is one stdlib-only file with no sibling.

## The rule

### `tree-write`

A path whose `git status` entry or content differs after the smoke:

- a new untracked file (`clean -> ??`), wherever it lands, as long as it is not ignored;
- a tracked file modified or deleted (`clean -> M`, `clean -> D`);
- a file already dirty before the run (work in progress) that the smoke changed again (`M -> M (content changed)`) or reverted (`M -> clean`).

Work in progress the smoke does not touch is not a hit: each listed file is hashed before and after, and only a difference counts. Ignored files are never listed by `git status`, so a log under an ignored `data/logs/` or a cache under `__pycache__/` is fine.

A smoke that writes the same bytes twice leaves no difference the second time. So a red run records the paths it flagged, as the smoke left them, in the repository's git dir (`clean-tree-ratchet-flagged.json`, per worktree, never in the work tree), and the next run still counts a recorded path that sits unchanged. Re-running a red gate stays red until the write is reverted; a pass clears the record.

## The smoke

The repo declares the argv of a short, disposable start in `smoke`. It runs from the repo root, with three placeholders filled in on every run:

- `{python}`: the interpreter running the ratchet (the repo's `.venv` in the gate);
- `{port}`: a free loopback port picked for this run, so the smoke never collides with the live instance or the tray;
- `{data_dir}`: a fresh temporary folder, removed afterwards. With `data_dir_env` set, the same folder is exported under that variable (`<APP>_DATA_DIR`), so a store resolved through the runtime data root lands there instead of the machine's real data.

Two kinds of smoke:

- **A server** (`ready_path` set): the smoke is started, `GET http://127.0.0.1:{port}<ready_path>` is polled until it answers 200 within `timeout_s`, the server keeps running `settle_s` more seconds so its start-up writes land, and its whole process tree is stopped (`taskkill /T` on Windows, the process group on POSIX). The argv must take `{port}`.
- **A command** (`ready_path` absent): the smoke runs to completion within `timeout_s` and must exit 0, for a repo whose start is a one-shot (a CLI, a pipeline's dry run, a restart script with a `--dry-run`).

Never point `smoke` at the live tray or its restart recipe: the check boots its own copy. The restart path of a tray app is covered by the same boot, since a restart is a stop plus this start.

## What is not checked

- **Writes at shutdown on Windows.** The server is stopped with `taskkill /F /T`, so a file an app writes only on a graceful exit is not observed there. POSIX sends `SIGTERM` first.
- **Writes outside the repo.** The machine's runtime data root, `%TEMP%` and the user profile are not the work tree; the runtime write ratchet and the runtime data convention cover where state goes.
- **Concurrent edits.** A file someone saves while the smoke runs is counted as the smoke's write. Re-run once the editor is idle.
- **Code paths the smoke never reaches.** Only what the boot does is observed; a write behind a button is the e2e suite's and the runtime write ratchet's to find.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | pass, or the table is absent or `enabled = false` |
| 1 | the smoke wrote a path beyond the baseline, the baseline is missing, or `--update-baseline` met an addition without `--allow-additions` |
| 2 | bad configuration (unknown key, no `smoke`, a server smoke without `{port}`, a value of the wrong type), a malformed baseline, `--init` over an existing baseline |
| 3 | **not confirmed**: `git` could not list the tree, a listed file cannot be read, or the smoke could not start, exited non-zero, died before it was ready, was not ready within `timeout_s`, or did not stop. The last lines of the smoke's output are printed. The gate fails on it |

## The baseline file

`.clean-tree-ratchet-baseline.json` (or `baseline`): a version and the sorted list of paths the smoke is known to write. It only shrinks on its own: a baselined path the smoke no longer writes prints a hint to run `--update-baseline`.

## Modes

Every mode runs the smoke.

- `python scripts/clean_tree_ratchet.py`: check against the baseline.
- `--init`: write the first baseline; never overwrites.
- `--update-baseline`: drop paths no longer written; refuses additions.
- `--update-baseline --allow-additions`: also record new paths, which shows in review as added lines.

## Adopting it (opt-in per repo)

```toml
[clean_tree_ratchet]
enabled      = true
baseline     = ".clean-tree-ratchet-baseline.json"   # default
smoke        = ["{python}", "-m", "app.webapp.serve", "--host", "127.0.0.1", "--port", "{port}"]  # required
ready_path   = "/healthz"          # optional; absent = the smoke runs to completion and must exit 0
timeout_s    = 60                  # default; the start (or run) deadline
settle_s     = 2                   # default; seconds the server keeps running after it is ready
data_dir_env = "MYAPP_DATA_DIR"    # optional; exported as the scratch `{data_dir}`
```

Then `scripts/tools/adopt_ratchets.py <target> --ratchets clean_tree` copies the script, records it under `[vendored]` and writes a commented `smoke` line; fill it in and run `--init`, or do the same by hand ([adopting-ratchets.md](adopting-ratchets.md)). Start from a clean tree, so the first baseline holds only what the smoke writes. The stage costs one app boot, a few seconds for a typical web app.

**A Streamlit app is a command smoke.** Its server answers `/_stcore/health` before any page has run, because a page runs only when a browser session connects, so a server smoke would observe Streamlit and none of the app's code. The scaffold enables the check for itself with a command smoke that runs the page once through `streamlit.testing.v1.AppTest`, with the app folder on `sys.path` as `streamlit run` puts it, and exits 1 on a page exception; its baseline is empty.

## Tests

`tests/ratchets/test_clean_tree_ratchet.py`: the porcelain parser and the before/after comparison; the config; every mode on a throwaway git repo with a one-line smoke script, covering a tracked write, an untracked and an ignored file, work in progress, a re-run of a red check, a server smoke that boots on its own port and data dir; the not-confirmed exits (a smoke that fails, hangs, dies or never answers, git that cannot list); and this repo's own adoption.
