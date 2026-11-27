# Install, update and migrate <APP NAME>

<!-- Template: copy to docs/install.md in the app, replace every <ANGLE BRACKET> placeholder, and delete
     the lines that do not apply. Keep the three sections Install, Update and Migrate: the install standard
     ratchet fails a playbook without them. The installer and its [install] table: project-scaffolding
     docs/installer.md. -->

<APP NAME> installs, updates and migrates the way any app in the toolbox does: clone it and run one `setup.bat`. An update is a pull plus a restart. A migration, onto a fresh clone of the same PC or of another one, is one `setup.bat` call. None of them ever resets or overwrites what a PC has configured.

## Install

You need Windows 10 or 11, `git`, and Python 3.11 or newer (the `py` launcher, or `python` on `PATH`). <ANY EXTERNAL TOOL THE APP NEEDS, e.g. an agent CLI or Tailscale, with where to get it.>

```powershell
git clone <REPOSITORY URL>
cd <FOLDER>
.\setup.bat
<START COMMAND, e.g. .\tray.bat>
```

`setup.bat` runs `src/installer.py`, which:

1. creates `.venv` when it is missing;
2. installs `requirements.txt`, and later reinstalls only when that file changed (its hash is kept inside `.venv`);
3. <ONLY IF DECLARED: runs the dependency step, e.g. `npm ci`, again only when its inputs changed;>
4. creates each ignored config from its tracked sample when the config is missing;
5. ends with two lists: the required items, each `ok`, `missing` or `unknown`, and the optional features, each `available`, `off` or `unknown` with what it unlocks.

A required item that can be checked first (<e.g. the Python version>) stops the run before anything is installed. Setup has succeeded when it ends with `Setup complete` and exits 0; an optional feature that is `off` never changes that.

The optional features of <APP NAME>, each needed only for what it unlocks:

- <CHECKLIST ITEM, e.g. "Sign-in password", for remote sign-in: the command that sets it.>
- <CHECKLIST ITEM, e.g. "HTTPS certificate", for phone access: the command that issues it.>
- **Start at log on:** run `.\setup.bat -Startup`. <DELETE IF THE APP HAS NO AUTOSTART.>

`.\setup.bat -WhatIf` lists every change it would make and makes none.

### Uninstall

1. Turn off the log-on autostart: <HOW, e.g. delete <NAME>.bat from shell:startup>.
2. <ANYTHING ELSE THE APP REGISTERED OUTSIDE ITS FOLDER, e.g. scheduled tasks, hooks in another tool.>
3. Stop the app: <HOW>.
4. Delete the folder. Keep a copy of the files listed under "Migrate" first if you may want them back.

## Update

```powershell
git pull --ff-only
.\setup.bat
<RESTART COMMAND, e.g. .\tray.bat --restart>
```

`setup.bat` on a configured PC is safe, and it is how a new setting arrives:

- Settings files (<LIST THEM, e.g. config/config.json>): an existing value is never changed. A key the sample has and the file lacks is added, after a timestamped backup beside it (`<name>.json.bak-<YYYYmmdd-HHMMSS>`), and the added key names are printed. A file that does not parse is left alone and reported, and the run exits 1.
- Registries (<LIST THEM, e.g. config/apps.json>) are your own lists: created when missing, never rewritten or reformatted.
- A second run reports `unchanged` and writes nothing.

## Migrate

What moves is declared in `[install.migrate]` of `.fleet.toml`: <LIST THE APP'S CONFIGS, STATE AND CERTIFICATES, e.g. config/config.json, data/, webapp/certificates/, .env>. Its runtime data under <e.g. C:\sqlite\<app>> stays where it is and is shared. The installer does the whole move; nothing here or in `setup.bat` deletes the old copy.

**Reinstall in the same folder (the usual case).** It works whatever version the installed copy is, because it runs from a fresh clone and never runs the old copy's code. Run these in order from `<PARENT FOLDER>`, the folder that holds `<FOLDER>` (<DELETE FOR AN APP THAT HOSTS NO SESSIONS:> in a plain terminal, never a session <APP NAME> hosts, because the run stops <APP NAME> and every session in it):

```powershell
cd <PARENT FOLDER>
git clone <REPOSITORY URL> <FOLDER>.incoming          # a fresh clone beside the install; run nothing in it yet
.\<FOLDER>.incoming\setup.bat -Replace <FOLDER> -WhatIf   # read the backup name and every step; nothing changes
.\<FOLDER>.incoming\setup.bat -Replace <FOLDER>
```

It stops `<FOLDER>`, renames it to `<FOLDER>.bak-YYYYMMDD-N` (uncommitted edits stay there), moves `<FOLDER>.incoming` to `<FOLDER>`, migrates and passes only when the new clone serves its own commit. The path is unchanged, so <e.g. the launcher's app entry and the Startup link> need no edit. On an install whose `setup.bat` already has `-InPlace`, `.\<FOLDER>\setup.bat -InPlace` does the same and makes the clone itself.

**Beside it (another folder, or an old copy that is not a git clone):**

```powershell
git clone <REPOSITORY URL> <NEW FOLDER>
cd <NEW FOLDER>
.\setup.bat -MigrateFrom <OLD FOLDER> -StopOld
```

Only you can do these steps:

- **Repoint** whatever stores the old path, after a `-MigrateFrom` into another folder: the run lists what still points at it.
- **Fall back** if verify fails (the report names the step): stop the new copy, rename the new folder away and the backup to the original name, and start it; it is untouched.
- **Retire the backup** once you are sure the new copy works, by deleting it yourself. An agent working through this playbook asks you before it deletes anything.
