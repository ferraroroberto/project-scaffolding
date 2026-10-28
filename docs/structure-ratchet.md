# Structure ratchet

`scripts/structure_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It enforces the [repo layout](repo-layout.md) with five checks: **file size**, **function length**, **flat directories**, the **layer contract** and the **root layout**. The first four fail when a new offender appears, or when a baselined one grows; existing offenders never block work, and they cannot grow either. A **near-limit band** holds the files and functions just under their limits to a shrink-only count, so a split that stops at 990 lines fails the same way. The root layout is never baselined.

It reuses the shape of the [docs ratchet](docs-ratchet.md) and the [comment ratchet](comment-ratchet.md): an opt-in `.fleet.toml` table, a committed baseline, the same flags, and exit 3 for "not confirmed". It is its own script, and not a check inside the [static-analysis ratchet](static-ratchet.md), because that one needs Node and ruff; this one is stdlib-only and runs anywhere Python 3.11 does.

## The checks

| Check | Rule (defaults) | Baseline key → field |
|---|---|---|
| File size | A file over **1,000 lines** fails when new; a baselined one may not grow past its count | `size:<path>` → `lines` |
| Function length | A Python or JS function over **100 lines** fails when new; a baselined one may not grow | `fn:<path>:<qualname>` → `lines` |
| Flat directory | A directory holding more than **40 modules** fails when new; a baselined one may not gain a module | `dir:<path>` → `modules` |
| Layer contract | A Python file under `src/` that imports the `app` package fails | `layer:<path>:<module>` → `imports` |
| Unmeasured | A JS function whose end the scanner cannot find is recorded, never passed | `unmeasured:<path>` → `functions` |
| Near-limit band | The count of files at **900–1,000 lines** and of functions at **90–100 lines** may not rise | `band` → `files`, `functions` |
| Root layout | A required root folder with no tracked file fails; so does a tracked root folder the declared `shape` and `extra_roots` do not list | none: not baselined |

Tests get the same limits as code. Each failure message names the rule, the limit, where the code goes instead, and the section of `docs/repo-layout.md` that says so:

```
structure ratchet: 1 finding(s) above the baseline:
  [flat directory] src/ has 107 modules (limit 40); baseline 106
      put the new module in a domain subpackage, src/<domain>/. See project-scaffolding docs/repo-layout.md#flat-directory
```

The anchors (`#file-size`, `#function-length`, `#flat-directory`, `#layer-contract`, and one per shape id for the root layout) are pinned by a test, so renaming a heading in `repo-layout.md` fails until the script follows.

## What is measured

**File size** counts lines as an editor shows them (a missing final newline still ends a line; CRLF counts once) in `.py`, `.js`, `.mjs`, `.ts`, `.css`, `.html`, `.ps1` and `.sql` files.

**Python functions** come from `ast`: from the `def` line to `end_lineno`, decorators excluded. Every function is measured, nested ones and methods included, under a dotted name (`Class.method`, `outer.inner`). A nested function also counts inside its outer function, so the outer one is held as a whole.

**JS functions** (`.js`, `.mjs`) come from a single tokenizing pass with a brace stack. Strings, template literals (with nested `${}` code), comments and regex literals never move the stack; a `/` is read as a regex where an expression may start, and as a division after a value, `)` or `]`. A `{` opens a function body after:

- `function name(...)`, `function (...)`, `async` and generator forms;
- `name(...)` at the start of a class or object member, with `static`, `async`, `get`, `set`, `*` or `#` before it;
- `=>` (an arrow function with a block body).

A function expression takes the name it is bound to (`const mountHome = async () => {`, `save: function () {`), `default` for `export default function`, and otherwise `<anonymous>`. Methods are qualified by their class. So a view's `mountView()` closure is measured as a whole, and each helper inside it as `mountView.helper`.

**Same-named functions** in one file rank by length: `name` is the longest, then `name~2`, and so on. Only functions over the limit take part, so adding a short `<anonymous>` callback, or reordering, never renames a recorded one. No key holds a line number, so code inserted above a function never re-flags it.

