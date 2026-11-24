# Windows-only ratchet

`scripts/windows_only_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It reads the test modules, finds tests that touch a Windows-only API without the `windows_only` marker, counts them per file and rule, and **fails when a file's count for a rule rises** above the committed baseline. Existing debt never blocks work; it cannot grow either.

It enforces the convention of the [Mac nightly](mac-runner.md) ("The `[ci.nightly]` table"): a test that needs Windows carries `@pytest.mark.windows_only`, and the Mac unit leg leaves it out with `-m "not windows_only"`. Without the check, an unmarked test passes in the Windows gate where it was written and turns the Mac night red a day later. The ratchet moves that discovery to the gate, before the merge.

It has the shape of the other ratchets ([adopting-ratchets.md](adopting-ratchets.md)): an opt-in `.fleet.toml` table, named rules, a committed baseline, the same flags, and exit 3 for "not confirmed". It is one stdlib-only file with no sibling. Every rule is decided from source alone (`ast` and `tokenize`), so the same tree gives the same answer on every machine.

## The rules

Every rule is on unless `rules` narrows the list. The signal list is kept small on purpose: a false positive on a test that only fakes Windows is a bug in the ratchet, so each rule names something that fails off Windows whatever the code under test does.

### `win-module`

An import of a module that exists only on Windows: `winreg`, `msvcrt`, `winsound`, `pywintypes`, `pythoncom`, `wmi`, `comtypes`, or any `win32*` (`win32api`, `win32gui`, `win32com`...). Off Windows the import raises `ModuleNotFoundError`. At module level it breaks the whole module's collection, so only a module-wide cover (`pytestmark`, `pytest.importorskip`, a module-level platform skip) clears it.

### `win-api`

A Windows-only attribute, read through the module, an alias of it (`import subprocess as sp`) or another module's reference to it (`launcher.subprocess.CREATE_NO_WINDOW`), or imported by name (`from os import startfile`): `ctypes.windll`, `ctypes.WinDLL`, `ctypes.oledll`, `ctypes.OleDLL`, `os.startfile`, `subprocess.CREATE_NO_WINDOW`, `subprocess.STARTUPINFO`, `subprocess.DETACHED_PROCESS`, `subprocess.CREATE_NEW_CONSOLE`, `subprocess.CREATE_NEW_PROCESS_GROUP`, `signal.CTRL_C_EVENT`, `signal.CTRL_BREAK_EVENT`. Off Windows each raises `AttributeError`. `getattr(subprocess, "CREATE_NO_WINDOW", 0)` and a `monkeypatch.setattr(ctypes, "windll", ..., raising=False)` name the attribute as a string and are never hits.

### `win-env-read`

`os.environ["<var>"]` for a variable only Windows defines (`ProgramFiles`, `ProgramFiles(x86)`, `ProgramW6432`, `ProgramData`, `LOCALAPPDATA`, `APPDATA`, `USERPROFILE`, `SystemRoot`, `WINDIR`, `COMSPEC`; compared case-insensitively) when nothing in the same file sets it. Off Windows the subscript raises `KeyError`. `os.environ.get(...)` and `os.getenv(...)` return `None` and are not hits; a fixture in the file that sets the variable clears every read of it.

### `win-exe-lookup`

One test both points a Windows-only variable at a folder (`monkeypatch.setenv`, `os.environ[...] =`, `monkeypatch.setitem(os.environ, ...)`, `mock.patch.dict(os.environ, {...})`, `os.environ.update({...})`) and builds an on-disk `.exe` path (`tmp_path / "chrome.exe"`, `Path(..., "app.exe")`, `joinpath`, `os.path.join`). The code under test is resolving a planted Windows install, which no other OS finds. This is the shape of the test that kept the Mac nightly red: it planted `chrome.exe` under a fake `ProgramFiles` and expected the install-folder lookup to find it. Either half alone is not a hit: redirecting `LOCALAPPDATA` to `tmp_path` works on every OS, and a `"C:/Apps/chrome.exe"` string in a fake is never on disk.

### `bare-exempt`

A `windows-only-exempt` marker with no reason. It exempts nothing and is itself a hit.

### Exempting one hit

Write `windows-only-exempt: <reason>` in a comment on the hit's line, in the comment lines right above it, or on (or right above) its test's `def` or first decorator. A reasoned marker removes the hit from the count; every exemption is printed on every run.

## What counts as covered

A hit is not counted when its test is covered:

- `@pytest.mark.windows_only` on the test or its class (`marker` names another marker);
- the marker in the module's `pytestmark` (one mark or a list);
- a `pytest.mark.skipif(...)` whose condition reads the platform, on the test, its class, in `pytestmark`, or through a module-level alias (`windows_only = pytest.mark.skipif(sys.platform != "win32", ...)`);
- a top-level `if <platform test>: pytest.skip(...)` in the test or the module;
- a module-level `pytest.importorskip("winreg")` of a Windows-only module.

Code that never runs off Windows is never a hit: anything under an `if` or a conditional expression that reads `sys.platform`, `os.name`, `platform.system()`, `sys.getwindowsversion` or calls `hasattr(...)`, and the body of a `try` that catches `ImportError`, `ModuleNotFoundError`, `AttributeError`, `OSError` or `Exception`.

A test that fakes the platform is clean of the two environment rules: `monkeypatch.setattr(sys, "platform", "win32")`, `mock.patch("sys.platform", ...)`, `patch.object(os, "name", ...)`. A faked Windows module (`monkeypatch.setitem(sys.modules, "win32gui", MagicMock())`) is not an import and is never a hit.

## What is not checked

- **Path semantics.** A test that needs backslash separators, drive letters, case-insensitive paths or UNC handling fails off Windows without touching any API above. No static signal tells it apart from a test that merely contains such a string, so it stays a human call and the marker convention.
- **Real Windows programs.** A test that runs `powershell.exe`, a `.bat` or `schtasks` through `subprocess` is not detected: the command is a string, and a faked spawn holds the same string.
- **Fixtures and helpers.** Only `test*` functions (and methods of `Test*` classes) and module-level code are read. A Windows API used inside a fixture or helper is not attributed to the tests that use it.
- **`conftest.py`** is not a test module and is not read; a variable an outside `conftest.py` sets still makes `win-env-read` count, so exempt that read with a reason.
- **Parametrize-level marks** (`pytest.param(..., marks=pytest.mark.windows_only)`) cover one case, not the test; a hit in such a test still counts.

## Scope

Tracked and untracked-but-not-ignored files (`git ls-files --cached --others --exclude-standard`) named `test_*.py` or `*_test.py` under `test_paths` (default `tests/**`). `exclude` globs, `**/node_modules/**`, `**/.venv/**`, `**/venv/**` and every `[vendored]` `dest` are skipped; a vendored copy's debt belongs to the repo it came from.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | pass, or the table is absent or `enabled = false` |
| 1 | a file's count for a rule rose, the baseline is missing, or `--update-baseline` met an addition without `--allow-additions` |
| 2 | bad configuration (unknown key, unknown rule, bad marker name), a malformed baseline, `--init` over an existing baseline |
| 3 | **not confirmed**: `git` could not list the tree, or a test module cannot be read, is not UTF-8, or does not parse; the gate fails on it |

## The baseline file

`.ratchets/windows-only.json` (or `baseline`): a version and one entry per file with hits, the count per rule, sorted, no line numbers, so a diff reviews cleanly. It only shrinks on its own: a gone hit prints a hint to run `--update-baseline`.

## Modes

- `python scripts/windows_only_ratchet.py`: check against the baseline.
- `--init`: write the first baseline; never overwrites.
- `--update-baseline`: drop gone hits; refuses additions.
- `--update-baseline --allow-additions`: also record new hits, which shows in review as added lines.

## Adopting it (opt-in per repo)

Adopt it in a repo that declares `[ci.nightly]` ([mac-runner.md](mac-runner.md)), whose `pytest.ini` registers the marker:

```toml
[windows_only_ratchet]
enabled    = true
baseline   = ".ratchets/windows-only.json"  # default
rules      = ["win-module", "win-api", "win-env-read", "win-exe-lookup", "bare-exempt"]  # default: all
marker     = "windows_only"                        # default; the marker the nightly's exclude_marker filters on
test_paths = ["tests/**"]                          # default
exclude    = ["tests/fixtures/**"]                 # globs; never scanned
```

Then `scripts/tools/adopt_ratchets.py <target> --ratchets windows_only` copies the script, records it under `[vendored]` and writes the first baseline, or do the same by hand ([adopting-ratchets.md](adopting-ratchets.md)). The scaffold enables it for itself to dogfood it, though its own `[ci.nightly]` is not declared.

## Tests

`tests/ratchets/test_windows_only_ratchet.py`: each rule on in-memory test modules, including the reference install-lookup test before and after its marker and a test that only fakes Windows; every mode on a throwaway git repo; the not-confirmed exits; and this repo's own adoption.
