# Clone-and-setup installer

Every app in the toolbox moves to another Windows PC the same way: `git clone`, one `setup.bat`, and a playbook for a fresh PC, an update, a migration and an uninstall. An existing PC's local config is kept and only topped up.

## The pieces

| Piece | Source here | In the app | How it travels |
| --- | --- | --- | --- |
| The installer | `src/installer.py` | `src/installer.py` | vendored verbatim, manifest key `installer` |
| The launcher | `scripts/templates/setup.bat` | `setup.bat` | copied once, renamed; it needs no edit |
| The playbook | `docs/templates/install-playbook.md` | `docs/install-playbook.md` | copied once, placeholders filled per app |

The module is stdlib only, because on a fresh PC it runs on the system python before any requirement is installed. `setup.bat` runs it as a script in isolated mode, `python -I src\installer.py`: `src/` stays off `sys.path`, so an app whose `src/__init__.py` imports a third-party package still installs, and no module of the app can shadow the standard library. Reading `.fleet.toml` needs Python 3.11 or newer (`tomllib`); an older interpreter fails the run with that message.

`setup.bat` is a batch file, not a `.ps1`, so the PowerShell execution policy (`AllSigned` included) never refuses it. It runs the repo's `.venv` python once that exists, else the `py` launcher, else `python` on `PATH`, and passes `-WhatIf` and `-Startup` through.

## What a run does

Before step 1, every required check that needs nothing setup creates runs ([levels](#required-checks-and-optional-features)). One that is not `ok` stops the run: nothing is installed or written, and the exit code is 1.

1. **`.venv`:** created when missing; an existing one, a junction included, is kept as it is.
2. **Requirements:** `pip install -r` runs only when the requirements file's hash differs from the one recorded inside `.venv` by the last successful install.
3. **Dependency step (optional):** a declared command, rerun only when the command or one of its declared input files changed since it last succeeded.
4. **Configs:** each sample/target pair. A missing target is copied from its sample. A target listed in `settings` that exists gains only the keys its sample has and it lacks (nested objects included, `_`-prefixed keys skipped), after a timestamped backup beside it (`<name>.bak-<YYYYmmdd-HHMMSS>`); the added key names are printed, never values, and no existing value changes. The backup holds the same values as the config (passwords, tokens), so before writing anything the installer asks `git check-ignore` whether the backup path is ignored: not ignored → the top-up is `refused`; git missing or the folder not a checkout → `not confirmed`. Both write nothing and fail the run. Every other target is a registry, the owner's own list: created when missing, never rewritten. A settings file that does not parse is left alone and reported.
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

# `status` exits 0 when a password is stored, 1 when not, 2 when a file it needs cannot be read.
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

## Adopting it

1. Vendor `src/installer.py` and list it under `[vendored]` in the app's `.fleet.toml`. An older entry script that ran the installer is deleted: `setup.bat` runs the module directly.
2. Copy `scripts/templates/setup.bat` to `setup.bat` at the repo root. An app that already has a `setup.bat` with extra steps (another installer it offers, a closing banner) keeps them after the `src\installer.py` line.
3. Declare the `[install]` table, giving each check its `level` and each optional one its `blocks`. Keep every config's sample tracked and its target gitignored, and add `*.json.bak-*` to `.gitignore`: a rule written for the config (`config/*.json`, or the file's own name) does not match `config.json.bak-<stamp>`, and without the line every top-up is refused. A check or autostart that lives in the app's own code gets a small command-line entry that exits 0, 1 or another code, as above.
4. Copy `docs/templates/install-playbook.md` to `docs/install-playbook.md`, fill each placeholder and delete the lines that do not apply. The migrate section names the app's own configs, state and certificates; it never deletes the old copy, which is retired only after the owner confirms.
5. Link the playbook from the README's install section.

## The top-up can change behaviour

A top-up never changes a value that is there, yet it can still change what the app does. A key the config lacked was running on the code's default; the top-up writes the sample's value, so a sample value that differs from the code default (a feature flag set to `true` in the sample, a different port or interval) switches behaviour on the next start. A new key that takes precedence over an older one the app still honours has the same effect. Keep each sample value equal to the code default, or give the app a test that tops up an older config and asserts nothing it already did changes.