**A directory's modules** are the `.py`, `.js`, `.mjs` and `.css` files directly in it, `__init__.py` aside. Subfolders are counted as their own directories. The repo root is `dir:.`.

**The layer contract** reads `import` and `from ... import` statements anywhere in a file (a deferred import inside a function counts). `import app`, `import app.web` and `from app.x import y` match the `app` package; `import application`, `from src.app import x` and relative imports do not. Each pair in `layers` is a lower and an upper root: files under the lower root may not import the package at the upper root (a root with a subfolder is the dotted package, so `app.web` for the `web` folder under `app`). The default is `[["src", "app"]]`; `layers = []` turns the check off.

### Root layout

The check reads the top-level `shape` and `extra_roots` keys of the repo's own `.fleet.toml` (not the `[structure_ratchet]` table) and the root folders from the same file list as the other checks (`git ls-files --cached --others --exclude-standard`), so a new untracked folder counts as a root and an ignored one does not. A shape's preset lives in the script (`SHAPES`), which keeps the script vendor-verbatim; this table is the same data, and a test compares the two.

| `shape` | Required root folders | Also allowed | `layers` default |
|---|---|---|---|
| `webapp-tray` | `app`, `src`, `tests`, `docs` | `scripts`, `data`, `brand`, `assets`, `config` | `[["src", "app"]]` |
| `streamlit` | `app`, `src`, `tests` | `scripts`, `data`, `brand` | `[["src", "app"]]` |
| `pipeline-cli` | `tests` | `src`, `common`, `scripts`, `config`, `data` | none |
| `skills-governance` | `skills`, `tests` | `hooks`, `scripts`, `architecture` | none |
| `node` | `src` | `test`, `scripts` | none |
| `static-site` | none | `css`, `js`, `assets`, `games` | none |
| `agent-workspace` | none | `scripts` | none |
| `service` | `src`, `tests`, `app_web`, `tray` | `scripts`, `config`, `launchers`, `assets` | none |

`docs`, `.github` and every hidden folder are allowed in every shape. A set is required only where every repo of the shape has the folder, because `extra_roots` can add a folder but never waive one. A multi-tool `pipeline-cli` repo declares each tool package in `extra_roots`.

- **A required folder with no tracked file** fails by name; the fix is to add it, or to correct `shape`.
- **A tracked root folder** that is in neither the preset nor `extra_roots` fails by name. The message names the shape, the folder and both fixes: move the code into a listed folder, or declare the folder in `extra_roots` with a line in the repo's `docs/layout.md`.
- **A declared exception is data**, not debt: nothing about the layout enters the baseline, `--init` and `--update-baseline` never touch it, and removing a folder from `extra_roots` fails the next run if the folder is still tracked.
- **No `shape`** prints `layout check not applicable` and skips that one check; the other four still run, so re-vendoring never breaks a repo that has not declared one. This is a declared skip, never a pass: the PASS line names the shape only when the layout was checked.
- **An unknown `shape`** is exit 3, not a skip: the layout cannot be checked against a tree that does not exist. A `shape` that is not a string, or an `extra_roots` that is not a list of single folder names, is exit 2.
- **`layers`**: when the table does not set it, a shape with a layer pair supplies it (`src` never imports `app` for `webapp-tray` and `streamlit`); a repo with no `shape` keeps the default pair.

### Limits

- **JS only, among the script languages.** TypeScript files are measured for size but not for function length; type annotations would mislead the brace matcher. Inline `<script>` blocks in HTML are not measured.
- **An arrow function with an expression body** (`items.map(x => x.id)`) is not a function to the scanner: it has no braces. It counts inside its enclosing function.
- **A statement call followed by a block on the next line** (`run(x)` then `{`) reads as a method. Real code almost never has it.
- **An anonymous function's key depends on its place in the ranking.** Two long anonymous callbacks in one function swap names when one outgrows the other. Both are still held.
- **Renaming or moving a file** reads as a new offender under the new key, resolved with the explicit `--allow-additions`.

## Near-limit band

