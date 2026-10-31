# Runtime write ratchet

`scripts/runtime_write_ratchet.py` keeps runtime output (logs, run records, caches, databases) out of tracked code folders. The layout reserves `data/` for runtime input and output ([repo layout](repo-layout.md)), and a long-lived app's state belongs under the machine's runtime root (`src/runtime_data.py`). Nothing else enforced it, so a process could still write `run.log` next to the module that produced it. This stage has two halves:

- a **static check**, a baseline-and-ratchet gate stage that finds every write target in the repo's Python source and resolves where it points;
- a **runtime probe** that brackets the test stages and fails on any file the run left under a code folder.

It has the same shape as the [conventions ratchet](conventions-ratchet.md): an opt-in `.fleet.toml` table, a committed baseline, the same flags, and exit 3 for "not confirmed". It is stdlib-only, in two files: the ratchet itself and its path resolver, `scripts/runtime_write_resolve.py`, which it loads from beside itself. With the resolver missing it exits 3.

## The static check

### Write targets

A write target is the path argument of:

- `open()`, `io.open()` or `codecs.open()` with a writing mode (`w`, `a`, `x` or `+`); a mode the source does not spell counts as writing;
- `<path>.open(mode)` with a literal writing mode;
- `<path>.write_text()`, `.write_bytes()`, `.touch()`, `.mkdir()` (not when the first argument is a string, as in `ftp.mkdir("dir")`, because a `pathlib` method never takes one);
- `os.mkdir()`, `os.makedirs()`, and the destination of `shutil.copy`, `copy2`, `copyfile`, `copytree` and `move`;
- `logging.FileHandler`, `RotatingFileHandler`, `TimedRotatingFileHandler`, `WatchedFileHandler`, and `logging.basicConfig(filename=...)`;
- `sqlite3.connect()`, except `":memory:"`.

### Resolution

The check follows the path expression through what the source spells out: string literals, `__file__`, `.parent`, `.parents[n]`, `/`, `os.path.join`, `os.path.dirname`, `Path(...)`, `.resolve()`, `.joinpath()`, an f-string whose head is a path and whose rest is literal text, and a name assigned exactly once in the enclosing function or module. A relative literal is read from the repo root, which is where the fleet runs every entry point. Each target ends in one of three states:

| State | Example | Counted as |
|---|---|---|
| Under a code folder | `Path(__file__).parent / "run.log"` in `src/` | `code-folder` |
| Anywhere else | `ROOT / "data" / "logs"`, an absolute path, `tempfile.mkdtemp()`, `Path.home()`, `runtime_db_path(...)` | not counted |
| Not resolvable | a function parameter, `self.path`, `os.environ["OUT"]`, a name assigned twice | `unresolved` |

Code folders default to `src`, `app`, `scripts`, `hooks` and `skills`. A file name the source does not spell (`P / name`) stays under its folder, so `Path(__file__).parent / name` is still a `code-folder` hit.

**Unresolved is unknown, never clean.** A new `code-folder` target fails the gate (exit 1). A new `unresolved` target is exit 3, NOT CONFIRMED: the check could not tell where it writes. Resolve it in one of three ways:

- make the path resolvable, for example build it from the module's own constants rather than a parameter;
- name the adopter's own runtime-root helper in `safe_calls`, so calls to it count as outside the tree;
- mark the call `# runtime-write-exempt: <reason>`, such as "path comes from runtime_db_path in the caller".

Baselined `unresolved` targets do not fail the gate, but every pass prints how many remain as unknown.

### Exempting one call

A deliberate write keeps a reasoned marker on one of its own lines, or in the comment block directly above it:

```python
# runtime-write-exempt: generated source, committed on purpose
(Path(__file__).parent / "_catalog.py").write_text(text)
```

A bare `# runtime-write-exempt` with no reason exempts nothing.

### Scope

Every `.py` file git lists (tracked, or untracked and not ignored), except:

- test modules (under `tests/` or `test/`, `test_*.py`, `*_test.py`, `conftest.py`): they write under pytest's `tmp_path`, and the probe covers what a test run actually leaves behind;
- files under the repo's `[vendored]` destinations: a vendored copy's debt belongs to the repo it came from;
- the `exclude` globs, plus `node_modules`, `.venv` and `venv` anywhere.

### Limits

The check is static. It does not follow a path across a function call, through a class attribute, or into another module, so those count as `unresolved` instead of being guessed. A process whose working directory is not the repo root resolves relative literals somewhere else. The probe is the backstop for both.

## The runtime probe

The gate takes a snapshot before the unit tests and probes after the last test stage:

```powershell
& $py scripts/runtime_write_ratchet.py --snapshot $runtimeSnapshot   # before pytest
& $py scripts/runtime_write_ratchet.py --probe $runtimeSnapshot      # after e2e + shot baseline
```

Both list the untracked **and ignored** files under the code folders (`git status --porcelain --ignored --untracked-files=all -- <folders>`). Ignored files count because a log is usually gitignored, and still sits in the wrong place. The probe fails (exit 1) on any file the run added, leaving out `__pycache__`, `*.pyc`, `*.pyo`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`, `node_modules` and the `exclude` globs. A passing probe deletes its snapshot. A snapshot that is missing or unreadable, or a `git` that cannot list the tree, is exit 3. The probe only sees files the run added, so a file left by an earlier run is the static check's job.

## Configuration

```toml
[runtime_write_ratchet]
enabled      = true
baseline     = ".runtime-write-ratchet-baseline.json"       # default
code_folders = ["src", "app", "scripts", "hooks", "skills"]  # default; top-level folders only
exclude      = ["src/generated/**"]                          # globs; never scanned or probed
safe_calls   = ["state_dir"]                                 # calls that return a path outside the tree
```

An absent table, or `enabled = false`, skips both halves with a line saying so. An unknown key, a nested code folder or an empty list is a configuration error (exit 2), never a quiet partial run.

## Enabling it in a repo with hits today

1. Copy `scripts/runtime_write_ratchet.py` and `scripts/runtime_write_resolve.py` byte-for-byte and declare both in the repo's `[vendored]` table (manifest keys `runtime_write_ratchet` and `runtime_write_resolve`).
2. Add the `[runtime_write_ratchet]` table with `enabled = true`.
3. Record today's hits rather than fixing them first: `python scripts/runtime_write_ratchet.py --init`. Commit the baseline in the same PR.
4. Wire the gate: the check after the conventions ratchet, `--snapshot` before the first pytest stage, `--probe` after the last test stage. This scaffold's `scripts/verify-before-ship.ps1` is the reference.
5. If the repo routes e2e through `.fleet.toml` `[e2e]`, add a `none` rule for the baseline file.

From then on, every write that moves to `data/` or the runtime root shrinks the baseline: run `--update-baseline`. Raising it takes `--update-baseline --allow-additions`, which shows up in review.

## Exit codes

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (no count above the baseline; the probe found nothing new), or the stage is **not enabled** | continues |
| `1` | A file's `code-folder` count rose, the probe found a new file, or the baseline is missing | fails |
| `2` | Bad `[runtime_write_ratchet]` table, unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: a new `unresolved` target, `git` unusable, a tracked `.py` file that cannot be read or does not parse, or an unreadable snapshot | fails |

## The baseline file

Committed, sorted JSON, one source file per line, keyed by repo-relative path, counting hits per kind:

```json
{
  "version": 1,
  "entries": [
    {"key": "src/usage_log.py", "counts": {"unresolved": 3}}
  ]
}
```

No line numbers, so moving code inside a file does not churn the baseline.
