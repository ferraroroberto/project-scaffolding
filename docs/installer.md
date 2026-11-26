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

1. **`.venv`:** created when missing; an existing one, a junction included, is kept as it is.
2. **Requirements:** `pip install -r` runs only when the requirements file's hash differs from the one recorded inside `.venv` by the last successful install.
3. **Dependency step (optional):** a declared command, rerun only when the command or one of its declared input files changed since it last succeeded.
4. **Configs:** each sample/target pair. A missing target is copied from its sample. A target listed in `settings` that exists gains only the keys its sample has and it lacks (nested objects included, `_`-prefixed keys skipped), after a timestamped backup beside it (`<name>.bak-<YYYYmmdd-HHMMSS>`); the added key names are printed, never values, and no existing value changes. The backup holds the same values as the config (passwords, tokens), so before writing anything the installer asks `git check-ignore` whether the backup path is ignored: not ignored → the top-up is `refused`; git missing or the folder not a checkout → `not confirmed`. Both write nothing and fail the run. Every other target is a registry, the owner's own list: created when missing, never rewritten. A settings file that does not parse is left alone and reported.
5. **Start at log on (optional):** with `-Startup`, the declared register command runs only when the declared check says autostart is absent; a present one is reported `kept`.
6. **Checklist:** the venv, the requirements, the dependency step, each config, each declared check and the autostart, each `ok`, `missing` or `unknown`. A fact the run could not establish (a probe that would need a `.venv` that does not exist yet, a probe that hangs or exits with another code) is `unknown`, never `ok`.

`-WhatIf` reports every change as `would ...` and writes nothing. A second run reports `unchanged` and writes nothing. The exit code is 0 when every step ran and 1 when one failed, a settings file was left alone, or a top-up was refused or not confirmed.

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

# Extra checklist items: exactly one of paths (all must exist), which (a CLI on PATH) or command
# (exit 0 ok, 1 missing, anything else unknown). The hint is printed while the item is not ok.
# `status` exits 0 when a password is stored, 1 when not, 2 when a file it needs cannot be read.
# An app that still honours an old plaintext value adds where it lives, a top-level key of a JSON file:
# "--legacy", "config/webapp_config.json", "auth_password".
[[install.check]]
name  = "Sign-in password"
command = ["{python}", "-m", "src.password", "status"]
hint  = "set one with: .venv\\Scripts\\python.exe -m src.password set"

[[install.check]]
name  = "HTTPS certificate"
paths = ["webapp/certificates/cert.pem", "webapp/certificates/key.pem"]
hint  = "run: .venv\\Scripts\\python.exe scripts\\gen_tailscale_cert.py"

[[install.check]]
name  = "GitHub CLI"
which = "gh"
```

A malformed table fails the run before any step, naming the key.

## Adopting it

1. Vendor `src/installer.py` and list it under `[vendored]` in the app's `.fleet.toml`. An older entry script that ran the installer is deleted: `setup.bat` runs the module directly.
2. Copy `scripts/templates/setup.bat` to `setup.bat` at the repo root. An app that already has a `setup.bat` with extra steps (another installer it offers, a closing banner) keeps them after the `src\installer.py` line.
3. Declare the `[install]` table. Keep every config's sample tracked and its target gitignored, and add `*.json.bak-*` to `.gitignore`: a rule written for the config (`config/*.json`, or the file's own name) does not match `config.json.bak-<stamp>`, and without the line every top-up is refused. A check or autostart that lives in the app's own code gets a small command-line entry that exits 0, 1 or another code, as above.
4. Copy `docs/templates/install-playbook.md` to `docs/install-playbook.md`, fill each placeholder and delete the lines that do not apply. The migrate section names the app's own configs, state and certificates; it never deletes the old copy, which is retired only after the owner confirms.
5. Link the playbook from the README's install section.

## The top-up can change behaviour

A top-up never changes a value that is there, yet it can still change what the app does. A key the config lacked was running on the code's default; the top-up writes the sample's value, so a sample value that differs from the code default (a feature flag set to `true` in the sample, a different port or interval) switches behaviour on the next start. A new key that takes precedence over an older one the app still honours has the same effect. Keep each sample value equal to the code default, or give the app a test that tops up an older config and asserts nothing it already did changes.
