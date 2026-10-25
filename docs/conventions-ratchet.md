# Conventions ratchet

`scripts/conventions_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It holds a small set of fleet conventions as stdlib `ast` rules, counts each enabled rule's hits per tracked Python file, and **fails when a file's count for a rule rises** above the committed baseline. Existing debt never blocks work; it cannot grow either.

Before it, each convention was guarded by a one-off test in whichever repo last hit the bug: a no-window spawn test here, a constant-time compare test in one app, a raw-git check in another. This stage is the one vendored copy of those guards. A repo that adopts it can delete its local duplicate once the matching rule is enabled and its baseline is committed.

It reuses the shape of the [dead code ratchet](dead-code-ratchet.md): an opt-in `.fleet.toml` table, a committed baseline, the same flags, and exit 3 for "not confirmed". It is stdlib-only and imports nothing it scans.

## The rules

Each rule is opted into by name in `rules`. A rule that needs the repo's own helper refuses to run until the helper is declared, so a repo without one is never flagged for not using it.

**Test modules** (any file under a `tests/` or `test/` folder, `test_*.py`, `*_test.py`, `conftest.py`) are held to `no-window` only. Fixtures legitimately spell drive paths, raw compares and raw git calls.

### `no-window`

> **Subprocess spawns must suppress the console window (Windows)** — every `subprocess` spawn of an external executable passes `creationflags=subprocess.CREATE_NO_WINDOW` on Windows unless the window is meant to be visible; never combine it with `DETACHED_PROCESS`; repos with 3+ call sites use one `NO_WINDOW` helper.

A hit is a call to `subprocess.run`, `Popen`, `call`, `check_call`, `check_output`, `asyncio.create_subprocess_exec` or `create_subprocess_shell`, through any import alias, with no `creationflags=` keyword. It is not reported when:

- the call passes `**kwargs`, which may carry the flag (a miss, never a guess);
- it sits in a branch that never runs on Windows: the body of `if sys.platform == "darwin"`, `if os.name != "nt"`, `if platform.system() == "Linux"`, `if sys.platform.startswith("linux")`, the `else` of a Windows test, or anything after `if <Windows>: ... return` in the same block.

A POSIX-only helper that no branch marks (a macOS installer function), and a console that is meant to be visible (a foreground dev runner), take the exempt marker.

### `logging-not-print`

> **Logging:** the language's logging facility (Python: `logging`, not `print()`).

A hit is a builtin `print(...)` in a file under `print_paths` (default `app/` and `src/`). It is not reported when:

- the module is a command-line entry point: it has an `if __name__ == "__main__":` block, imports `argparse`, `click`, `typer`, `fire` or `optparse`, is named `cli.py` or `__main__.py`, or sits under a `cli/` folder. A CLI prints its output by design;
- the call writes to a file (`file=` anything but `sys.stdout` or `sys.stderr`);
- the module binds its own `print` (`from rich import print`, a local `def print`).

The CLI rule is what makes this one honest. Without it, the fleet had 289 hits, every one in a command-line module (tables, JSON dumps, usage lines), where `print` is the product and not a log line. With it the fleet has none, so the rule now guards against a new diagnostic `print` in library code. The price: a diagnostic `print` inside a CLI module is not seen.

### `no-drive-path`

> **No hardcoded paths or credentials.**

A hit is a string literal (f-string parts included, docstrings excluded) that **starts** with a Windows drive letter and separator: `E:/data`, `r"D:\out"`. It is not reported for:

- the system folders `?:\Windows`, `?:\Program Files`, `?:\Program Files (x86)` and `?:\ProgramData`, because the instructions themselves mandate absolute system binaries such as `C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`;
- a bare drive root (`"C:\\"`), which anchors a filesystem walk rather than naming a data location;
- a drive in the middle of a string (`"see E:/x"`, a URL).

### `secret-compare`

There is **no global-instruction line** for this rule. It enforces a convention the repo declares by naming its helper: every constant-time comparison goes through one function, which compares bytes rather than `str`, because `hmac.compare_digest` raises `TypeError` on a non-ASCII `str`. Several fleet repos keep a local test for exactly this.

A hit is a call to `hmac.compare_digest` or `secrets.compare_digest`, through any import alias, outside the files listed in `secret_helpers`. The rule refuses to run without `secret_helpers`.

### `git-wrapper`

> Every `git` spawn goes through the tier's `run_git`, and any repo reading git state fleet-wide needs that static gate over its own tree.

A hit is a spawn (the same calls as `no-window`) whose program is literally `git` or `git.exe`: the first item of a list or tuple argument, or the first word of a string command, any directory stripped. It is not reported in the files listed in `git_wrappers`, and the rule refuses to run without `git_wrappers`. A program computed at run time is not seen.

### Exempting one call

A call that must break a rule keeps a reasoned marker on one of its own lines, or in the comment block directly above it:

```python
# no-window-exempt: foreground dev runner; the console is the UI
return subprocess.run(cmd, cwd=str(PROJECT_ROOT)).returncode
```

The marker names one rule (`<rule>-exempt`) and needs text after it. A bare `# no-window-exempt` exempts nothing, and a marker for another rule does not cover this one. This is the same marker the scaffold's own `tests/test_no_window_convention.py` reads.

