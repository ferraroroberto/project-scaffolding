# Conventions ratchet

`scripts/conventions_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It holds a small set of fleet conventions as stdlib `ast` rules (plus rules over lines of web files and text files), counts each enabled rule's hits per tracked file, and **fails when a file's count for a rule rises** above the committed baseline. Existing debt never blocks work; it cannot grow either.

Before it, each convention was guarded by a one-off test in whichever repo last hit the bug: a no-window spawn test here, a constant-time compare test in one app, a raw-git check in another. This stage is the one vendored copy of those guards. A repo that adopts it can delete its local duplicate once the matching rule is enabled and its baseline is committed.

It reuses the shape of the [dead code ratchet](dead-code-ratchet.md): an opt-in `.fleet.toml` table, a committed baseline, the same flags, and exit 3 for "not confirmed". It is stdlib-only and imports nothing it scans. It is three files: the ratchet (configuration, scanning, baseline), `scripts/conventions_readers.py`, the pure readers (syntax-tree predicates and the web and text line rules), and `scripts/conventions_state.py`, the implicit-state-machine readers for Python and JavaScript/TypeScript, which keeps each under the structure limits.

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

#### The fix: `fleet_root()` instead of a drive letter

Most hits name a fleet location: a sibling repo, a helper in another checkout, a scratch folder beside the repos. Their fix is the vendored resolver `src/fleet_root.py` (manifest key `fleet_root`), not a different literal:

```python
from src.fleet_root import fleet_root

