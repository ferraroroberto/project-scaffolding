# Personal data ratchet

`scripts/personal_data_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It reads every tracked text file, counts findings of personal data per file and rule, and **fails when a file's count for a rule rises** above the committed baseline. Existing debt never blocks work; it cannot grow either.

It exists for repositories that are shared with other people: absolute local paths, a personal email address, the owner's GitHub handle used as a default and the names of private apps are cheap to write and hard to notice in review. It catches that kind of leak. It is not a secret scanner, and a pass says nothing about git history.

It has the shape of the other ratchets ([adopting-ratchets.md](adopting-ratchets.md)): an opt-in `.fleet.toml` table, named rules, a committed baseline, the same flags, and exit 3 for "not confirmed". It is one stdlib-only file beside the shared `ratchet_baseline.py`.

**The output never quotes what it found.** A finding is the file, the line and the rule, because gate logs get copied into pull requests and CI. A listed term inside a printed path or exemption reason is masked as `***`. The baseline holds paths and counts only.

## Pattern rules

These need no setup and always run.

### `user-path`

An absolute local user or checkout path:

- a drive letter followed by a users root, then a name: `<drive>:\Users\<name>`;
- a drive letter followed by a projects root, with or without anything after it. The roots are `project`, `projects`, `automation`, `code`, `dev`, `repo`, `repos`, `git`, `github`, `src`, `work` and `workspace`, directly under the drive;
- the POSIX forms: `/home/<you>`, `/Users/<you>`, and the same roots through a Git Bash (`/c/...`) or WSL (`/mnt/e/...`) mount.

Separators may be `\`, `\\` (an escaped string) or `/`.

The segments `<root>`, `<you>`, `me`, `you` and `sample` are placeholders and never a hit. Under a users root, a segment that names nobody (`%USERNAME%`, `$USER`, `{user}`, `...`, or nothing at all) is not a hit either. A projects root is itself the checkout path, so only a placeholder right after it clears it. A URL path (`https://host/home/page`) and a path after an interpolated base (`{base}/home/page`) are not read as local paths.

### `personal-email`

Any email address outside the reserved example domains: `example.com`, `example.net`, `example.org` and their subdomains, and the `.example`, `.test`, `.invalid` and `.localhost` endings. Not addresses: a `git@host` clone URL, a `user@host:path` copy target, an image density name such as `icon@2x.png`, a version pin, an escaped newline before a decorator in a string literal.

### `handle-default`

The owner's GitHub handle used as a value: an assignment, a default, a comparison or an argument, in code or a config sample. The handle is the owner segment of the `origin` remote, plus the term list's `handles`, so no tracked file has to name it.

Read: files ending `.py`, `.ps1`, `.psm1`, `.bat`, `.cmd`, `.sh`, `.js`, `.mjs`, `.cjs`, `.ts`, `.json`, `.toml`, `.yml`, `.yaml`, `.ini`, `.cfg` or `.env`, and any file whose name holds `.sample`, `.example` or `.template`.

Not a hit: the handle inside a URL or clone address, an issue reference (`owner/repo#<number>`), a full-line comment, a block comment, a Python docstring, or any document such as a `.md` file.

With no GitHub `origin` and no listed handle the rule has nothing to look for and is `unknown`.

### `bare-exempt`

A `<rule>-exempt` marker with no reason on a line that has a finding. It exempts nothing and is itself a hit.

## Term rules

Names that no pattern can find come from a machine-local term list.

| Rule | Term list key | Holds |
|---|---|---|
| `term-name` | `names` | people's names |
| `term-handle` | `handles` | account handles |
| `term-email` | `emails` | email addresses |
| `term-domain` | `domains` | personal domains |
| `term-app` | `apps` | private app and repository names |

Every text file is read, comments and documents included. Matching ignores case and does not match inside a longer word; `_`, `-` and `.` separate words, so a term `acme-tool` is found in `ACME-TOOL_DIR` and a term `acme` in `acme-tool`.

### The term list: location and format

The list is the file the `PERSONAL_DATA_TERMS` environment variable names, else `~/.config/personal-data/terms.toml`. It sits outside every repository, so one list serves every checkout and worktree on the machine and **it is never committed**. A list that `git` would commit from the scanned repository is refused as a configuration error.

It is TOML with one list of strings per key, each term three characters or more:

```toml
names   = ["Full Name"]
handles = ["account-handle"]
emails  = ["person@example.com"]
domains = ["personal-site.example"]
apps    = ["private-app-name"]
```