## Scope

Every tracked `.py` file, except:

- files under the repo's `[vendored]` destinations: a vendored copy's debt belongs to the repo it came from;
- the `exclude` globs, plus `node_modules`, `.venv` and `venv` anywhere.

Only Python source is read. A baseline (this stage's or any other ratchet's) is JSON and is never read as a hit or as evidence about one.

## Exit codes

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (no rule count above the baseline), or the stage is **not enabled** | continues |
| `1` | A file's count for a rule rose, or the baseline file is missing | fails |
| `2` | Bad `[conventions_ratchet]` table (unknown key or rule, no rules, a helper rule with no helper), unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: `git` unusable, or a tracked `.py` file that cannot be read or does not parse. The message names the file and line | fails |

Exit 3 is its own state and never folded into a pass: a file the scanner cannot parse may hold a violation, so skipping it would report a clean tree it never saw.

## The baseline file

Committed, sorted JSON, one source file per line, keyed by repo-relative path, counting hits per rule:

```json
{
  "version": 1,
  "entries": [
    {"key": "src/runtime_data.py", "counts": {"no-drive-path": 1}}
  ]
}
```

There are no line numbers, so edits elsewhere in a file never churn it. Counting per file and rule means a fix and a new violation of the same rule in the same file cancel out; that is the accepted trade for a baseline that does not churn. Renaming a file that carries debt reads as a new file, resolved with `--allow-additions`.

## Modes

```
python scripts/conventions_ratchet.py                                   # check (what the gate runs)
python scripts/conventions_ratchet.py --init                            # first baseline; refuses to overwrite
python scripts/conventions_ratchet.py --update-baseline                 # drop hits now gone; exit 1 + write nothing if anything was added
python scripts/conventions_ratchet.py --update-baseline --allow-additions   # the explicit flag that adds entries
```

A failing check prints every hit of the risen rule in the file, as `<path>:<line>: [<rule>] <message>`, under a `<path>: [<rule>] <n> hit(s), baseline <m>:` header: without line numbers in the baseline, the stage cannot tell which one is new.

## Adopting it (opt-in per repo)

Re-vendoring the script never breaks a repo that has not opted in: an absent `[conventions_ratchet]` table, or `enabled = false`, prints `conventions ratchet: not enabled` and exits 0 (declared, not inferred).

