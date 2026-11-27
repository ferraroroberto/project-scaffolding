# Install standard ratchet

`scripts/install_standard_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It reads the repo and **fails when a piece of the fleet install standard is missing** that the committed baseline does not already list. Existing debt never blocks work; it cannot grow either.

It enforces the decision "Every app installs, reinstalls and migrates through the scaffold installer" in [architecture-decisions.md](architecture-decisions.md): `setup.bat` for a fresh install, `setup.bat -MigrateFrom <folder>` and `setup.bat -InPlace` (the in-place reinstall with a dated backup) all come from the one vendored [installer](installer.md), what moves is declared in `.fleet.toml`, and one playbook, `docs/install.md`, has an Install, an Update and a Migrate section. An app whose installer falls behind, whose migration table goes missing or whose playbook loses a section would need a hand-made workaround on the next move to another PC; the ratchet catches it in that app's own gate.

It has the shape of the other ratchets ([adopting-ratchets.md](adopting-ratchets.md)): an opt-in `.fleet.toml` table, named rules, a committed baseline, the same flags, and exit 3 for "not confirmed". It is one stdlib-only file plus the shared `ratchet_baseline.py`. It reads files only: it never runs `setup.bat`, starts the app or touches the network.

## The rules

### `installer-vendored`

One hit per installer module (`src/installer.py`, `src/installer_migrate.py`, `src/installer_declaration.py`, `src/installer_inplace.py`) that is:

- missing;
- not declared under its manifest key (`installer`, `installer_migrate`, `installer_declaration`, `installer_inplace`) in `[vendored]` (in this scaffold, which publishes them, `[components]`);
- not the scaffold's current content. The script carries the sha256 of each module as released with it, with CRLF read as LF so a Windows `autocrlf` checkout matches. The scaffold's own test fails until those values match its modules, so every installer change updates the ratchet in the same PR, and a re-vendor carries both together: an adopter that takes the new ratchet without the new installer goes red.

Fix: re-vendor the module byte for byte from project-scaffolding and record its `sha` under `[vendored]` (`/propagate-vendored installer_inplace` carries all four, through `requires`).

### `migrate-table`

`[install.migrate]` (with `[install.endpoint]`) is absent or does not parse. It is parsed by the repo's own `src/installer_migrate.py`, the code `setup.bat -MigrateFrom` runs, so the ratchet and the installer never disagree on what is valid; the hit prints the installer's own message, naming the key. With that module, or the `src/installer_declaration.py` it loads, missing the table cannot be parsed, which is a hit, not a pass. Fix: declare the tables ([installer.md](installer.md#migrating-an-existing-install)).

### `playbook-sections`

The playbook (`docs/install.md`, or `playbook`) is missing, or has no `## Install`, `## Update` or `## Migrate` heading. Headings inside code fences do not count; other sections (an Uninstall subsection, an Execution policy section) are allowed. One hit per missing section. Fix: copy `docs/templates/install-playbook.md` and fill it in, or rename the section to the standard title.

## What is not checked

- **That the installer works on this app.** Only the pieces are checked; proving a reinstall is an in-place run from a fresh clone on a disposable pair, done once per adopter in its propagation PR.
- **`setup.bat`.** It is copied once and may keep extra steps after the installer line, so its bytes are not compared.
- **What the Migrate section says.** Only that it exists. The template keeps it to the installer call plus the steps only the owner can do.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | pass, or the table is absent or `enabled = false` |
| 1 | a hit beyond the baseline, the baseline is missing, or `--update-baseline` met an addition without `--allow-additions` |
| 2 | bad configuration (unknown key, a `playbook` outside the repo, a value of the wrong type, `.fleet.toml` that does not parse), a malformed baseline, `--init` over an existing baseline |
| 3 | **not confirmed**: an installer module or the playbook cannot be read, or `src/installer_migrate.py` exists but does not load. The gate fails on it |

## The baseline file

`.ratchets/install-standard.json` (or `baseline`): a version and the sorted list of hits (`installer-vendored: src/installer.py`, `migrate-table`, `playbook-sections: docs/install.md ## Migrate`). It only shrinks on its own: a fixed hit prints a hint to run `--update-baseline`.

## Modes

- `python scripts/install_standard_ratchet.py`: check against the baseline.
- `--init`: write the first baseline; never overwrites.
- `--update-baseline`: drop fixed hits; refuses additions.
- `--update-baseline --allow-additions`: also record new hits, which shows in review as added lines.

## Adopting it (opt-in per repo)

```toml
[install_standard_ratchet]
enabled  = true
baseline = ".ratchets/install-standard.json"   # default
playbook = "docs/install.md"                    # default
```

Then `scripts/tools/adopt_ratchets.py <target> --ratchets install_standard` copies the script, records it under `[vendored]` and enables the table; run `--init`, or do the same by hand ([adopting-ratchets.md](adopting-ratchets.md)). An app that already follows [installer.md](installer.md) starts with an empty baseline.

The scaffold enables it for itself with `playbook` pointing at the template, so the template's three sections are held by the same rule adopters are. It is not an installable app, so its baseline lists its missing `[install.migrate]`.

## Tests

`tests/ratchets/installer/test_install_standard_ratchet.py`: the hashes match this scaffold's installer modules; every rule on a throwaway repo (a missing, undeclared and stale module, a CRLF copy that still matches, a missing and a malformed migration table, a missing playbook and section, a heading inside a fence); every mode; the not-confirmed exit for a module that does not load; and this repo's own adoption.