helper = fleet_root() / "shared-tools" / "bin" / "send_file.py"
```

`fleet_root()` returns the directory holding the fleet's repos, resolved in this order:

1. the `FLEET_ROOT` environment variable;
2. the machine-local config `$XDG_CONFIG_HOME/fleet/fleet.toml` (`~/.config/fleet/fleet.toml` when unset), key `root`. It lives in the user's home, never in a repo, because the root is a fact about the machine;
3. the parent of the git checkout holding the module, so a repo cloned at `<root>/<repo>`, or a worktree at `<root>/<repo>-wt-<N>`, needs no setup.

Every step yields an existing absolute directory or raises `FleetRootError` naming the step and the value it read. A set-but-wrong value never falls through to the next step, so a typo in `FLEET_ROOT` surfaces instead of resolving to wherever the checkout sits. When no step applies (no variable, no `root` key, and the module is not inside a git checkout), it raises rather than guessing. Tests: `tests/locations/test_fleet_root.py`.

A location that is genuinely one fixed place on every machine (the runtime-data root `C:/sqlite` in `src/runtime_data.py`) keeps its literal under a `no-drive-path-exempt` marker with the reason.

**Enabling the rule in a repo that has hits today.** Add `"no-drive-path"` to `rules` in its `[conventions_ratchet]` table, then record today's hits instead of fixing them first:

- no baseline yet: `python scripts/conventions_ratchet.py --init`;
- a baseline already committed for other rules: `python scripts/conventions_ratchet.py --update-baseline --allow-additions`, which adds the new rule's counts and shows them in review.

Commit the baseline in the same PR as the `rules` change. From then on a new drive literal fails the gate, and each burned-down hit shrinks the baseline with `--update-baseline`. The scaffold itself runs the rule with a baseline of zero.

### `secret-compare`

There is **no global-instruction line** for this rule. It enforces a convention the repo declares by naming its helper: every constant-time comparison goes through one function, which compares bytes rather than `str`, because `hmac.compare_digest` raises `TypeError` on a non-ASCII `str`. Several fleet repos keep a local test for exactly this.

A hit is a call to `hmac.compare_digest` or `secrets.compare_digest`, through any import alias, outside the files listed in `secret_helpers`. The rule refuses to run without `secret_helpers`. It is a [`must-use`](#must-use) policy with the call set built in.

### `git-wrapper`

> Every `git` spawn goes through the tier's `run_git`, and any repo reading git state fleet-wide needs that static gate over its own tree.

A hit is a spawn (the same calls as `no-window`) whose program is literally `git` or `git.exe`: the first item of a list or tuple argument, or the first word of a string command, any directory stripped. It is not reported in the files listed in `git_wrappers`, and the rule refuses to run without `git_wrappers`. A program computed at run time is not seen. It is a [`must-use`](#must-use) policy with the spawn calls and the program built in.

### `password-input-vendored`

There is **no global-instruction line** for this rule. It enforces the scaffold's component contract: every web app that asks for its own password does it through the one vendored sign-in sheet (`app/webapp/static/_vendored/sign-in/`), never its own modal.

It reads web files rather than Python (as `nav-standalone-head` does): `.html`, `.htm`, `.js`, `.mjs`, `.cjs`, `.ts`, `.jsx`, `.tsx`, `.vue`, `.svelte`, `.jinja`, `.jinja2` and `.j2`. A hit is a line that makes a password input: `type="password"` (any quote, or none), `type: 'password'`, `el.type = 'password'`, or `setAttribute('type', 'password')`. It is not reported:

- inside a `_vendored/sign-in/` folder, wherever the app copied it: the component is the one place the field may live;
- in a test file or anything under a `tests/` or `test/` folder (a bespoke modal fixture is how the rule is proven red);
- on a line that only mentions passwords (`placeholder="password"`, `type="password-hint"`, a label).

The rule reads line by line, so a selector that only reads the field (`querySelector('input[type="password"]')`) is a hit too, and a password input built from a string spread across lines, or written by Python (an inline `HTMLResponse`), is not seen.

A password field that is not this app's own sign-in keeps its own markup under a marker with the reason, in the file's comment syntax: a settings field that types into another machine's page, or a separate sign-in page whose request and session differ from the sheet's (a cookie session posting a `secret`):

```html
<!-- password-input-vendored-exempt: types into the remote PC's page, not this app's sign-in -->
<input type="password" id="pcPassword" class="input-native">
```

**Enabling it in an app with a bespoke modal today.** Add `"password-input-vendored"` to `rules` and record today's hit with `--update-baseline --allow-additions` (or `--init` when there is no baseline yet). Moving the app onto the sheet removes the hit, and `--update-baseline` shrinks the baseline to zero.

### `nav-standalone-head`

There is **no global-instruction line** for this rule. It enforces the vendored nav's page-head contract (`app/webapp/static/_vendored/nav/README.md`, step 4): a page that links the nav's `nav-tabs.css` also carries a viewport meta with `viewport-fit=auto` and the `apple-mobile-web-app-status-bar-style` meta set to `black-translucent`. The pill's bottom offset and the top glass are written for that head. Under `viewport-fit=cover` the installed iPhone app's web view runs under the home indicator, so the pill lands on the screen's bottom edge instead of above it, and the apps stop matching each other.

It reads the same web files as `password-input-vendored`, and only a file that links `nav-tabs.css` (`<link ... href="...nav-tabs.css...">`) owes the head. A hit is a viewport meta without `viewport-fit=auto` among its comma-separated values, a status-bar meta with any other content, or either meta missing (reported at the stylesheet's line). A meta tag spread across lines is read whole. A head written by Python or assembled in JavaScript is not seen.

A page that is never installed (a browser-only debug view) keeps its head under a marker with the reason, in the comment block right above the reported line:

```html
<!-- nav-standalone-head-exempt: browser-only debug page, never installed on a phone -->
<meta name="viewport" content="width=device-width, initial-scale=1">
```

### `login-lockout`

There is **no global-instruction line** for this rule. It enforces the scaffold's component contract: every web app's password route answers `429` with `Retry-After` after repeated wrong passwords, through the one vendored `src/login_lockout.py` (manifest key `login_lockout`), never a hand-rolled counter or no limit at all. The sign-in sheet shows the wait; the module enforces it. Wiring: the "Server side" section of `app/webapp/static/_vendored/sign-in/README.md`.

A hit is a FastAPI route decorator `@<anything>.post("<path>")`, the path given by position or `path=`, whose last path segment is `login` (`/api/login`, `/login/`, an admin sub-app's `/api/login`), when:

- the module imports nothing named `login_lockout` (`from src.login_lockout import ...`, `import src.login_lockout as ll`, `from src import login_lockout`, any folder the app copied it to), or
- it does, but the handler's body never calls `retry_after(...)`, the check that refuses a locked client before the password is read.

A route registered any other way (`add_api_route`, `api_route(methods=["POST"])`) or with a computed path is not seen. The rule does not check that the handler also calls `record_failure` and `reset`: the route's own test (6 wrong passwords: six `401`s, then the next attempt gets a `429` with `Retry-After`) proves the lock-out works.

A password route whose lock-out lives elsewhere (an auth middleware in front of it) keeps its exception with a reasoned marker in the comment block right above its decorator:

```python
# login-lockout-exempt: the lock-out runs in AuthMiddleware before this route
@router.post("/api/login")
```

**Enabling it in an app with an unguarded route today.** Add `"login-lockout"` to `rules` and record today's hit with `--update-baseline --allow-additions`. Wiring the module in removes the hit, and `--update-baseline` shrinks the baseline to zero.

### `no-pwsh-stub`

> **Windows PowerShell in spawned commands (any agent)** — use the absolute `C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`, never the 0-byte `pwsh` stub.

On the fleet's main machine `pwsh` resolves to a 0-byte alias, so a gate or restart command written as `pwsh -File ...` does not run. The failure reads as a broken script, not a wrong interpreter, and agents copy the gate command from `CLAUDE.md`, the README and a script's usage banner.

It reads lines of text rather than a syntax tree, in `.md`, `.ps1`, `.bat`, `.cmd`, `.toml`, `.json`, `.yml`, `.yaml` and `.py` files (a Python string or comment is a line of text). A hit is `pwsh` or `pwsh.exe` used as a command:

- followed by a switch: `pwsh -File x.ps1`, `pwsh -NoProfile -Command ...`, `pwsh --version`, in prose, a code fence, a table, a `run:` value or a usage banner; or
- the first quoted item of an argv list: `["pwsh", "-File", "x.ps1"]`, `('pwsh.exe', ...)`.

It is not a hit:

- with a path before it, which is an absolute path to a real install (`C:/Program Files/PowerShell/7/pwsh.exe -File x.ps1`) and, above all, the mandated `C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe`;
- in prose that names the stub without a switch (`never the 0-byte pwsh stub`), as `shell: pwsh` in a workflow, or as `shutil.which("pwsh")`;
- as a shell name in the middle of a list or set (`{"bash", "pwsh", "cmd"}`), which is a name and not a command;
- in a test module or under a `tests/` or `test/` folder, where a fixture legitimately spells the command.

A line that must name the command keeps a reasoned marker on the **same line or the line right above it**, in the file's own comment syntax. The line above counts only when it is not itself a hit, so one marker never covers a second command. The three kinds that need one:

- prose or a banner that names the stub to forbid it;
- a lookup that only checks whether the stub exists (`Get-Command pwsh -ErrorAction SilentlyContinue`);
- a step in a GitHub Actions workflow: a hosted `windows-2025` runner ships a real `pwsh`, so `run: pwsh -File ...` works there. The same script on the fleet machine is still run through the absolute path.

```markdown
<!-- no-pwsh-stub-exempt: names the stub to forbid it -->
Never run `pwsh -File scripts/verify-before-ship.ps1`; use the absolute Windows PowerShell path.
```

Replace the command with `C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -File scripts/verify-before-ship.ps1`. That binary is PowerShell 5.1, so a script it runs must not use PowerShell 7 parameters.

The rule does not see a command split across lines, a quoted `pwsh` that is not the first item of its list, or `pwsh` followed by a bare script path (`pwsh x.ps1`).

**Enabling it in a repo that has hits today.** Add `"no-pwsh-stub"` to `rules` and record today's hits with `--update-baseline --allow-additions` (or `--init` when there is no baseline yet). Fix them in a follow-up: each fixed line shrinks the baseline with `--update-baseline`. Reading these file types makes every tracked `.md`, `.json` and `.yml` file part of the scan, but only while the rule is listed; a repo that does not list it reads the same files as before. A baseline file is never read as a hit.

### `subprocess-timeout`

> **Execution** — any command meant for unattended/scheduled execution must run synchronously (foreground) or poll to completion in the same turn; nothing wakes a headless session that is waiting on a child that never exits.

A blocking spawn with no `timeout=` can hang forever, and in a scheduled run nothing reports it. `ruff` has `S113` for an HTTP request with no timeout but no rule for a subprocess, so this is the same check for `subprocess`.

A hit is a call to `subprocess.run`, `call`, `check_call` or `check_output`, through any import alias, with no `timeout=` keyword. It is not reported when:

- the call passes `**kwargs`, which may carry the timeout (a miss, never a guess);
- it is `Popen`, `asyncio.create_subprocess_exec` or `asyncio.create_subprocess_shell`, which return at once, so their lifetime is managed by the caller.

A call that is meant to block for the child's whole life (a foreground dev runner) takes the exempt marker, with the reason. `timeout=None` counts as a timeout the author chose, so it is not a hit; a literal `None` is not told apart from a variable.

A fix passes a named constant (`timeout=GIT_TIMEOUT_S`) and handles `subprocess.TimeoutExpired` as its own failure, distinct from the child's non-zero exit: a hung child and a failed child are different conditions.

**Enabling it in a repo that has hits today.** Add `"subprocess-timeout"` to `rules` and record today's hits with `--update-baseline --allow-additions` (or `--init` when there is no baseline yet). Fix them in a follow-up, so the baseline reaches zero and is not kept as a standing ledger. A copy of a scaffold script that predates its timeout (`scripts/gen_tailscale_cert.py`, `scripts/classify_e2e.py`) is cleared by re-vendoring it, not by editing the copy.

### `must-use`

There is **no global-instruction line** for this rule. It enforces a convention the repo's own `CLAUDE.md` states by naming one home for a job: a pooled HTTP session, one SQLite connection dependency, one static-file class, one atomic-write helper. The scaffold's own `CLAUDE.md` names several (outbound-connection discipline, the `get_db` dependency, `CachingStaticFiles`).

Re-implementing a canonical helper is the most common duplication finding the audits report, and `jscpd` misses it because the copies are rarely byte-identical. This rule checks the thing that is stable instead: a call to the primitive the helper wraps, made outside the helper. It is data, not code. A repo lists one table per helper in its own `.fleet.toml`, and listing the first entry is what turns the rule on (it need not be named in `rules`):

```toml
[[conventions_ratchet.must_use]]
call   = ["requests.get", "requests.post"]    # a dotted name, or a list of them
helper = ["src/pooled_http.py"]                # the file(s) or folders that may make the call
why    = "CLAUDE.md: outbound-connection discipline, one pooled session"
paths  = ["app/", "src/"]                      # optional: only these paths are held to it (default the whole repo)
```

| Key | Required | Meaning |
|---|---|---|
| `call` | yes | One dotted name (`module.function`) or a list of them. Each must contain a dot. |
| `helper` | yes | Non-empty list of repo-relative files or folders where the call is allowed. |
| `why` | yes | The convention, in a few words. It is printed with every hit. |
| `paths` | no | Repo-relative files or folders the entry binds. Omitted, it binds every scanned `.py` file. |

A missing `helper`, `call` or `why`, an unknown key, a `call` that is not dotted, a value of the wrong type, or `must-use` in `rules` with no entry is a configuration error: exit 2, in every mode.

A hit is a call whose name, resolved through the module's imports, equals one of the entry's `call` names, in a file that is neither under a `helper` path nor outside `paths`. The name is resolved the way `secret-compare` resolves its own: `import sqlite3` and `sqlite3.connect(...)`, `import sqlite3 as sq` and `sq.connect(...)`, `from sqlite3 import connect` and `connect(...)`, and a dotted module such as `urllib.request.urlopen` through `import urllib.request`, `from urllib import request` or `from urllib.request import urlopen`. It is not reported:

- in a test module (any file under a `tests/` or `test/` folder, `test_*.py`, `*_test.py`, `conftest.py`);
- for a relative import (`from .requests import get` is a sibling module, not the library);
- for a name the scanner cannot resolve to an import: a method on an instance (`conn.connect`, `Path.replace`), a name rebound by assignment, a computed callable.

Every entry in a repo counts under the one rule name `must-use`, so the baseline holds a per-file total, as for every other rule. A call that is a documented exception, such as a CLI script that is meant to open its own connection, carries a reasoned marker:

```python
# must-use-exempt: one-shot CLI script; no pool to share
resp = requests.get(url, timeout=10)
```

`secret-compare` and `git-wrapper` run through the same code path: each is a built-in entry whose call set is fixed and whose helper is read from `secret_helpers` or `git_wrappers`. They keep their rule names, config keys and baseline keys.

**Entries worth declaring.** An entry names the repo's own home for the job, so the scaffold can recommend the ones whose home it defines, and a shape for the ones whose home differs per repo. All three below were dry-run over the fleet (hit counts and what was checked by hand are in the table at the end); `paths` keeps the first and the third off one-shot scripts and migrations:

```toml
[[conventions_ratchet.must_use]]
call   = ["requests.get", "requests.post", "requests.put", "requests.patch", "requests.delete", "requests.head", "requests.request"]
helper = ["src/pooled_http.py"]
why    = "CLAUDE.md: outbound-connection discipline, one pooled session"
paths  = ["app/", "src/"]