1. Vendor `scripts/conventions_ratchet.py` byte-for-byte (`/propagate-vendored conventions_ratchet`; manifest key `conventions_ratchet`) and declare it in the repo's `[vendored]` table. It needs Python 3.11+ (`tomllib`) and `git`; it parses code with the running interpreter's grammar, so run it with the interpreter the project targets.
2. Add to the repo's own `.fleet.toml`, enabling only the rules that apply:

   ```toml
   [conventions_ratchet]
   enabled        = true
   baseline       = ".conventions-ratchet-baseline.json"  # default
   rules          = ["no-window", "no-drive-path", "secret-compare", "git-wrapper"]
   exclude        = ["src/generated/**"]                    # globs; never scanned
   print_paths    = ["app/", "src/"]                        # logging-not-print scope (default)
   secret_helpers = ["src/secret_compare.py"]               # required by secret-compare
   git_wrappers   = ["src/git_run.py"]                      # required by git-wrapper
   ```

   A Windows-only or cross-platform app enables `no-window`; a Linux-only service does not. `secret-compare` and `git-wrapper` only make sense once the repo has the helper.
3. Declare every vendored copy in `[vendored]` first (an undeclared copy of a scaffold ratchet reports its own `git` spawn as yours). Then run `python scripts/conventions_ratchet.py --init`, review the baseline, and commit it. Each entry is either a violation worth a follow-up fix or a legitimate exception worth an exempt marker. **Adoption never requires the fixes first.**
4. Add a gate stage that runs `python scripts/conventions_ratchet.py` and fails on any non-zero exit. The scaffold's `scripts/verify-before-ship.ps1` places it after the dead code ratchet and before `mypy`. **Do not path-route it**: it is cheap, and a rule added to `rules` must see the whole tree.
5. Delete the repo's local guard test for a rule once that rule is enabled here with a baseline of zero for it; keep the test while the baseline still carries debt, because the test is zero-tolerance and the ratchet is not.
6. If the repo uses diff-proportionate e2e routing, add a `tier = "none"` rule for the baseline file to `.fleet.toml` `[e2e]` and a matching assertion in `tests/test_classify_e2e.py`.

The script spawns `git` with `CREATE_NO_WINDOW`, derived locally (it is vendor-verbatim, so it cannot import `src/no_window.py`), and with `GIT_OPTIONAL_LOCKS=0`. It shares its config, glob and baseline helpers with the sibling ratchets by copy, because each vendored file must be self-contained.

## Adding a rule from a promotion issue

A cleanup lane that fixes a recurring audit bucket must ship one structural check, and that check lands in the one repo the lane worked on. When the lane declares the check generalizable, the cleanup orchestrator files an issue in this repo labelled `structural-promotion`. The issue is keyed by a hidden `<!-- structural-promotion: name=<rule-name> -->` marker, so the same rule written in a second repo adds a comment to the existing issue instead of opening a new one. A closed issue is never reopened: if it was closed as completed, the rule already exists and that repo adopts it.

A promotion issue names the rule, plus the repo, pull request and check path for every repo that wrote it. It holds no code excerpts and no personal data. It ends in one of three ways: a new entry in this stage's rules, a new ratchet, or a not-planned close that says why.

### Evidence before building

1. **A written convention.** Quote the line the rule enforces from the global instructions or this scaffold's `CLAUDE.md`, or name the repo-declared helper it routes calls through (as `secret-compare` does). A check with no written convention behind it is a repo-specific test: close the issue as not planned and say so.
2. **A fleet dry run.** Run the candidate rule read-only over every fleet checkout and report it as a row of the table under "Cost and measured hit rate": hits, repos, how many were checked by hand, how many were real. The rule ships only when the false positives left are a kind an exempt marker covers. A kind that would need a marker on most of its hits becomes an exception in the rule, or the proposal closes.
3. **The right home.** Use the table below.
4. **A test pair.** Add a seeded violation that fails by rule name, and the compliant form that passes, to `tests/ratchets/test_conventions_ratchet.py`. For a new ratchet, add the same pair to that ratchet's own test module.