### Unknown is never a pass

A rule with no terms to read is reported `unknown`, and the run exits 3 even when nothing rose:

- no term list: every term rule is unknown;
- a key missing from the list: that rule is unknown. Write `apps = []` to declare there are none.

The pattern rules are enforced all the same, and a new pattern hit is still exit 1. A rewrite of the baseline (`--update-baseline`) keeps the entries of every unknown rule, since it could not measure them.

A machine without the list (CI, a teammate's clone) therefore fails the stage. Either give it a list through `PERSONAL_DATA_TERMS`, or narrow `rules` to the pattern rules in `.fleet.toml`; the rules left out are then printed as `OFF` on every run, which is a declared skip and not a clean result.

## Exempting one hit

Write `<rule>-exempt: <reason>` on the hit's line, or on the comment line right above it, in whatever comment syntax the file has:

```
# user-path-exempt: the fixed install path of a vendor's service
<!-- personal-email-exempt: the vendor's published support address -->
```

The marker covers only the rule it names. Every exemption is printed on every run. A format without comments (JSON) has no exemption; its hits stay in the baseline.

## Fixing a hit

- A path: derive it from the file's own location or an environment variable in code; write `<root>/<repo>` or `<drive>:\Users\<you>` in documents.
- An email: use an `example.com` address, or move the real one to ignored machine-local config.
- A handle default: read it from the repository context (in a workflow, `github.repository_owner`) or from ignored config.
- A term: reword. `repo-a` and `repo-b` stand in for private app names.

## What is not checked

- **Git history** and commit metadata.
- **Binary files** (images, PDFs, archives), including their metadata. The run prints how many files it did not read.
- **File names.** Only content is matched.
- **Other layouts.** A checkout under a root not listed above, or deeper than the drive's first folder, is not seen by `user-path`; add the folder name to the term list's `apps` if it identifies you.
- **A second hit on a counted line.** One finding per rule per line.

## Scope

Tracked and untracked-but-not-ignored files (`git ls-files --cached --others --exclude-standard`). Never read: `exclude` globs, `**/node_modules/**`, `**/.venv/**`, `**/venv/**`, the ratchet's own baseline, and every `[vendored]` `dest`, whose debt belongs to the repository it came from. A UTF-16 file with a byte order mark is read.

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | pass, or the table is absent or `enabled = false` |
| 1 | a file's count for a rule rose, the baseline is missing, or `--update-baseline` met an addition without `--allow-additions` |
| 2 | bad configuration, a malformed or committable term list, a malformed baseline, `--init` over an existing baseline |
| 3 | **not confirmed**: a rule is `unknown`, `git` could not list the tree, or a file cannot be read, is not UTF-8 text, or (Python, for `handle-default`) does not parse; the gate fails on it |

A new hit (1) outranks an unknown rule (3).

## The baseline file

`.ratchets/personal-data.json` (or `baseline`): a version and one entry per file with hits, the count per rule, sorted, with no line numbers and no matched text.

## Modes

- `python scripts/personal_data_ratchet.py`: check against the baseline.
- `--init`: write the first baseline; never overwrites. Run it on a machine that holds the term list, or the term hits are not recorded and later read as new.
- `--update-baseline`: drop gone hits; refuses additions.
- `--update-baseline --allow-additions`: also record new hits, which shows in review as added lines.

A write made while a rule is unknown still exits 3.

## Adopting it (opt-in per repo)

```toml
[personal_data_ratchet]
enabled  = true
baseline = ".ratchets/personal-data.json"  # default
rules    = ["user-path", "personal-email", "handle-default", "term-name", "term-handle", "term-email", "term-domain", "term-app", "bare-exempt"]  # default: all
exclude  = ["third_party/**"]              # globs; never scanned
```

Then `scripts/tools/adopt_ratchets.py <target> --ratchets personal_data` copies the script, records it under `[vendored]` and writes the first baseline, or do the same by hand ([adopting-ratchets.md](adopting-ratchets.md)).

The scaffold enables it for itself with the pattern rules only, so its gate needs no machine-local file.

## Tests

`tests/ratchets/personal_data/test_personal_data_ratchet.py`: each rule and each allowed placeholder on in-memory files; a planted term that fails and passes once removed; the no-list, missing-key and narrowed cases; every mode on a throwaway git repository; the not-confirmed exits; and this repository's own adoption. Every term, handle, address and path in it is invented.
