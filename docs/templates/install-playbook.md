# Install, update and move <APP NAME>

<!-- Template: copy to docs/install-playbook.md in the app, replace every <ANGLE BRACKET> placeholder, and delete
     the lines that do not apply. The installer and its [install] table: project-scaffolding docs/installer.md. -->

<APP NAME> moves to another Windows PC the way any app in the toolbox does: clone it and run one `setup.bat`. An update is a pull plus a restart. Neither ever resets or overwrites what a PC has configured.

## What you need

- Windows 10 or 11, `git`, and Python 3.11 or newer (the `py` launcher, or `python` on `PATH`).
- <ANY EXTERNAL TOOL THE APP NEEDS, e.g. an agent CLI or Tailscale, with where to get it.>

## Fresh PC

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

## Migrate from an existing install

Use this on a PC that already runs an older copy of <APP NAME>: one that may not be a git clone, and may live at another path. The old copy keeps running until the new one is verified, and it is deleted only when you say so.

1. **Clone fresh beside it.** Clone into a new folder next to the old one (`git clone <REPOSITORY URL> <NEW FOLDER>`); never clone over the old folder.
2. **Copy this PC's own files across.** From the old folder into the new one, copy only these, keeping their relative paths (they are all gitignored, so nothing tracked is touched):
   - configs: <LIST, e.g. config/config.json, config/apps.json>
   - state: <LIST, e.g. data/, the runtime database folder if it lives in the repo>
   - certificates and secrets: <LIST, e.g. webapp/certificates/, .env>
3. **Top them up.** Run `.\setup.bat -WhatIf` in the new folder and read what it would change, then `.\setup.bat`. Settings files gain only the keys they lack; the values you copied stay as they were.
4. **Stop the old copy.** <HOW, e.g. quit the tray from its menu; remove the old copy's log-on autostart entry.>
5. **Start the new one.** <START COMMAND>, and `.\setup.bat -Startup` if it should start at log on.
6. **Verify it.** <WHAT TO CHECK, e.g. open the app, confirm the build line shows the new commit, run one real action.> If anything is wrong, stop the new copy and start the old one again: it is untouched.
7. **Retire the old folder, only after you confirm.** Nothing in this playbook or in `setup.bat` deletes the old copy. When you are satisfied, rename it first (for example `<OLD FOLDER>.retired`) and run on the new copy for a while; delete it yourself once you are sure. An agent working through this playbook asks you before it deletes anything.

## Uninstall

1. Turn off the log-on autostart: <HOW, e.g. delete <NAME>.bat from shell:startup>.
2. <ANYTHING ELSE THE APP REGISTERED OUTSIDE ITS FOLDER, e.g. scheduled tasks, hooks in another tool.>
3. Stop the app: <HOW>.
4. Delete the folder. Keep a copy of the configs, state and certificates listed under "Migrate" first if you may want them back.