[[conventions_ratchet.must_use]]
call   = ["fastapi.staticfiles.StaticFiles", "starlette.staticfiles.StaticFiles"]
helper = ["src/static_versioning.py"]
why    = "CLAUDE.md: static assets go through CachingStaticFiles"

[[conventions_ratchet.must_use]]
call   = "sqlite3.connect"
helper = ["src/db.py"]                           # the module that defines get_db: replace with the repo's own
why    = "CLAUDE.md: one get_db dependency owns the connection"
paths  = ["app/", "src/"]
```

The first two helpers are scaffold-vendored files at a fixed path. The `sqlite3.connect` helper is the repo's own, and its name differs (`db.py`, `connection.py`, `store.py`): name the file that holds `get_db`, or the folder when the connection is built in several modules of one package. `os.replace` suits the same shape with an atomic-write helper as its home.

An entry is data in the adopting repo's own `.fleet.toml`. Re-vendoring `scripts/conventions_ratchet.py` never adds one, so no adopter turns red until its owner pastes the entry and records today's hits (below). The scaffold's own `.fleet.toml` declares the first and the third, with its usage log as the one `sqlite3.connect` home and a baseline of zero.

**Enabling an entry in a repo that has hits today.** Add the table, then record today's hits with `--update-baseline --allow-additions` (or `--init` when there is no baseline yet). Fix them in a follow-up: each fixed call shrinks the baseline with `--update-baseline`, and the goal is a baseline with no `must-use` entries left, not a standing ledger. A call that should stay takes the marker above.

### `state-literal`

> An *implicit state machine* is a concept that really has modes (stopped, loading, ready, failed) but never declares them as one official state. ([implicit-state-machines.md](implicit-state-machines.md))

The three state rules are the deterministic scan that page describes: they flag **suspects**, and an agent deep-dive confirms each one before anything is declared or refactored. A lifecycle word is one of `idle`, `loading`, `loaded`, `ready`, `starting`, `started`, `running`, `stopping`, `stopped`, `pending`, `queued`, `waiting`, `failed`, `finished`, `completed`, `done`, `cancelled`, `canceled`, `crashed`, `retrying`, `paused`, `resuming`, `connecting`, `connected`, `disconnected`, `booting`, `warming`, `succeeded`, `errored`, `aborted`, `expired`, `draining`, `terminated`, `killed`, `dead`, `offline`, `online`, `in_progress` and `scheduled` (any case). Generic outcome words (`error`, `success`, `ok`, `active`, `unknown`) are left out: as values they are mostly log levels, HTTP outcomes and toggles.

A `state-literal` hit is a lifecycle string that is compared or stored **as a state**: the name on the other side says it holds one, because its last word (after `_`) is `status`, `state`, `phase`, `stage` or `lifecycle`. The forms read:

- `x.status == "running"`, `"failed" != row["state"]`, `job.get("phase") in ("idle", "loading")` (one hit per literal in the collection);
- `self.status = "stopped"`, `entry["state"] = "idle"`, `status: str = "queued"`;
- a dict literal's state key, `{"state": "started"}`, and a state keyword argument, `finish(status="failed")`.

In **JavaScript and TypeScript** the same rule reads:

- `job.status === 'running'`, `'failed' !== row['state']`, `params.get('phase') == 'done'` (`==`, `===`, `!=`, `!==`, either way round);
- `x.status = 'stopped'`, an object literal's state key `{ status: 'queued' }`;
- a `case 'running':` inside a `switch` whose subject holds a state (`switch (job.status)`);
- `['idle', 'paused'].includes(job.state)` and `new Set(['idle', 'paused']).has(job.state)`, one hit per literal, the JS form of `in (...)`.

It is not a hit when the name says nothing about a state (`level == "running"`, `word = "failed"`), or the value is not a lifecycle word (`status = "green"`). A TypeScript union in a type (`status: 'running' | 'failed'`) is a set, not a stored value, so it is not a `state-literal` hit. It reads one module at a time.

### `state-set-repeat`

A hit is one set of states spelled out in more than one module: a tuple, list or set literal, a `frozenset({...})` / `set([...])` call, a `Literal[...]` subscript, or the string values of an `Enum` / `StrEnum` class, whose items are all strings and at least two of them lifecycle words. Two spellings are the same set when they hold the same strings, in any order and case. Every module that spells it gets a hit at each spelling; a set spelled twice in one module is not a hit. One concept's states written down twice is how two readers come to disagree about which states count as "active".

In JavaScript and TypeScript a set is an array literal (`new Set([...])` counts its array), a TypeScript union of string literals (`'idle' | 'running'`), the string values of a TypeScript `enum`, or an enum-shaped object: every value a string and every key in UPPER_CASE (`Object.freeze({ RUNNING: 'running', PENDING: 'pending' })`) or equal to its value in any case (`{ running: 'Running', pending: 'Pending' }`). A record such as `{ answer: 'done', label: 'Done' }` is data, not a set. A JS spelling counts a Python spelling of the same set as a second home, because a frontend re-spelling its backend's states is the same drift. A Python spelling counts only Python homes, so reading JS never changes a Python module's hits.

### `state-write`

A hit is a boolean, `None`, comparison or `not ...` written to a lifecycle-named flag from more than one module. A lifecycle-named flag is an attribute or a string key whose name, leading underscores dropped, is a flag word (`loading`, `loaded`, `ready`, `starting`, `started`, `running`, `stopping`, `stopped`, `pending`, `busy`, `connected`, `connecting`, `retrying`, `paused`, `initialized`, `booted`, `warming`, `warm`, `finished`, `failed`, `draining`, `in_flight`), optionally after `is_` / `has_` / `was_` and a prefix (`scan_pending`, `_is_ready`, `model_loaded`). `obj.flag = ...`, `obj["flag"] = ...` and `setattr(obj, "flag", ...)` are writes. The receiver's own name is part of the flag, so `load.ready` in one module and `load.ready` in another are one flag with two owners, while `self.ready` in one class and `state.ready` in another are two. A bare local name (`ready = True`) is never shared state and never a write. A flag with no single owner is the "set on entry, cleared only on the happy path" sign.

In JavaScript and TypeScript a write is `obj.flag = ...` or `obj['flag'] = ...` with `true`, `false`, `null`, `undefined`, a `!x` or a comparison (`===`, `!==`, `==`, `!=`, `<=`, `>=`; a bare `<` or `>` is left out because TypeScript generics use it). A default such as `x.ready = x.ready || false` is not a flag value. `this.loading` is keyed `this.loading`. JS flags and Python flags are counted apart in the same direction as sets: a JS write counts a Python write of the same key, a Python write never counts a JS one.

#### Declaring a machine: `[[state_machines]]`

Declaring a machine is what clears its suspects. Each declared machine is one top-level table in `.fleet.toml`:

```toml
[[state_machines]]
name   = "job"                       # the concept, for the messages
module = "src/jobs/state.py"         # the one module that owns it (repo-relative)
type   = "JobState"                  # the declared state type: a class, Enum or type alias defined there
derive = "derive_job_state"          # optional: the derive function defined there

