# Clone-and-setup installer

Every app in the toolbox moves to another Windows PC the same way: `git clone`, one `setup.bat`, and a playbook for a fresh PC, an update, a migration and an uninstall. An existing PC's local config is kept and only topped up.

## The pieces

| Piece | Source here | In the app | How it travels |
| --- | --- | --- | --- |
| The installer | `src/installer.py` | `src/installer.py` | vendored verbatim, manifest key `installer` |
| Migration | `src/installer_migrate.py` | `src/installer_migrate.py` | vendored verbatim, manifest key `installer_migrate` |
| Its declaration | `src/installer_declaration.py` | `src/installer_declaration.py` | vendored verbatim, manifest key `installer_declaration`; `installer_migrate.py` loads it by path |
| Replace at the same path (`-Replace`, `-InPlace`) | `src/installer_inplace.py` | `src/installer_inplace.py` | vendored verbatim, manifest key `installer_inplace` |
| The launcher | `scripts/templates/setup.bat` | `setup.bat` | copied once, renamed; it needs no edit |
| Replace from the scaffold | `scripts/tools/replace_app.py` | nothing | run from a project-scaffolding clone, never vendored ([below](#replacing-an-install-at-its-path--replace--inplace-and-replace_apppy)) |
| The playbook | `docs/templates/install-playbook.md` | `docs/install.md` | copied once, placeholders filled per app; its Install, Update and Migrate sections are checked by the [install standard ratchet](install-standard-ratchet.md) |

The module is stdlib only, because on a fresh PC it runs on the system python before any requirement is installed. `setup.bat` runs it as a script in isolated mode, `python -I src\installer.py`: `src/` stays off `sys.path`, so an app whose `src/__init__.py` imports a third-party package still installs, and no module of the app can shadow the standard library. Reading `.fleet.toml` needs Python 3.11 or newer (`tomllib`); an older interpreter fails the run with that message.

`setup.bat` is a batch file, not a `.ps1`, so the PowerShell execution policy (`AllSigned` included) never refuses it. It runs the repo's `.venv` python once that exists, else the `py` launcher, else `python` on `PATH`, and passes every argument through. `-Replace` and `-InPlace` always take the system python ([below](#replacing-an-install-at-its-path--replace--inplace-and-replace_apppy)).

## What a run does

Before step 1, every required check that needs nothing setup creates runs ([levels](#required-checks-and-optional-features)). One that is not `ok` stops the run: nothing is installed or written, and the exit code is 1.

1. **`.venv`:** created when missing; an existing one, a junction included, is kept as it is.
2. **Requirements:** `pip install -r` runs only when the requirements file's hash differs from the one recorded inside `.venv` by the last successful install.
3. **Dependency step (optional):** a declared command, rerun only when the command or one of its declared input files changed since it last succeeded.
4. **Configs:** each sample/target pair. A missing target is copied from its sample. A target listed in `settings` that exists gains only the keys its sample has and it lacks (nested objects included, `_`-prefixed keys skipped), after a timestamped backup beside it (`<name>.bak-<YYYYmmdd-HHMMSS>`); the added key names are printed, never values, and no existing value changes. The backup holds the same values as the config (passwords, tokens), so before writing anything the installer asks `git check-ignore` whether the backup path is ignored: not ignored → the top-up is `refused`; git missing or the folder not a checkout → `not confirmed`. Both write nothing and fail the run. Every other target is a registry, the owner's own list: created when missing, never rewritten. A settings file that does not parse is left alone and reported. Configs, samples and `.fleet.toml` may start with a UTF-8 byte-order mark: every reader accepts it, and a file the installer rewrites is written without one.
5. **Start at log on (optional):** with `-Startup`, the declared register command runs only when the declared check says autostart is absent; a present one is reported `kept`.
6. **Checklist:** two lists. **Required:** the venv, the requirements, the dependency step, each config and each required check, each `ok`, `missing` or `unknown`. **Optional features:** each optional check and the autostart, each `available`, `off` or `unknown`, with what it unlocks. A fact the run could not establish (a probe that would need a `.venv` that does not exist yet, a probe that hangs or exits with another code) is `unknown`, never `ok`.

`-WhatIf` reports every change as `would ...` and writes nothing. A second run reports `unchanged` and writes nothing. The exit code is 0 when every step ran and every required item is `ok`, and 1 otherwise: a step failed, a settings file was left alone, a top-up was refused or not confirmed, or a required item is `missing` or `unknown`. An optional feature never changes it. Under `-WhatIf` nothing is created, so only the checks that run first can fail it.

The `.venv`, install and register steps (1, 2, 3 and 5) write straight to the setup's own output, on the console or into the file it is redirected to, so a long install shows its progress and a failed step's error text stands above the checklist. No window opens: a step shares the console setup runs in, and only a run with no console passes `CREATE_NO_WINDOW`. Passing that flag from a console would put the step on a hidden console of its own and lose everything it writes.

A probe's output is discarded and no config value is printed by the installer itself: the checklist shows item names, states, hints, the reason a fact could not be established and, for a `python` check, version numbers.

## Required checks and optional features

Each `[[install.check]]` has a `level`:

- **`required`:** the app does not work without it. It takes no `blocks`.
- **`optional`:** the app works without it. It names what it unlocks in `blocks` (`"recording"`, `"phone access"`, `"remote sign-in"`).

An item that declares no `level` is optional, and the checklist says the declaration does not name its feature. A `python` check is the exception: it is required unless it says otherwise.

When a required check runs depends on what it needs:

| Kind | Runs |
| --- | --- |
| `python`, `which`, and a `command` without `{python}` | before `.venv` is built; not `ok` stops the run |
| `paths`, and a `command` with `{python}` | after the install, since setup may create what they look at; not `ok` fails the run |

`python = "3.14"` means that version or newer. It is read from the `.venv` python when `.venv` exists, else from the interpreter that would build it. Setup does not search for another installed interpreter. State a minimum Python this way, not as a `{python}` probe: a probe runs only after everything is installed.

## The `[install]` table

Everything app-specific is declared in the app's `.fleet.toml`. With no table the defaults apply: `requirements.txt`, every `config/*.sample.json`, all of them registries, no extra checks.

```toml
[install]
requirements = "requirements.txt"                          # the default
samples      = ["config"]                                  # folders scanned for *.sample.json -> *.json
settings     = ["config/config.json", "config/webapp_config.json"]   # topped up; every other config is a registry

# A pair outside the *.sample.json convention (any file type; only JSON settings are topped up).
[[install.config]]
sample = "webapp/tunnel.sample.yml"
target = "webapp/tunnel.yml"

# Optional dependency step; {python} is the repo's .venv python.
[install.deps]
command = ["npm", "ci"]
inputs  = ["package-lock.json"]

# Optional log-on autostart: check exits 0 when registered, 1 when not; register adds it.
[install.startup]
check    = ["{python}", "-m", "src.boot_autostart", "status"]
register = ["{python}", "-m", "src.boot_autostart", "enable"]

# Extra checklist items: exactly one of paths (all must exist), which (a CLI on PATH), command
# (exit 0 ok, 1 missing, anything else unknown) or python (a minimum version). The hint is printed
# while the item is not ok.
[[install.check]]
name   = "Python 3.14"
python = "3.14"                                            # required by default; checked before any install
hint   = "install Python 3.14, delete .venv and run setup.bat again"

[[install.check]]
name  = "git"
level = "required"
which = "git"

# `status` exits 0 when a password is stored, 1 when not, 2 when a file it needs cannot be read or does not parse.
# An app that still honours an old plaintext value adds where it lives, a top-level key of a JSON file:
# "--legacy", "config/webapp_config.json", "auth_password".
[[install.check]]
name    = "Sign-in password"
level   = "optional"
blocks  = "remote sign-in"
command = ["{python}", "-m", "src.password", "status"]
hint    = "set one with: .venv\\Scripts\\python.exe -m src.password set"

[[install.check]]
name   = "HTTPS certificate"
level  = "optional"
blocks = "phone access"
paths  = ["webapp/certificates/cert.pem", "webapp/certificates/key.pem"]
hint   = "run: .venv\\Scripts\\python.exe scripts\\gen_tailscale_cert.py"
```

A malformed table fails the run before any step, naming the key.

## Migrating an existing install

Two entries move a PC's existing install onto a fresh clone. Both read the same declaration, in the clone's `.fleet.toml`:

```toml
# Where the app answers {git_sha, built_at}. Always asked on 127.0.0.1; port falls back to the top-level `port`.
[install.endpoint]
scheme       = "http"             # or "https"; asked first, the other scheme second
version_path = "/api/version"
self_signed  = false              # true accepts any certificate, safe only because the host is loopback
port_config  = "config.json"      # optional: the JSON config where this PC sets the port it serves on
port_key     = "port"             # the default; a dotted key ("webapp.port") reaches a nested one

[install.migrate]
copy    = ["config.json", ".env", "webapp/certificates"]   # this PC's own files and folders, repo-relative
secrets = [".env", "webapp/certificates/key.pem"]           # compared by hash, never printed
shared  = ["folder-explorer"]                                # runtime-data folder names (<FLEET_DATA_ROOT>/<name>): left in place
start   = ["tray.bat", "--restart"]                         # the default
```

A malformed table fails the run before anything is written, naming the key. An app with no `[install.endpoint]` can still copy, but its verify is `unknown`, so the run fails.

**Which port and scheme verify asks.** The declaration holds the app's defaults; a PC can serve elsewhere. With `port_config`, the port is read from that file under `port_key`, in the clone after the copy (the old copy's file for the `-StopOld` wait and under `-WhatIf`). A file that is not there, or that sets no such key, means the app runs on its default, so the declared port is used. A file that does not parse, or a value that is not a TCP port, is `unknown` and fails the run: the real port cannot be told. The declared scheme is asked first and the other one second, so a PC that serves plain HTTP where the declaration says HTTPS (or the reverse) still verifies; the second HTTPS attempt accepts any certificate, because the host is always 127.0.0.1. The verify row names the URL that answered and where its port came from.

### Which paths belong to a folder

A folder can be reached by more than one spelling: a directory junction, a symlink, a mapped or `subst` drive, and a copy started through one of them carries that spelling in its program path, command line, configs and Startup entries. Every folder comparison therefore matches a path that is spelled as the folder **or leads to it**: the process list the stop and verify work from, the refusal of a run started from the app, the autostart inventory and leftovers, and rebind. A sibling that only shares a prefix (`app.bak-1` beside `app`) never matches.

A `.venv` that is itself a junction to somewhere else still belongs to the app it sits in. The reverse also holds: a process whose program reaches into the folder through another checkout's junction (a worktree sharing the app's `.venv`) is running the folder's files, so it is stopped with the rest. Only drive-letter paths in free text are followed; a UNC path is matched by spelling.

### Which listeners hold the port

The `-StopOld` wait and verify's owner check count only the listeners a connection to 127.0.0.1 can meet: those on `0.0.0.0`, `::`, `127.0.0.1` or `::1`, and one whose address the listing does not give. A listener on any other address of the same port number is ignored by both, because verify only ever asks 127.0.0.1: a reverse proxy publishing the app's port on a VPN or LAN address (Tailscale Serve mapping `https:<port>` to `http://127.0.0.1:<port>` has this shape) neither keeps the port busy nor counts as its owner. The inventory still lists every port a process listens on, whatever the address.

### `setup.bat -MigrateFrom <old folder>`

Run in a fresh clone beside the old copy. `-StopOld` first stops the old copy; `-WhatIf` and `-Json` apply as usual.

**On the same PC, pass `-StopOld`.** Two copies of one app cannot both run there: the tray's single-instance lock is named per app, not per folder, so the second tray exits while the first runs, and both copies bind the same port. A lock named per folder would not help, since the port still collides. Without `-StopOld` the copy runs, but the old copy keeps the port and verify fails, naming it as the port's owner. `-Replace` and `-InPlace` always stop the old copy first.

1. **Guards.** The folder must be the root of a clean git checkout (no changed or untracked files), and the old folder another folder, not inside or around it. Anything else is `refused` and nothing is written. A rerun is allowed: files a previous run copied are ignored, so the checkout is still clean.
2. **Inventory, read only.** The old folder, its git remote, the processes that run from it with their listening ports, and the Startup links and files, `HKCU` Run values and scheduled tasks whose command names it.
3. **Stop (`-StopOld` only).** Every process that runs from the old folder is stopped by PID with its tree, never by name, repeating while a watchdog respawns one. Then the run waits for the declared port to be free, naming any PID that still [holds it](#which-listeners-hold-the-port). When this run was itself started from one of those processes (the program lives in the folder), the stop is `refused`, because it would end the run: migrate a launcher from a plain terminal, never from a session it hosts.
4. **Copy.** Each declared file, or each file in a declared folder, is `copied` only when it is not here yet; one that is here is `kept` and never overwritten. SQLite `-wal`, `-shm` and `-journal` files are never copied, and a database (`.sqlite`, `.sqlite3`, `.db`) is held back while the old copy runs. `shared` folders stay where they are and are reported. Under `-WhatIf` each file a declared folder would copy gets its own `would copy` row, by name.
5. **Rebind.** In each copied JSON file, a string value that starts with the old folder (either slash style, any case, by path component) is rewritten to the clone's folder; the key names are printed. A copied file of another kind that still names the old folder is listed for a hand edit.
6. **Secrets.** Each declared secret here against the old one: `same`, `differs` or `missing`, by hash.
7. **Install.** The normal run above, so copied settings files are topped up the usual way.
8. **Start and verify.** The start command runs (its output goes to `.venv/migrate-start.log`, so an app it leaves running holds no pipe of this run). Verify passes only when the endpoint ([port and scheme](#migrating-an-existing-install)) serves this clone's `HEAD` and every process [listening on the port](#which-listeners-hold-the-port) runs from this clone, found by walking up from the listener to the nearest process whose program or python command line is in either folder. An old copy that still serves the port fails it, even on the same commit.
9. **Leftovers.** What still runs from or points at the old folder is listed after verify, without failing it.

Each row is named, never valued. The exit code is 0 only when every step ran and verify passed; a fact a probe could not establish is `unknown` and fails the run.

### Replacing an install at its path: `-Replace`, `-InPlace` and `replace_app.py`

All three land a fresh clone at the app's canonical path, `<root>\<app>`, so whatever stores that path (a launcher's app list, a Startup link, a scheduled task) needs no edit, and all are repeatable any number of times. They run the same code and differ only in where it comes from:

- **`<app>.incoming\setup.bat -Replace <app>`** runs from a fresh clone beside the install, with the clone's own vendored `installer_inplace.py`. None of the install's own code runs, so it works whatever version the install is, including one whose `setup.bat` predates both flags.
- **`<app>\setup.bat -InPlace`** runs from the install and first clones the install's `origin` to `<app>.incoming` itself. It needs an install new enough to have the flag; an older `setup.bat` stops with `unrecognized arguments: -InPlace`.
- **`scripts\tools\replace_app.py <app> --root <root>`** runs from a project-scaffolding clone with this scaffold's `installer_inplace.py`, so an installer fix reaches every app with a `git pull` of the scaffold, before any app is re-vendored. It uses `<root>\<app>.incoming` when that is there; otherwise it clones the origin of `<root>\<app>`, or, when that folder is missing or is another app, of the one sibling copy whose origin is named `<app>` (more than one, or none: clone `<app>.incoming` yourself and run it again). It reads `<root>\<app>` as another app only when that folder's origin is not named `<app>` and it is no copy of a sibling whose origin is; an unrelated repository whose origin is also named `<app>` cannot be told apart, so there clone `<app>.incoming` yourself. The app's own `.fleet.toml` still decides what moves, and its own `setup.bat -MigrateFrom` still does the install.

Run from `<root>`, the folder that holds the app:

```powershell
cd <root>
git clone <origin URL> <app>.incoming          # git -C <app> remote get-url origin prints it
.\<app>.incoming\setup.bat -Replace <app> -WhatIf
.\<app>.incoming\setup.bat -Replace <app>

# or, from a project-scaffolding clone (git pull it first):
py -3 -I <scaffold>\scripts\tools\replace_app.py <app> --root <root> -WhatIf
py -3 -I <scaffold>\scripts\tools\replace_app.py <app> --root <root>
```

`-Replace` takes the install's folder relative to the terminal's current folder, or absolute; the folder may be missing.

#### Which copy is the install

Installs drift: the copy that runs may sit in a suffixed folder (`<app>-new`, `<app>-e2e`), `<root>\<app>` may be an old leftover or missing, and the origin URL may be spelled another way (ssh or https, a repository's old name that the host redirects). So the run finds the install on the machine:

- **Same app by history.** A checkout is a copy of the app when it shares the repository's root commit (`git rev-list --max-parents=0 HEAD`) with the incoming clone, whatever its origin URL says. Only when one side has no history (no commit, a shallow clone) does the origin decide, parsed into host and `owner/name` from any https, ssh or scp form, case and `.git` aside. A repository of its own built from the app's history (a fork, a "lite" copy) is another app: its folder carries its own origin's name, and that name is not the app's.
- **The candidates.** `<root>\<app>` when it is a copy of the app ([or another app](#another-app-at-the-installs-path)); every sibling `<app>-*` or `<app>.*` that is a copy of the app (never a `.bak-*` or `.incoming*` folder; one of another app is listed as `other app` and left alone); and the checkout of whatever holds the app's port, wherever it is. The port is the one each candidate's own config sets (`port_config`), the declared one where it sets none. A holder is traced up its parent chain to the nearest process whose program, or whose python command line, lies in a checkout.
- **A port held by another program is refused.** When the nearest checkout of a port holder is not a copy of the app, or there is none, the run stops before anything is stopped, naming the holder's PID and program path.
- **The live copy** is the candidate holding the port, else the one something runs from, else the most recently committed. The `discover` rows name every candidate, which one is live and why, and `missing` when `<root>\<app>` is not there.

#### Another app at the install's path

`<root>\<app>` may hold a different repository while the app runs from a suffixed sibling. The run treats that folder like an unrelated sibling: a `discover` row `other app`, `left alone` with the reason, nothing in it stopped, and the search goes on. When the clone lands at `<root>\<app>`, the folder is first renamed to `<app>.bak-YYYYMMDD-N`, never deleted; that backup holds the other app, not a fallback for this one. Anything that starts the other app by its old path (a Startup link, a scheduled task) needs repointing by hand.

The run is `refused` before anything stops while something runs from that folder, since this run stops only the app's own copies. It is also refused when no copy of the app is found anywhere, when the folder is not the root of a git checkout, and when the other app holds the app's port; in each case nothing is renamed.

#### The steps

1. **Guards.** The incoming clone must be the root of a clean checkout (no changed or untracked files), have no `.venv` yet (a venv names the folder it was made in), and have nothing running from it. Uncommitted changes in a folder the run renames are reported as `kept`: they stay in its backup. Anything else is `refused` and nothing is changed.
2. **Discover**, as above.
3. **Inventory and stop.** The live copy's inventory as in `-MigrateFrom`; then every process that runs from any candidate is stopped by PID with its tree, and the run waits for each port. Under `-WhatIf` each process is listed with the folder it runs from and its ports.
4. **Rename** `<root>\<app>`, when it exists, to `<app>.bak-YYYYMMDD-N`, the first free `N` of the day.
5. **Move** the incoming clone to `<app>`.
6. **Migrate:** the moved clone's `setup.bat -MigrateFrom` the live copy (its backup when the live copy was `<root>\<app>`): copy, rebind, secrets, install, start, verify. Migrating from a sibling at its own path lets rebind turn the sibling's paths into the clone's.
7. **Retire a live sibling.** When the migration passed, the live sibling is renamed to its own backup name, `<sibling>.bak-YYYYMMDD-N`, so nothing starts it again; a stale sibling stays where it is, stopped.

`-InPlace` makes the clone before step 2, so a clone that fails stops nothing and changes nothing. A `<app>.incoming` that is already there is refused, with the `-Replace` command that would use it.

**When a step fails.** Before step 4 every copy is still at its path: the run names the start command that brings the live one back (`[install.migrate] start`, by default `tray.bat --restart`). A rename at step 4 that fails changes nothing else. A move at step 5 that fails renames the backup back to `<app>` and leaves the clone where it was. When that rename back fails too, the report names both folders, for a rename by hand. A migration that fails at step 6 leaves a live sibling at its path, the fallback; otherwise the backup is the fallback ([below](#what-still-works-in-the-backup)). Nothing deletes either.

**How the run gets out of the way.** Windows refuses to rename a folder that a process runs from or has as its current folder, so `setup.bat` copies the running clone's `installer_migrate.py`, `installer_declaration.py` and `installer_inplace.py` to a temporary folder and runs them there with the system python, with `%TEMP%` as the current folder. Run it from a terminal whose current folder is outside the app (`<root>`). The temporary folder (`%TEMP%\setup-inplace-*`) is removed when the run ends, whether it passed or failed. The run, the removal and the exit are one line of `setup.bat`, because the file cmd.exe is reading is renamed away under it; that line leaves the batch with `(goto)` before it sets the exit code, since ending a batch whose file is gone otherwise fails with exit code 1.

`-WhatIf` prints the guards, every candidate and which one is live, the inventory, what it would stop, every file the migration would copy (by name), the backup names, the renames and the migration, and changes nothing: the folder listing, the git refs and the running processes are the same before and after. It never clones: `-InPlace -WhatIf` and `replace_app.py -WhatIf` without an `<app>.incoming` compare histories using the copy they would clone from, in the clone's place.

The copy list is the one the real run goes by, and the first `copy` row, `copy list`, names where it was read. With an `<app>.incoming` that is the fresh clone. Without one it is `origin's default branch`: the run fetches that branch's head into the copy it would clone from (objects and `FETCH_HEAD` under `.git` only) and reads its `.fleet.toml`. When the origin cannot be read, the list shown is the live copy's and the row is `unknown`, so the preview does not pass. When the origin is read and declares no `[install.migrate]`, the real run falls back to the live copy's list, and the preview shows that one.

Migrating a launcher (app-launcher, app-launcher-lite) stops it and every session it hosts, so run it from a plain terminal: the stop refuses when it would end its own run.

#### What still works in the backup

It is a full git checkout, and `.venv\Scripts\python.exe -m <module>` runs as before, because a venv's `python.exe` finds its base interpreter through `pyvenv.cfg`. The console-script launchers in `.venv\Scripts` (`pip.exe`, `uvicorn.exe` and the like) and the `activate` scripts embed the original path: after the rename they start the new clone's interpreter, or nothing until the clone's `.venv` exists. A `tray.bat` that resolves its own folder (`%~dp0`) starts the backup from the backup. To fall back: stop the new copy, rename the clone away, rename the backup to the original name and start it.

## Adopting it

1. Vendor `src/installer.py`, `src/installer_migrate.py`, `src/installer_declaration.py` and `src/installer_inplace.py` and list them under `[vendored]` in the app's `.fleet.toml`. An older entry script that ran the installer is deleted: `setup.bat` runs the module directly.
2. Copy `scripts/templates/setup.bat` to `setup.bat` at the repo root. An app that already has a `setup.bat` with extra steps (another installer it offers, a closing banner) keeps them after the `src\installer.py` line, skipped when the arguments include `-Json`: anything printed after the report breaks the JSON document a caller parses, and `-Replace` and `-InPlace` read the child's `-MigrateFrom -Json` output that way.
3. Declare the `[install]` table, giving each check its `level` and each optional one its `blocks`. Keep every config's sample tracked and its target gitignored, and add `*.json.bak-*` to `.gitignore`: a rule written for the config (`config/*.json`, or the file's own name) does not match `config.json.bak-<stamp>`, and without the line every top-up is refused. A check or autostart that lives in the app's own code gets a small command-line entry that exits 0, 1 or another code, as above.
4. Declare `[install.endpoint]` and `[install.migrate]`: the app's own configs, state and certificates to copy, the secrets among them, and its runtime-data folders as `shared`.
5. Copy `docs/templates/install-playbook.md` to `docs/install.md`, fill each placeholder and delete the lines that do not apply, keeping its Install, Update and Migrate sections. It never deletes the old copy, which is retired only after the owner confirms.
6. Link the playbook from the README's install section.
7. Vendor `scripts/install_standard_ratchet.py` (manifest key `install_standard_ratchet`) and enable `[install_standard_ratchet]`: it fails the gate when one of the pieces above goes missing, the installer falls behind the scaffold's, or `setup.bat` does not offer `-MigrateFrom`, `-Replace` and `-InPlace` ([install standard ratchet](install-standard-ratchet.md)).

## The top-up can change behaviour

A top-up never changes a value that is there, yet it can still change what the app does. A key the config lacked was running on the code's default; the top-up writes the sample's value, so a sample value that differs from the code default (a feature flag set to `true` in the sample, a different port or interval) switches behaviour on the next start. A new key that takes precedence over an older one the app still honours has the same effect. Keep each sample value equal to the code default, or give the app a test that tops up an older config and asserts nothing it already did changes.
