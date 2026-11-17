# UX surface ratchet

`scripts/ux_surface_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It reads a web app's HTML and JS and its [UX surface map](ux-surface-map.md), counts each rule's hits per file, and **fails when a file's count for a rule rises** above the committed baseline. Existing debt never blocks work; it cannot grow either.

It holds the convention that the map and the code name the same surfaces:

> each surface root carries the same id as a constant `data-surface="<id>"`, and a surface's entry and its attribute appear and disappear together.

The map is only useful while it is complete. A surface added without an entry, an entry left behind when its surface goes, or one id on two surfaces each make the map wrong without anyone noticing; this stage makes each of them a gate failure in the PR that causes it.

It has the shape of the [usage track ratchet](usage-track-ratchet.md): an opt-in `.fleet.toml` table, named rules, a committed baseline, the same flags, and exit 3 for "not confirmed". It reads JS through that ratchet's tokenizer, `scripts/usage_track_scan.py`, so the two read strings, templates, comments and blocks the same way; it is stdlib-only and imports nothing it scans.

## The rules

Every rule is on unless `rules` lists a subset, and every rule is counted per file against the baseline: a code rule against the HTML or JS file, a map rule against the map.

### `unmarked-surface`

An element that is a surface by its markup, with no `data-surface`:

- a `<dialog>`;
- an element whose `role` is `dialog`, `alertdialog`, `menu` or `tabpanel`;
- an element with a `popover` attribute.

It is read in HTML (inline scripts included), in a JS string or template literal that holds markup, and from `document.createElement`: the variable it is assigned to is a surface root when its tag is `dialog`, or when `x.setAttribute('role', ...)`, `x.role =`, `x.setAttribute('popover', ...)` or `x.popover =` gives it one of the above later in the same block; it is marked when `x.dataset.surface =` or `x.setAttribute('data-surface', ...)` follows in that block.

Screens, drill-ins and states are surfaces too, but nothing in their markup says so: they are held by the map and by the live walk (below), not by this rule.

### `invalid-surface-id`

Every surface id is a string literal matching `^[a-z0-9]+(?:[.-][a-z0-9]+)*$` (the e2e capture hook's name form), or a name bound to a module-level `const` string literal. Checked are a `data-surface` attribute in HTML or in a JS literal (a `${...}` hole or a Jinja `{{ ... }}` is a hit), `x.dataset.surface =` and `setAttribute('data-surface', ...)` values, and the id of every map entry.

### `unmapped-surface`

An id the code declares that no map entry lists. The hit is on the code line: add the entry, or drop the attribute with the surface.

### `stale-entry`

A map entry whose id no element in the code carries. The hit is on the map line: remove the entry with its surface, or, for a surface that has no element of its own (a gesture, a key, a state drawn inside another surface), say so with `*Root:* none — <reason>`. A bare `none` with no reason still counts.

### `duplicate-surface`

An id declared on more than one element in the code, or listed by more than one map entry. Every site counts, so both copies are named. A surface drawn twice on purpose (one root for the mouse popover, another for the phone sheet) keeps one id and excepts the second root with `duplicate-surface-exempt: <reason>`.

## What it reads

- **Code:** every tracked or untracked-but-not-ignored file under `paths` with an HTML suffix (`.html`, `.htm`, `.jinja`, `.jinja2`, `.j2`) or a JS one (`.js`, `.mjs`), outside `exclude`, test folders, `node_modules`, `.venv`, `*.min.js` and every `[vendored]` destination. A surface a vendored component builds is stamped by the app's call site, which is scanned.
- **The map:** the file named by `map`. An entry is a line that opens with a bold backticked id (`**\`today.row-menu\` Row menu**`, optionally as a list item), outside fenced code blocks, and runs until the next entry or heading. Prose between entries is ignored.

## Exceptions

A single hit keeps its exception with a `<rule>-exempt: <reason>` comment (`//` in JS, `<!-- -->` in HTML and in the map) on the hit's own line or in the comment block right above it. A marker with no reason exempts nothing.

## Configuration

```toml
[ux_surface_ratchet]
enabled  = true
baseline = ".ux-surface-ratchet-baseline.json"            # the default
map      = "docs/ux-surface-map.md"                        # the default
rules    = ["unmarked-surface", "invalid-surface-id", "unmapped-surface", "stale-entry", "duplicate-surface"]  # the default: all
paths    = ["app/webapp/static/**", "app/webapp/templates/**"]  # the default
exclude  = ["app/webapp/static/vendor/**"]
```

## Running it

| Command | What it does |
|---|---|
| `python scripts/ux_surface_ratchet.py` | Check: what the gate runs. |
| `--init` | Write the first baseline. Never overwrites an existing one. |
| `--update-baseline` | Lower or drop entries. Refuses, and writes nothing, while anything rose. |
| `--update-baseline --allow-additions` | Raise or add entries; shows in review. |

| Exit | Meaning |
|---|---|
| 0 | Pass, or the stage is not enabled |
| 1 | A count rose, the map is missing, or the baseline is missing |
| 2 | Bad configuration, baseline or arguments |
| 3 | **Not confirmed**: `git` could not list the tree, a file could not be read or is not UTF-8, or a JS source's strings, comments or braces do not close. Fails the gate; never a pass |

A missing map is not baselined: an app that enables the stage copies `docs/templates/ux-surface-map.md` first.

## Adopting it

1. Vendor `scripts/ux_surface_ratchet.py` and `scripts/usage_track_scan.py` (manifest keys `ux_surface_ratchet` and `usage_track_scan`) and add the stage to the gate after the usage track ratchet.
2. Copy the template to `docs/ux-surface-map.md` and walk the app ([Starting a map](ux-surface-map.md#starting-a-map)).
3. Add the table, run `--init`, and commit the baseline: today's unmarked roots, unmapped ids and stale entries go in as debt.
4. Burn it down: each `data-surface` added with its entry lowers a count; `--update-baseline` records it.

## Limits

- It sees surfaces that are surfaces by their markup, and every surface that already carries an id. A screen, drill-in or state built without `data-surface` and without an entry is invisible to it; the design-review and e2e walk is the cross-check that reports a surface it opened with no id.
- A `createElement` root marked in another function, after it was returned, is not seen: mark it where it is built, or except it with a reason.
- It holds ids, not contents: it does not check that an entry's *Holds* or *Does* still matches the controls on the surface.