[[state_machines]]
name   = "upload"
module = "app/webapp/static/upload-state.js"  # a JS or TS module works the same way
type   = "UploadState"               # a top-level const, class, enum, type alias or interface there
derive = "deriveUploadState"         # a top-level function or const there
```

Code in a declared module is never reported by the three state rules. Its spellings still count toward the cross-module rules, so a second module that re-spells the declared states (`state-set-repeat`) or writes its flag (`state-write`) is a hit: the fix is to import the declared type or call the derive function. The table is validated whenever the stage is enabled: a missing `name`, `module` or `type`, a non-string value or an unknown key is a configuration error (exit 2). A declared JS/TS module resolves the same way: its top-level `const`, `let`, `var`, `function`, `class`, `enum`, `type` and `interface` names, exported or not, define it. With a state rule listed, a declared module that does not exist or parse, or that defines no top-level `type` or `derive` name, is **not confirmed** (exit 3), never a skip, because a stale declaration would exempt a module that no longer owns the state.

**What the state rules cannot see.** A state held in names that say nothing (`if proc and not err`), a mode inferred from an empty field or a timer, an outcome passed as prose, unknown folded into a negative, and in-memory restart latches (a flag that survives in a long-lived process and is lost on restart). Those stay review-checklist items in [implicit-state-machines.md](implicit-state-machines.md). A status vocabulary that belongs to a remote API (a GitHub run's `in_progress`, a vehicle's `online`) is a hit at the boundary that translates it; that spot is usually the derive function, so declare it or mark it.

#### State rules in JavaScript and TypeScript: how the files are read

The rules read `.js`, `.mjs`, `.cjs`, `.ts`, `.jsx` and `.tsx` files with a stdlib tokenizer, not a JavaScript parser. The tokenizer handles comments, single- and double-quoted strings, template literals (the code inside `${...}` is read; the literal itself is never a fixed state string) and regex literals, then matches brackets. These patterns are all short and local (an operator with a name before it and a string after it, a bracketed list of strings, a `switch` body), so a token stream with bracket pairs is enough. Running a real parser through Node would mean a Node dependency in every adopter's gate and a second toolchain inside a vendored, stdlib-only script, and the fleet dry run showed no pattern the tokenizer misread that a parser would have read correctly (precision table below).

What a token stream cannot tell apart, so the rules miss or over-report it:

- `//` inside JSX text (`<p>see http://x</p>`) reads as a comment to the end of the line;
- a `/` right after a closing `}` is read as division, so a regex literal that opens a statement after a block is misread;
- two features that both name their state object `st` (`ctx.st.busy` in each) share a `state-write` key, like two Python classes sharing a receiver name;
- React's `setLoading(true)` is a call, not a write, so `useState` flags are not `state-write` hits;
- `.vue`, `.svelte` and HTML inline scripts are not read; neither are minified bundles (`*.min.js`).