| The check… | Lands as |
|---|---|
| is a pattern in Python source that stdlib `ast` can see without importing the scanned code | a new rule in this stage |
| is already reported by `ruff` or `jscpd` | a rule family in the [static ratchet](static-ratchet.md) |
| reads non-Python files, or measures a size rather than matching a pattern | a new ratchet with the same contract: opt-in table, committed baseline, shrink-only `--update-baseline`, visible `--allow-additions`, exit 3 for not confirmed |

### Landing it

A new rule is off until a repo names it in `rules`, so re-vendoring the script never breaks a repo. A rule that needs the repo's own helper refuses to run without it. Close the promotion issue with the scaffold pull request that ships the rule. Then roll the rule out with `/propagate-vendored conventions_ratchet`, plus one adoption issue in each repo that wrote the local check: enable the rule, commit its baseline, and delete the local test as step 5 of "Adopting it" describes.

## Cost and measured hit rate

A read-only dry run with **every rule on** over every fleet checkout (42 repos), each repo's own `[vendored]` table honoured, and a stand-in helper for `secret-compare` and `git-wrapper` so that every raw call counts, finished without a "not confirmed" in 0.03 to 2.2 s per repo. As a gate stage here it adds about 0.6 s, interpreter start included.

| Rule | Hits | Repos | Checked by hand | Real |
|---|---|---|---|---|
| `no-window` | 277 (265 in tests) | 14 | all 12 outside tests; 13 sampled in tests | in tests 12 of 13 (the miss: a canary spawn that is meant to fail); outside tests 0 of 12: 8 POSIX-only spawns in functions no branch marks (a macOS installer, `launchctl`, `systemctl`) and 4 consoles meant to be visible (foreground runners, a browser bootstrap) |
| `logging-not-print` | 0 | 0 | before the CLI rule: 289 hits in 14 repos, all in command-line modules; 25 sampled | 23 of 25 were the command's output; 2 were `ERROR ...` lines a CLI could log instead |
| `no-drive-path` | 19 | 7 | all | 19 of 19 hardcoded locations (fleet roots, backup targets, a scaffold checkout default); 1 is the scaffold's own `C:/sqlite` runtime-data default, which carries the exempt marker |
| `secret-compare` | 32 | 14 | all | 32 of 32 raw calls; 2 are the repos' own helpers and drop out once declared |
| `git-wrapper` | 24 | 11 | all | 24 of 24 raw `git` spawns; 4 are the repos' own wrappers and 10 are the scaffold's vendored scripts, which adopters exclude through `[vendored]`. Of the three repos that have a wrapper today, one real hit remains: an undeclared vendored copy |

Before the platform-branch and system-folder rules, the dry run also reported `open`/`xdg-open`/`pbcopy`/`xclip` branches (`no-window`), `C:/ProgramData/pip/pip.ini` and a bare `"C:\\"` drive root (`no-drive-path`). Each became a rule above.

The false-positive kinds that remain:

- POSIX-only code that no `if` marks (a whole macOS build function): an exempt marker;
- a console meant to be visible: an exempt marker (the instructions allow it);
- a spawn in a test that is meant to fail: an exempt marker.

## Tests

`tests/ratchets/test_conventions_ratchet.py`: for each rule, a seeded violation that fails by name and the compliant form that passes. Also covered: import aliases, the `**kwargs` miss, every platform-branch form and the early return, the CLI-module and file-write exceptions, the system-folder and drive-root exceptions, docstrings versus f-strings, helpers and wrappers, the test-module scope, and exempt markers (a reason is needed, and the marker must name this rule). On throwaway git repos it runs every mode and exit code: a new violation failing by rule, file and line; a second violation of a baselined rule; shrink-only updates; `--allow-additions`; vendored, excluded and untracked files; a tracked baseline and another ratchet's baseline never read as evidence; and exit 3 for an unparseable file and an unusable `git`, in every mode. A missing prerequisite is a hard failure there, never `pytest.skip`. The scaffold's own gate stage doubles as the guard that its committed baseline is current.