A file at 990 lines blocks the next change just as a file at 1,001 does, so a split that stops just under a limit has only moved the problem. The band is every file and every function whose length is at or above `near_limit_ratio` of its limit and not over it: with the defaults, files of 900–1,000 lines and functions of 90–100 lines. Over-limit code is not in the band; it already has its own entry.

- **Counted per repo, shrink-only.** The baseline records two counts, files in the band and functions in the band. A change that brings a new file or function into the band fails unless another one leaves it in the same change. A file that grows inside the band, or a split that lands a half in it, fails the same way.
- **Existing members are never failed retroactively.** `--init` records today's band, and so does the first `--update-baseline` after a re-vendor (see below).
- **The split target is 75% of the limit**: about 750-line files and 75-line functions, so the result starts well clear of the band instead of being born in it. The failure lists every member of the band, the split target, and the `docs/repo-layout.md` section for the limit:

  ```
  structure ratchet: 1 finding(s) above the baseline:
    [near-limit file] 4 file(s) at 900-1,000 lines, the near-limit band (90% of the limit); baseline 3
        - app/webapp/views.py: 958 lines
        - ...
        split it to about 750 lines, moving code into a new module beside it named for what it does, so it lands clear of the band. See project-scaffolding docs/repo-layout.md#file-size
  ```

- **One leaving the band** passes with the below-the-baseline hint; `--update-baseline` lowers the count. Raising it takes `--allow-additions`, like any entry.
- **`near_limit_ratio`** (default `0.9`, a number strictly between 0 and 1) sets where the band starts for both files and functions; the band's top is always the limit itself. The lowest member is the limit times the ratio, rounded up.

**A baseline written before the band existed** has no `band` object. It loads unchanged: the check passes on the band and prints that the band is not recorded yet, so no adopter fails on the day it re-vendors. The next `--update-baseline` (no `--allow-additions` needed) records today's counts, and from then on they may only shrink.

## Scope

Files come from `git ls-files --cached --others --exclude-standard`, spawned with `GIT_OPTIONAL_LOCKS=0`, so a new untracked file is measured before it is added and an ignored one is not. Always excluded: `node_modules`, `.venv`, `venv`, files whose first five lines contain `DO NOT EDIT` or `@generated` (case-sensitive), `exclude` globs, and every `dest` in the adopter's own `[vendored]` table. Excluded files count toward no check, the directory count included. Tracked files deleted from the working tree are not measured.

## Exit codes

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (nothing new and nothing above its baseline), or the stage is **not enabled** | continues |
| `1` | A new offender, a baselined one that grew, a near-limit band count that rose, or the baseline file is missing | fails |
| `2` | Bad `[structure_ratchet]` table, unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: `git` unusable, a file that cannot be read, a Python file that does not parse, or a `shape` that is not in the table above. The message names the file or the value | fails |

Exit 3 is its own state and never folded into a pass: a file that cannot be measured might hold any finding.

## The baseline file

Committed, sorted JSON, one entry per line, with no line numbers:

```json
{
  "version": 1,
  "band": {"files": 6, "functions": 31},
  "entries": [
    {"key": "dir:tests", "modules": 52},
    {"key": "fn:app/webapp/static/composer.js:mountComposer", "lines": 500},
    {"key": "size:tests/e2e/test_components.py", "lines": 1496}
  ]
}
```

Each entry records the count at the last baseline write. A check fails when the count rises above it; a count that falls passes with a hint, and the next `--update-baseline` lowers the entry, or drops it once the offender is back under the limit. Raising the limits in the table drops the entries under the new limit the same way. The `band` object holds the two near-limit counts and follows the same rules; a baseline without it is one written before the band existed, never an error.

## Modes

```
python scripts/structure_ratchet.py                                     # check (what the gate runs)
python scripts/structure_ratchet.py --init                              # first baseline; refuses to overwrite
python scripts/structure_ratchet.py --update-baseline                   # lower or drop entries; exit 1 + write nothing if anything rose
python scripts/structure_ratchet.py --update-baseline --allow-additions # the explicit flag that raises or adds entries
```

The fix for a failure is to put the code where the layout says. `--allow-additions` exists for the reviewed exception, and shows in the baseline diff.