Test modules are skipped as in Python: a file under `tests/` or `test/` or `__tests__/`, or named `*.test.*` or `*.spec.*`. A file the tokenizer cannot read (an unterminated comment or template literal, or brackets that do not balance) is **not confirmed** (exit 3), never skipped.

### Exempting one call

A call that must break a rule keeps a reasoned marker on one of its own lines, or in the comment block directly above it:

```python
# no-window-exempt: foreground dev runner; the console is the UI
return subprocess.run(cmd, cwd=str(PROJECT_ROOT)).returncode
```

`no-pwsh-stub` takes its marker on the hit's line or the line right above (see its section). In a web file the marker sits in that file's comment syntax (`<!-- ... -->`, `// ...`, `/* ... */`), on the hit's line or in the comment block right above it. The marker names one rule (`<rule>-exempt`) and needs text after it. A bare `# no-window-exempt` exempts nothing, and a marker for another rule does not cover this one. This is the same marker the scaffold's own `tests/test_no_window_convention.py` reads. The three state rules take the same marker in JavaScript and TypeScript, as `// <rule>-exempt: <reason>` or `/* <rule>-exempt: <reason> */`; a marked site is not reported but still counts as a second home for `state-set-repeat` and `state-write`.

## Scope

Every `.py` file git lists (tracked, or untracked and not ignored), every web file for `password-input-vendored` and `nav-standalone-head`, every `.js`, `.mjs`, `.cjs`, `.ts`, `.jsx` and `.tsx` file for the three state rules (not minified bundles or test modules), and every `.md`, `.ps1`, `.bat`, `.cmd`, `.toml`, `.json`, `.yml` and `.yaml` file for `no-pwsh-stub` (only while that rule is listed), except:

