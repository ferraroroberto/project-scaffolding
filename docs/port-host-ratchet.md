# Port host ratchet

`scripts/port_host_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It reads the tracked scripts and code, finds port and machine-local host literals written outside the repo's config resolver and its samples, counts them per file and rule, and **fails when a file's count for a rule rises** above the committed baseline. Existing debt never blocks work; it cannot grow either.

It enforces the decision "A clean pull plus restart is the whole update" in [architecture-decisions.md](architecture-decisions.md): ports, hosts and other machine-local values live in an ignored config file (`config/*.json` or `.env`) with a tracked `*.sample` default, and code, scripts and `.bat` files read them through the repo's config resolver. A literal written anywhere else is a value some machine will one day edit in place, and that edit is what turns a plain `git pull --ff-only` into a conflict. It is the decision's first check; the second, that a start or restart leaves `git status` clean, is a separate stage.

It has the shape of the other ratchets ([adopting-ratchets.md](adopting-ratchets.md)): an opt-in `.fleet.toml` table, named rules, a committed baseline, the same flags, and exit 3 for "not confirmed". It is one stdlib-only file with no sibling. Every rule is a line-level pattern over source text, so the same tree gives the same answer on every machine.

## The rules

Every rule is on unless `rules` narrows the list.

### `port-literal`

A port number (1 to 65535, two to five digits) written in code:

- next to a host: `127.0.0.1:8445`, `localhost:8501`, `[::1]:8000`, `nas.tail1234.ts.net:5000`, any IPv4 with a port, and an interpolated host whose port is still literal (`f"https://{host}:8445"`, `${HOST}:8445`, `%HOST%:8445`);
- given to a port name: `PORT=8501`, `set "PORT=8465"`, `--port 8130`, `--port=8130`, `-Port 8445`, `-Ports "8465,8466"`, `DEFAULT_PORT = 8446`, `port: int = 8445`, `"port": 8000`, camelCase `webappPort = 8445`.

A name that only ends in the letters (`report`, `export`, `sport`) is not a port name. One hit per line, however many ports it lists.

### `host-literal`

A host that is only right on one machine or network: a private-LAN IPv4 (`10.x.x.x`, `172.16-31.x.x`, `192.168.x.x`), a CGNAT/tailnet IPv4 (`100.64-127.x.x`) or a `*.ts.net` name. Loopback, `0.0.0.0` and public addresses are the same everywhere and are not hits, and neither is a CIDR network (`100.64.0.0/10`, `10.0.0.0/8`), which names a range a trust check compares against rather than a host to reach.

### `bare-exempt`

A `port-host-exempt` marker with no reason. It exempts nothing and is itself a hit.

### Exempting one hit

Write `port-host-exempt: <reason>` on the hit's line or on the comment line right above it. A reasoned marker removes the line's hits from the count; every exemption is printed on every run. The usual reasons: an unroutable address used only to read the LAN route (`("10.255.255.255", 9)`), and the documented default of an external service the repo does not own.

## Fixing a hit

Move the value into the repo's config resolver, which reads the ignored machine-local file over its tracked sample, and read it from there:

- Python: `app_config.load().webapp_port` instead of `PORT = 8445`.
- `.bat` / `.cmd`: `for /f %%p in ('<the resolver's command line> port') do set "PORT=%%p"` instead of `set "PORT=8445"`.
- PowerShell: call the same resolver, or pass the value in as a parameter from the `.bat` that already read it.

Then list the resolver file in `resolvers` so its own defaults are not counted. A second instance of the app on the same machine (a full and a lite launcher side by side) then differs only in its ignored config.

## What is not checked

- **Config files.** `.json`, `.toml`, `.yml` and `.env` are not read: a tracked config file is either the sample (allowed) or a file that should be ignored, which `git status` and review catch, not a pattern.
- **Prose.** Full-line comments (`#`, `//`, `REM`, `::`), PowerShell `<# ... #>` and JS `/* ... */` blocks that open a line, and Python docstrings are skipped, so a docstring that says which port the hub listens on is not a hit. A trailing comment on a code line is read with the line.
- **Hostnames.** A machine's own name (`DESKTOP-1234`, `nas`) has no shape that tells it from any other word, so only tailnet names and private addresses are found.
- **Built values.** A port computed from other literals (`BASE + 1`) or read from a non-port name (`listen_on = 8445`) is not found.

## Scope

Tracked and untracked-but-not-ignored files (`git ls-files --cached --others --exclude-standard`) ending `.py`, `.ps1`, `.psm1`, `.bat`, `.cmd`, `.sh`, `.js`, `.mjs`, `.cjs` or `.ts`. Never read:

- the files `resolvers` lists (globs): the config resolver owns the defaults;
- sample files: any name holding `.sample` or `.example` (`config.sample.py`, `ports.example.ps1`);
- tests, unless `include_tests = true`: a file under a `tests/` folder, `test_*.py`, `*_test.py`, `*.test.js`, `*.spec.js`, `*.test.ts`, `*.spec.ts`. A test booting a disposable instance on a fixed port is not a machine-local value;
- `exclude` globs, `**/node_modules/**`, `**/.venv/**`, `**/venv/**` and every `[vendored]` `dest`; a vendored copy's debt belongs to the repo it came from.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | pass, or the table is absent or `enabled = false` |
| 1 | a file's count for a rule rose, the baseline is missing, or `--update-baseline` met an addition without `--allow-additions` |
| 2 | bad configuration (unknown key, unknown rule, a value of the wrong type), a malformed baseline, `--init` over an existing baseline |
| 3 | **not confirmed**: `git` could not list the tree, or a file cannot be read, is not UTF-8, or (a Python file) does not parse; the gate fails on it |

## The baseline file

`.port-host-ratchet-baseline.json` (or `baseline`): a version and one entry per file with hits, the count per rule, sorted, no line numbers, so a diff reviews cleanly. It only shrinks on its own: a gone hit prints a hint to run `--update-baseline`.

## Modes

- `python scripts/port_host_ratchet.py`: check against the baseline.
- `--init`: write the first baseline; never overwrites.
- `--update-baseline`: drop gone hits; refuses additions.
- `--update-baseline --allow-additions`: also record new hits, which shows in review as added lines.

## Adopting it (opt-in per repo)

```toml
[port_host_ratchet]
enabled       = true
baseline      = ".port-host-ratchet-baseline.json"  # default
rules         = ["port-literal", "host-literal", "bare-exempt"]  # default: all
resolvers     = ["src/app_config.py"]              # globs; the files that own the defaults
include_tests = false                              # default
exclude       = ["scripts/bench/**"]               # globs; never scanned
```

Then `scripts/tools/adopt_ratchets.py <target> --ratchets port_host` copies the script, records it under `[vendored]` and writes the first baseline, or do the same by hand ([adopting-ratchets.md](adopting-ratchets.md)). List the resolver before the first `--init`, so its defaults never enter the baseline. The scaffold enables it for itself; it has no config resolver, so it lists none and its baseline holds its launcher and probe defaults.

## Tests

`tests/ratchets/test_port_host_ratchet.py`: each rule on in-memory files, including the launcher defaults a side-by-side machine had to edit by hand (a `.bat` port, a session-host port, a tray reclaim list) and the prose, network and loopback cases that must stay clean; the perimeter; every mode on a throwaway git repo; the not-confirmed exits; and this repo's own adoption.