## Adopting it (opt-in per repo)

Re-vendoring the script never breaks a repo that has not opted in: an absent `[structure_ratchet]` table, or `enabled = false`, prints `structure ratchet: not enabled` and exits 0 (declared, not inferred).

1. Vendor `scripts/structure_ratchet.py` byte-for-byte (`/propagate-vendored structure_ratchet`; manifest key `structure_ratchet`) and declare it in the repo's `[vendored]` table. It is stdlib-only and needs Python 3.11+ (`tomllib`).
2. Add to the repo's own `.fleet.toml`:

   ```toml
   [structure_ratchet]
   enabled            = true
   baseline           = ".structure-ratchet-baseline.json"   # default
   max_file_lines     = 1000                                 # default
   max_function_lines = 100                                  # default
   max_dir_modules    = 40                                   # default
   near_limit_ratio   = 0.9                                  # default; the near-limit band starts here
   layers             = [["src", "app"]]                     # default; [] turns the check off
   exclude            = ["tests/fixtures/**"]                # globs; default none
   ```

   and, at the top level of the same file, the layout check's two keys (leave `shape` out to skip that check until the repo is ready):

   ```toml
   shape       = "streamlit"                                     # one id from the table above
   extra_roots = ["custom_components"]                           # root folders the shape does not list; default none
   ```

3. Run `python scripts/structure_ratchet.py --init` and commit the baseline. Review it: the first baseline records every existing offender. **Adoption never requires the split first.** Then declare `shape` and run the check once: a root folder it lists as drift is either moved or declared in `extra_roots`.
4. Add a gate stage that runs `python scripts/structure_ratchet.py` and fails on any non-zero exit. The scaffold's `scripts/verify-before-ship.ps1` places it after the docs ratchet and before `mypy`. **Do not path-route it**: a directory count needs the whole tree.
5. If the repo uses diff-proportionate e2e routing, add a `tier = "none"` rule for the baseline file to `.fleet.toml` `[e2e]` and a matching assertion in `tests/test_classify_e2e.py`.

The script spawns `git` with `CREATE_NO_WINDOW`, derived locally (it is vendor-verbatim, so it cannot import `src/no_window.py`). For the same reason it repeats the config, glob and `git ls-files` helpers of the other vendored ratchets instead of importing them; the scaffold's static-ratchet baseline carries those duplicate pairs because it owns the sources.

## Cost

One pass reads every in-scope file once and parses each Python file once; the AST walk visits statements only, and imports are read only under a layer's lower root. Measured: about half a second on this scaffold, and about 1.6 s on a throwaway clone of the largest fleet repo (836 tracked files), whose first baseline is 27 files, 70 functions and 4 directories with no layer import. No file in two of the largest fleet repos came out unmeasured.

## Tests

`tests/ratchets/test_structure_ratchet.py`: Python and JS spans on fixture strings (nesting, methods, arrows, a closure of several hundred lines, braces inside strings, templates, comments and regexes, an unterminated function), the layer match and what it must not match, directory counts, and the full ratchet matrix per check on throwaway git repos (a new offender fails, a baselined one passes at its size, growth fails, a shrink lowers the entry, `--update-baseline` never adds, `--allow-additions` adds), the failure message per rule, scope and vendored exclusion, and every exit code. A missing prerequisite is a hard failure, never `pytest.skip`. Root-layout tests cover each shape's required set, an undeclared root, a declared extra root, no `shape` and an unknown `shape`. The self-adoption tests pin the gate order, the catalog entry, the anchors and limits in `docs/repo-layout.md`, and that the presets in the script match the table above.

`tests/ratchets/test_structure_ratchet_band.py`: the near-limit band on throwaway git repos: the ratio's default, range and rounding; a new file or function in the band fails with its split target; a split that lands just under the limit fails; one leaving lets `--update-baseline` lower the count; one entering while another leaves passes; `--allow-additions` raises it; a baseline from before the band passes, then is recorded and ratcheted; a malformed `band` is a baseline error; and the scaffold records its own band.