- files under the repo's `[vendored]` destinations: a vendored copy's debt belongs to the repo it came from;
- the `exclude` globs, plus `node_modules`, `.venv` and `venv` anywhere.

Only Python source, web files and (for `no-pwsh-stub`) the text files above are read. A baseline (this stage's or any other ratchet's, a file named `*-ratchet-baseline.json` or the configured `baseline`) is JSON and is never read as a hit or as evidence about one.

## Exit codes

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (no rule count above the baseline), or the stage is **not enabled** | continues |
| `1` | A file's count for a rule rose, or the baseline file is missing | fails |
| `2` | Bad `[conventions_ratchet]` table (unknown key or rule, no rules, a helper rule with no helper, a `must_use` entry with an unknown key or no `call`, `helper` or `why`), a bad `[[state_machines]]` entry, unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: `git` unusable, a tracked `.py` file that does not parse, a scanned file that cannot be read, or (with a state rule listed) a JS/TS file the tokenizer cannot read (an unterminated comment or template literal, brackets that do not balance) or a declared state machine whose module is missing or defines no `type` / `derive`. The message names the file and line | fails |

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
.venv/Scripts/python.exe scripts/conventions_ratchet.py                 # check (what the gate runs)
.venv/Scripts/python.exe scripts/conventions_ratchet.py --init          # first baseline; refuses to overwrite
.venv/Scripts/python.exe scripts/conventions_ratchet.py --update-baseline  # drop hits now gone; exit 1 + write nothing if anything was added
.venv/Scripts/python.exe scripts/conventions_ratchet.py --update-baseline --allow-additions  # the explicit flag that adds entries
```

A failing check prints every hit of the risen rule in the file, as `<path>:<line>: [<rule>] <message>`, under a `<path>: [<rule>] <n> hit(s), baseline <m>:` header: without line numbers in the baseline, the stage cannot tell which one is new.

## Adopting it (opt-in per repo)

Re-vendoring the script never breaks a repo that has not opted in: an absent `[conventions_ratchet]` table, or `enabled = false`, prints `conventions ratchet: not enabled` and exits 0 (declared, not inferred).

1. Vendor `scripts/conventions_ratchet.py` and its siblings `scripts/conventions_readers.py` and `scripts/conventions_state.py` byte-for-byte (`python scripts/tools/adopt_ratchets.py <repo> --ratchets conventions` from a scaffold checkout copies and declares them, see [adopting-ratchets.md](adopting-ratchets.md); inside the fleet, `/propagate-vendored conventions_ratchet`, whose `requires` carries both siblings; manifest keys `conventions_ratchet`, `conventions_readers` and `conventions_state`) and declare all three in the repo's `[vendored]` table. The ratchet loads the siblings by path and exits 3 when one is missing. It needs Python 3.11+ (`tomllib`) and `git`; it parses code with the running interpreter's grammar, so run it with the interpreter the project targets.
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

   [[conventions_ratchet.must_use]]                         # one table per helper; see `must-use`
   call   = ["requests.get", "requests.post"]
   helper = ["src/pooled_http.py"]
   why    = "CLAUDE.md: outbound-connection discipline, one pooled session"
   ```

   A Windows-only or cross-platform app enables `no-window`; a Linux-only service does not. `secret-compare`, `git-wrapper` and every `must_use` entry only make sense once the repo has the helper.
