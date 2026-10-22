# Static-analysis ratchet

`scripts/static_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It computes the current duplicated-code and unused-code findings, compares them with a committed baseline, and **fails only on a finding that is new**. Existing debt never blocks work; it cannot grow either.

Why a ratchet rather than a weekly audit: an audit re-finds the same duplication every run, and the fix lives in someone's head. A gate stage encodes the lesson in structure (the pstack principle "encode lessons in structure").

## What it checks

| Concern | Python | JS |
|---|---|---|
| Duplicate blocks | `jscpd` | `jscpd` (same run) |
| Unused imports / variables | `ruff check --select F401,F841` | not covered |

- **`jscpd` is pinned to an exact version** (`JSCPD_VERSION` in the script, currently `5.4.0`) and run through `npx --yes jscpd@<version>`. One tool covers both languages; a stdlib JS tokenizer (regex literals, template strings) would be a bug farm of its own. The cost is that **Node is a prerequisite for an adopter that opts in**. jscpd 5 ships its own `--baseline`; this script does not use it, so that duplicates and unused names share one baseline file, one key scheme and one set of modes.
- **ruff** is invoked as `python -m ruff` from the interpreter running the script, with `--select F401,F841`. That replaces the rule *selection* only: the repo's own ruff config (excludes, `per-file-ignores`) and inline `# noqa` still apply. An adopter that has no ruff in its venv gets a **not confirmed** exit, not a pass.
- **No JS unused-code check.** eslint would be a second Node tool plus per-repo config. JS is covered for duplication only.

## The three outcomes of a run

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (no new finding), or the stage is **not enabled** | continues |
| `1` | A new finding, or the baseline file is missing | fails |
| `2` | Bad `[static_ratchet]` table, unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: a detector could not run (no `npx`, no network on the first `npx`, ruff missing, timeout, unparseable output) | fails |

Exit 3 is its own state and is never folded into a pass: a tool that did not run has established nothing, so it must not read as "no new findings". Re-run once the prerequisite is fixed.

A baselined finding that has **disappeared** passes, and the run prints `N baselined finding(s) are gone -- run --update-baseline`. Failing instead would force the baseline edit into the same PR; the trade accepted here is that a stale entry lets the identical block regrow silently until someone shrinks the baseline, so shrink it in the PR that removes the debt.

## Keys and the baseline file

Keys carry no line numbers, so inserting code above a baselined finding does not re-flag it.

- **Duplicate:** `dup:<12 hex of sha1 of the whitespace-normalised fragment>:<fileA>|<fileB>` (paths sorted). The key is **strict**: editing the cloned block reads as one hit gone plus one new, so the author either removes the duplication or re-baselines it with the explicit flag, visible in review. A tolerant key (file pair only) would let a clone grow unnoticed. jscpd reports a clone as an ordered pair and the fragment hashed is the first file's; that order is deterministic for an unchanged tree.
- **Unused:** `unused:<rule>:<file>:<symbol>`, the symbol being the backtick-quoted name in ruff's message (falling back to the stripped source line).
- **Repeats** of one key (the same name unused twice in a file, the same block cloned twice between two files) get a `#<n>` suffix counting up from 2, in source-line order.

The baseline is committed, sorted JSON, one entry per line so diffs review cleanly:

```json
{
  "version": 1,
  "tools": {"jscpd": "5.4.0", "ruff": "0.15.21"},
  "entries": [
    {"key": "dup:e1d7fd9755a8:a.js|b.js", "files": ["a.js", "b.js"]},
    {"key": "unused:F401:b.py:os", "files": ["b.py"]}
  ]
}
```

`tools` records what produced the file and is informational only; it is rewritten whenever the baseline is. A ruff upgrade that changes what `F401`/`F841` report shows up as new or gone entries, and is handled like any other.

## Modes

```
python scripts/static_ratchet.py                                   # check (what the gate runs)
python scripts/static_ratchet.py --init                            # first baseline; refuses to overwrite
python scripts/static_ratchet.py --update-baseline                 # drop stale entries; exit 1 + write nothing if any finding is new
python scripts/static_ratchet.py --update-baseline --allow-additions   # the explicit flag that adds entries
```