3. Declare every vendored copy in `[vendored]` first (an undeclared copy of a scaffold ratchet reports its own `git` spawn as yours). Then run `python scripts/conventions_ratchet.py --init`, review the baseline, and commit it. Each entry is either a violation worth a follow-up fix or a legitimate exception worth an exempt marker. **Adoption never requires the fixes first.**
4. Add a gate stage that runs `python scripts/conventions_ratchet.py` and fails on any non-zero exit. The scaffold's `scripts/verify-before-ship.ps1` places it after the dead code ratchet and before `mypy`. **Do not path-route it**: it is cheap, and a rule added to `rules` must see the whole tree.
5. Delete the repo's local guard test for a rule once that rule is enabled here with a baseline of zero for it; keep the test while the baseline still carries debt, because the test is zero-tolerance and the ratchet is not.
6. Only if the repo uses this scaffold's diff-proportionate e2e routing ([e2e-routing.md](e2e-routing.md)), add a `tier = "none"` rule for the baseline file to `.fleet.toml` `[e2e]` and a matching assertion in `tests/test_classify_e2e.py`.

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
| is a call to one primitive that the repo's `CLAUDE.md` gives a single home | a `[[conventions_ratchet.must_use]]` entry in the adopting repo's `.fleet.toml`, no new code here |
| is a one-line pattern in web or text files (a regex per line, a marker on the line or above it) | a new rule in this stage, as `password-input-vendored` and `no-pwsh-stub` are |
| measures a size, or needs its own perimeter or baseline semantics rather than matching a pattern | a new ratchet with the same contract: opt-in table, committed baseline, shrink-only `--update-baseline`, visible `--allow-additions`, exit 3 for not confirmed |

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
| `login-lockout` | 11 | 11 (of 44) | all | 11 of 11 unguarded password routes, one per web app with a password sign-in: nine with no limit, two with a hand-rolled counter the vendored module replaces. Run alone, 0.3 to 1.2 s per repo |
| `must-use` `requests.<verb>` outside `src/pooled_http.py`, `paths = ["app/", "src/"]` | 14 (57 with no `paths`) | 8 (13) | all 14 in scope; the 43 outside it are one-shot scripts and were not checked | 7 of 14: 4 per-request API calls, a link fetch, a pagination loop and a health probe. 7 are a kind a marker covers: 3 tray one-shots posting once to the app's own port, 3 calls in a benchmark script, 1 repo's own loopback wrapper that is its helper |
| `must-use` `StaticFiles` outside the app's static-versioning module | 2 | 2 | all | 2 of 2: a PWA server mounting stock static files with no cache-busting |
| `must-use` `sqlite3.connect` outside the repo's `get_db` home, no `paths`, every `[vendored]` copy and test module skipped | 45 (1 to 7 per repo, 7 each in two repos) | 21 (of 30 active) | none: the home differs per repo, so each hit counts until the repo names it | not established: the counts are an upper bound until each repo's `helper` is declared, which removes the home's own calls |
| `no-pwsh-stub` | 28 | 5 (of 44) | all | 24 of 28 are the stub run as a command in a gate or restart line: the gate command in `CLAUDE.md` and the README, `docs/` pages, and `scripts/*.ps1` usage banners. 4 are a kind a marker covers: 3 `run: pwsh -File` steps in CI workflows, where a hosted runner has a real `pwsh`, and 1 `Get-Command pwsh` lookup. 8 more sit under `tests/` folders, which the rule skips. |
| `subprocess-timeout` | 128 (24 are in scaffold scripts: 18 in adopters' copies of `gen_tailscale_cert.py`, 5 in `classify_e2e.py` (the scaffold's own 2 since fixed) and 1 in a `gen_ssl_cert.py`) | 21 (of 44) | 14 of the 104 hits outside the scaffold-script copies, every 7th, source read | 12 of 14: a `git`, `ffmpeg`, `ffprobe`, `clip`, `systemctl`, `launchctl` or Ghostscript call that waits on a child with no bound. 2 are a kind a marker covers: foreground runners that block for the child's life. The issue's own hand sample found 8 of 10 real, 2 deliberate. Vendored destinations and test modules are not read. |
| `state-literal` | app-launcher 55, home-automation 9, local-llm-hub 15, whatsapp-radar 21 (100) | 4 of 4 | 42 sampled at random (10 to 12 per repo), source read | 38 of 42 are a lifecycle status compared or stored outside any declared machine (a job record's `"running"`, a run's `"failed"`, a container's `"running"`, a transcription's `"done"`). 4 are a remote API's vocabulary translated at the boundary (a GitHub run's `in_progress`, a vehicle's `online`), the spot a derive function belongs: declare it or mark it. A wider probe that did not require a state-named holder counted 74 / 44 / 30 in the first three repos |
| `state-set-repeat` | app-launcher 4, others 0 | 1 of 4 | all | 4 of 4: one job record's active set (`running`, `pending`) spelled in three modules |
| `state-write` | local-llm-hub 2, others 0 | 1 of 4 | all | 2 of 2: the serving state's `load.ready` written both in its declared module and in the backend process module. Keyed by attribute name alone (no receiver) it reported 4, 2 of them two unrelated classes sharing a `ready` field |
| `state-literal`, JS/TS | 208 JS hits in 15 of 45 repos; read here: app-launcher 31, facilitation-suite 39, home-automation 33, task-os 17, minecraft-bedrock-bot 1, robertoferraro 1 (122) | 6 | all 122, source read | 118 of 122 are a lifecycle status compared or stored outside any declared machine (a job's `'running'`, a card's `'failed'`, a view's `'loading'`, a login's `'waiting'`, a `switch` over a session's submit state). 2 are a remote API's vocabulary (a vehicle's `'online'` and `'Starting'`) and 2 a browser API's (an `AudioContext`'s `'running'`, `document.fonts.status`'s `'loaded'`): declare or mark them. Every tracked JS/TS file in the 45 repos tokenized |
| `state-set-repeat`, JS/TS | parking-manager 1, task-os 2 (3) | 2 | all | 3 of 3: a frontend re-spelling its backend's state set (a renewal's `starting`/`waiting`, a task's status list, a journal's `done`/`cancelled`). The same trees hold option records such as `{ answer: 'done', label: 'Done' }`, which the enum-shape test keeps out |
| `state-write`, JS/TS | task-os 12 | 1 | all | 5 of 12: the archive feature's `st.busy` written from two modules. 7 are a timer feature's own `st.busy`: two features name their state object `st`, the receiver-name limit the Python rule shares |

The state rules were dry-run separately over four repos, read-only from each one's `origin/main` with tests skipped, before any of them declared its machines in `[[state_machines]]`. The JS/TS rows are a later dry run over all 45 fleet repos' checked-out trees with the three rules forced on, tests skipped: every repo's Python counts were identical with and without JS reading.

Before the platform-branch and system-folder rules, the dry run also reported `open`/`xdg-open`/`pbcopy`/`xclip` branches (`no-window`), `C:/ProgramData/pip/pip.ini` and a bare `"C:\\"` drive root (`no-drive-path`). Each became a rule above.

The false-positive kinds that remain:

- POSIX-only code that no `if` marks (a whole macOS build function): an exempt marker;
- a console meant to be visible: an exempt marker (the instructions allow it);
- a spawn in a test that is meant to fail: an exempt marker.

## Tests

`tests/ratchets/test_conventions_ratchet.py`: for each rule, a seeded violation that fails by name and the compliant form that passes. Also covered: import aliases, the `**kwargs` miss (for `no-window` and `subprocess-timeout`), `Popen` and the async spawns never a timeout hit, every platform-branch form and the early return, the CLI-module and file-write exceptions, the system-folder and drive-root exceptions, docstrings versus f-strings, helpers and wrappers, every spelling of a login `post` route and the routes that take no password, every text format and argv spelling of a `pwsh` command against the absolute path, prose, shell-name lists and lookups that are not hits, the test-module scope, and exempt markers (a reason is needed, and the marker must name this rule). On throwaway git repos it runs every mode and exit code: a new violation failing by rule, file and line; a second violation of a baselined rule; shrink-only updates; `--allow-additions`; vendored and excluded files, a new untracked file failing and an ignored one skipped; a tracked baseline and another ratchet's baseline never read as evidence; and exit 3 for an unparseable file and an unusable `git`, in every mode. A missing prerequisite is a hard failure there, never `pytest.skip`. The scaffold's own gate stage doubles as the guard that its committed baseline is current.

`tests/ratchets/test_conventions_state.py` covers the three state rules on throwaway git repos: a hit, a miss, the exempt marker (a marked site is not reported but still counts as a second home) and the declared module's exemption for each, the `Enum`, `Literal` and `frozenset` spellings, and the `[[state_machines]]` table: every malformed entry exits 2, and a declared module, type or derive function that is not there exits 3.

`tests/ratchets/test_conventions_state_js.py` covers the same rules in JavaScript and TypeScript: each comparison, store, `switch`, `includes` and `Set.has` form; the misses (a union type, comments, plain template text, a regex holding a quote, a JSX apostrophe); code inside a `${...}` interpolation; the `//` and `/* */` markers; test modules and minified bundles skipped; arrays, unions, `enum`s and enum-shaped objects as sets, records not; a JS site counting a Python spelling while the Python site does not; JS flag writes and their misses; a declared JS module's exemption and name resolution; and exit 3 for a file the tokenizer cannot read.

`tests/ratchets/test_conventions_must_use.py` covers `must-use`: the entry shape and every config error, import aliases and dotted modules, the helper, `paths` and test-module scope, several entries counted under one rule, the two built-in policies reporting beside a declared one, and the gate on a throwaway repo (a new hit failing by rule, file and line, a baseline burned down to zero, a bad entry exiting 2 in every mode).