Normal use can only shrink the baseline. Adding entries needs `--allow-additions` and shows in review as added lines in the baseline file.

## Adopting it (opt-in per repo)

Re-vendoring the script never breaks a repo that has not opted in: an absent `[static_ratchet]` table, or `enabled = false`, prints `static ratchet: not enabled` and exits 0 (declared, not inferred).

1. Vendor `scripts/static_ratchet.py` byte-for-byte (`/propagate-vendored static_ratchet`; manifest key `static_ratchet`), and declare it in the repo's `[vendored]` table.
2. Make sure `npx` (Node) and `ruff` (in the venv that runs the gate) are available; on CI, install both before the gate.
3. Add to the repo's own `.fleet.toml`:

   ```toml
   [static_ratchet]
   enabled    = true
   baseline   = ".static-ratchet-baseline.json"   # default
   min_lines  = 10                                  # default
   min_tokens = 100                                 # default
   exclude    = ["**/_vendored/**"]                 # added to the built-in set
   ```

   Always excluded: `node_modules`, `.venv`, `venv`, `.git`, `__pycache__`, `*.min.js`. `exclude` globs are anchored at the repo root; `**/` means "any depth". An adopter excludes `**/_vendored/**` because vendor-verbatim copies are duplicates by design and cannot be fixed downstream; the scaffold itself does not, since it owns them. `jscpd` also honours `.gitignore`.
4. Run `python scripts/static_ratchet.py --init` and commit the baseline.
5. Add a gate stage that runs `python scripts/static_ratchet.py` and fails on any non-zero exit. The scaffold's `scripts/verify-before-ship.ps1` places it after `ruff` and before `mypy`; a Python acceptance runner calls the same script. **Do not path-route it**: duplication needs the whole tree.
6. If the repo uses diff-proportionate e2e routing, add a `tier = "none"` rule for the baseline file to `.fleet.toml` `[e2e]` (the file at the repo root otherwise fails safe to the full browser suite) and a matching assertion in `tests/test_classify_e2e.py`.

The script spawns `npx` and ruff with `CREATE_NO_WINDOW`, derived locally (it is vendor-verbatim, so it cannot import `src/no_window.py`).

## Cost and tuning

Measured with a warm `npx` cache on the dev box, using the defaults above and ruff with its own config disregarded:

| Tree | Python + JS files scanned | jscpd | ruff `F401,F841` |
|---|---|---|---|
| this scaffold | ~85 | ~1.4 s | well under 1 s |
| a ~660-file adopter | 663 | ~14 s | ~1.4 s |
| a ~350-file adopter | 351 | ~21 s | ~1.9 s |

The first `npx` call downloads jscpd once. Treat roughly **30 s** as the line at which to revisit scope (`exclude` globs, raising `min_tokens`) rather than accept it. At the defaults the scaffold has no duplicates, so its own baseline is empty and the ratchet is exercised by the test suite; the two adopters measured above carry real debt (25 and 4 duplicate pairs, 36 and 144 unused names, counted without their own ruff config and with `_vendored/` excluded), which is what their first `--init` will record.

`min_lines = 10` / `min_tokens = 100` are the starting defaults, to be tuned against real output. Lowering them finds many more, smaller clones (at 6 lines / 50 tokens the scaffold alone reports eight).

## Limits

- Exact clones only (jscpd's default). Renamed-identifier and near-miss clones are not detected.
- Python and JS only (`--format python,javascript`).
- No JS unused import/variable detection.
- Needs Node; a machine without it gets exit 3 on the first run, by design.

## Tests

`tests/test_static_ratchet.py`: pure logic against captured jscpd/ruff JSON shapes (key stability when lines shift, new-versus-baselined, every mode), plus the acceptance criteria end to end on throwaway trees with the real jscpd and ruff. A missing prerequisite is a hard failure there, never `pytest.skip`.
