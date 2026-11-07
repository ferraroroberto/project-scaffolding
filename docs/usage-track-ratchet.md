# Usage track ratchet

`scripts/usage_track_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It reads a web app's HTML and JS, counts each enabled rule's hits per file, and **fails when a file's count for a rule rises** above the committed baseline. Existing debt never blocks work; it cannot grow either.

It holds the decision that every UX control is tracked in the usage log ([architecture decisions](architecture-decisions.md), "Every UX control is tracked in usage-log"):

> every interactive control carries a constant tracking id; every sheet, dialog and drawer records its view on open and returns to the previous view on close, so time-spent stays exact; every fleet web app initialises `usage-log` and mounts its routes; ids are constants, never built from content.

The usage log only sees what the markup names. A tap on a control with no `data-track` is invisible to a design review; a sheet that records no view bills its minutes to the tab under it; an id built from content breaks the privacy contract (`docs/webapp-pwa-conventions.md`, "Usage log"). This stage makes each of those a gate failure the day it is written.

It has the shape of the [conventions ratchet](conventions-ratchet.md): an opt-in `.fleet.toml` table, named rules, a committed baseline, the same flags, and exit 3 for "not confirmed". Only its perimeter differs: HTML and JS instead of Python. It is stdlib-only and imports nothing it scans.

## The rules

Each rule is opted into by name in `rules`. The first three are counted per file against the baseline; `usage-log-wired` is a fact about the repo and is never baselined.

### `untracked-control`

> every interactive control carries a constant tracking id

A **control** is:

- a `<button>`, `<summary>` or `<select>`;
- an `<input>` of type `button`, `submit`, `reset`, `checkbox`, `radio` or `image`;
- any element whose `role` is `button`, `tab`, `menuitem`, `menuitemcheckbox`, `menuitemradio`, `switch`, `checkbox`, `radio` or `option`;
- an `<a>` that acts as a button: `href` of `#...` or `javascript:`, or a control `role`.

A navigation `<a href>`, a text `<input>` and passive text (the page foot, a label) are not controls.

A control is **tracked** when:

- it carries `data-track` itself;
- the nearest ancestor carrying `data-track`, which is the id the client's `closest('[data-track]')` records, is itself a control or has a grouping role (`group`, `radiogroup`, `tablist`, `toolbar`, `menu`, `menubar`, `listbox`). One id on a segmented control covers its segments. A `data-track` on a plain `<div>`, `<dialog>` or `<main>` covers nothing, so one attribute on `<main>` cannot pass a whole page;
- it is a nav tab: `data-tab` inside a `<nav>`. The nav's `onChange` records the tab as a view, so it is not a tap.

In JS, a control is held to the same rule in three places:

1. **A string or template literal** that holds markup (`innerHTML = '<button ...>'`, a template that renders a row). The literal is read as HTML, with each `${...}` hole read as `${}`, and the tag needs its own `data-track="<id>"`.
2. **`document.createElement`**. The variable it is assigned to gets `x.dataset.track = '<id>'` or `x.setAttribute('data-track', '<id>')` later in the same block, nested blocks included. Its tag, a `type` (an `<input>`), a `role` or an `href` (an `<a>`) set the same way decide whether it is a control at all. A tie in another function, after the element was returned, is not seen: declare the helper as a builder, or add the marker.
3. **A declared builder.** A helper that builds controls for its callers is listed in `builders` as `<file>:<function name>`. Every call to it passes an object literal with a `track:` key (or `'data-track':`), and the builder's own body is trusted to pass that id through:

   ```js
   // row.js, declared as "app/webapp/static/row.js:row"
   export function row(opts = {}) {
     const main = document.createElement('button');
     if (opts.track) main.dataset.track = opts.track;
     return main;
   }
   row({ label: 'Lights', track: 'lights.toggle' });   // passes
   row({ label: 'Lights' });                            // untracked-control
   ```

A click handler that calls `usage.track(...)` is **not** a tie: that call is for "a feature succeeded" events, not for taps.

### `untracked-sheet`

> every sheet, dialog and drawer records its view on open and returns to the previous view on close

A hit is a `<dialog>`, in HTML, in a JS string or from `createElement('dialog')`, without `data-track-view="<id>"`. The check is pure markup because the vendored client does the rest: `usage-log.js` watches the `open` attribute of every element carrying `data-track-view` (`showModal()`, `show()` and `close()` all toggle it), records the sheet's id as the view when it opens, and returns to the view under it when it closes or leaves the document. Open sheets stack, so a sheet opened from a sheet hands back to its parent. No opener has to call `trackView`, so a new sheet cannot forget to.

### `dynamic-id`

> ids are constants, never built from content

Every tracking id must be a string literal matching the id pattern (`^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$`), or a name bound to a module-level `const` string literal. Checked are:

- a `data-track` or `data-track-view` attribute in HTML or in a JS literal (a Jinja `{{ ... }}`, a `${...}` hole or a value outside the pattern is a hit);
- `x.dataset.track =` / `x.dataset.trackView =` values and `setAttribute('data-track' | 'data-track-view', ...)` values;
- the argument of every `.track(...)` and `.trackView(...)` call (a call with no argument is another API's `track()` and is not read);
- a builder caller's `track:` value.

A parameter, a property (`e.detail.tab`), a concatenation, a table lookup or a local `const` is a hit. Passing the function by reference (`onChange: usage.trackView`) is not a call and is fine. A fixed lookup table of literal ids keeps its exception with a marker naming the table.

### `usage-log-wired`

> every fleet web app initialises `usage-log` and mounts its routes

A repo-level check, never baselined, run in the check mode only: it passes when `[vendored]` declares both `usage-log` (the client) and `usage_log` (the server), a file in `paths` calls `initUsageLog(`, and a tracked Python file (vendored copies and tests aside) calls `usage_router(`. The one vendored file that counts is the Starlette adapter, when `[vendored]` declares `usage_log_starlette` and its file calls `usage_router(`: an app without FastAPI mounts the log through it and has no call of its own. Each missing piece is printed on its own line and fails the gate, whatever the baseline says. Like the structure ratchet's root layout, it cannot be baselined away.

A repo declares itself a web app by enabling this table; the table is the declaration. The fleet-wide cross-check that every repo whose `## UX surface` says `design spec applies: yes` has it enabled belongs to `fleet-config`'s drift test, not to this stage.

### Exempting one hit

A hit that must stay keeps a reasoned marker on one of its own lines, or in the comment block directly above it:

```html
<!-- untracked-control-exempt: decorative copy button, the copy itself is tracked -->
<button class="copy">Copy</button>
```

```js
// dynamic-id-exempt: ids come from the fixed TAP_IDS table of literals
btn.dataset.track = TAP_IDS[state];
```

The marker names one rule (`<rule>-exempt`) and needs text after it. A bare `<!-- untracked-control-exempt -->` exempts nothing, a marker for another rule does not cover this one, and a comment trailing code on the line above is not part of the block.

## What is not checked

The exemptions the decision names are out of scope by construction: Streamlit spikes have no HTML or JS here, public static sites under `design.web.md` live outside the default `paths` (and do not enable the table), and passive text is not a control.

The rules are lexical, so these false negatives remain:

- a control built from a computed string (`innerHTML = tag`, a string concatenated across literals);
- a third-party widget's own markup (exclude it with `exclude`);
- an overlay that is not a `<dialog>` (a popover, a class-toggled drawer) and a sheet already open in the markup at load;
- a tie made in another function than the `createElement`, unless the helper is a declared builder.

## Scope

Every `.html`, `.htm`, `.jinja`, `.jinja2`, `.j2`, `.js` and `.mjs` file git lists (tracked, or untracked and not ignored) under the `paths` globs (default `app/webapp/static/**` and `app/webapp/templates/**`), except:

- files under the repo's `[vendored]` destinations: a vendored copy's debt belongs to the repo it came from;
- files under a `tests/` or `test/` folder;
- the `exclude` globs, plus `node_modules`, `.venv`, `venv` and `*.min.js` anywhere.

An inline `<script>` (no `src`, a JavaScript or module type) is read as JS on its own lines. The wiring rule also reads tracked `.py` files for `usage_router(`. A baseline, this stage's or any other ratchet's, is JSON and is never read as a hit or as evidence about one.

## Exit codes

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (no rule count above the baseline, the wiring present when enabled), or the stage is **not enabled** | continues |
| `1` | A file's count for a rule rose, the app does not reach its usage log, or the baseline file is missing | fails |
| `2` | Bad `[usage_track_ratchet]` table (unknown key or rule, no rules or paths, a malformed or missing builder), unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: `git` unusable, a file that cannot be read or is not UTF-8, or JS whose string, template, comment or braces never close. The message names the file and line | fails |

Exit 3 is its own state and never folded into a pass. HTML is always read through (`html.parser` recovers from anything), but JS that does not close leaves the scope of every later token a guess, so the stage refuses to call it clean.

## The baseline file

Committed, sorted JSON, one source file per line, keyed by repo-relative path, counting hits per rule:

```json
{
  "version": 1,
  "entries": [
    {"key": "app/webapp/static/index.html", "counts": {"untracked-control": 12, "untracked-sheet": 3}}
  ]
}
```

There are no line numbers, so edits elsewhere in a file never churn it. A fix and a new hit of the same rule in the same file cancel out; that is the accepted trade for a baseline that does not churn. `usage-log-wired` is never in it: a baseline that names it is refused (exit 2).

## Modes

```
python scripts/usage_track_ratchet.py                                   # check (what the gate runs)
python scripts/usage_track_ratchet.py --init                            # first baseline; refuses to overwrite
python scripts/usage_track_ratchet.py --update-baseline                 # drop hits now gone; exit 1 + write nothing if anything was added
python scripts/usage_track_ratchet.py --update-baseline --allow-additions   # the explicit flag that adds entries
```

A failing check prints every hit of the risen rule in the file, as `<path>:<line>: [<rule>] <message>`, under a `<path>: [<rule>] <n> hit(s), baseline <m>:` header.

## Adopting it (opt-in per repo)

Re-vendoring the script never breaks a repo that has not opted in: an absent `[usage_track_ratchet]` table, or `enabled = false`, prints `usage track ratchet: not enabled` and exits 0.

1. Vendor `scripts/usage_track_ratchet.py` and its sibling reader `scripts/usage_track_scan.py` byte-for-byte (`python scripts/adopt_ratchets.py <repo> --ratchets usage_track` from a scaffold checkout copies and declares them, see [adopting-ratchets.md](adopting-ratchets.md); inside the fleet, `/propagate-vendored usage_track_ratchet,usage_track_scan`; manifest keys `usage_track_ratchet` and `usage_track_scan`), together with the current `usage-log` client, whose sheet watch the `untracked-sheet` rule relies on. Declare all three in `[vendored]`. The ratchet loads the sibling by path and exits 3 when it is missing. It needs Python 3.11+ (`tomllib`) and `git`.
2. Add to the repo's own `.fleet.toml`:

   ```toml
   [usage_track_ratchet]
   enabled  = true
   baseline = ".usage-track-ratchet-baseline.json"           # default
   rules    = ["untracked-control", "untracked-sheet", "dynamic-id", "usage-log-wired"]
   paths    = ["app/webapp/static/**", "app/webapp/templates/**"]  # default
   exclude  = ["app/webapp/static/vendor/**"]                 # third-party code
   builders = ["app/webapp/static/row.js:row"]                # control builders, if any
   ```

   A fleet web app lists all four rules.
3. Run `python scripts/usage_track_ratchet.py --init`, review the baseline and commit it. **Adoption never requires the fixes first.**
4. Add a gate stage that runs `python scripts/usage_track_ratchet.py` and fails on any non-zero exit. The scaffold's `scripts/verify-before-ship.ps1` places it after the runtime write ratchet and before `mypy`. **Do not path-route it**: it is cheap, and the wiring rule must see the whole tree.
5. Only if the repo uses this scaffold's diff-proportionate e2e routing ([e2e-routing.md](e2e-routing.md)), add a `tier = "none"` rule for the baseline file to `.fleet.toml` `[e2e]` and a matching assertion in its `test_classify_e2e.py`.
6. Burn the baseline down: give each control its id and each `<dialog>` its `data-track-view`, then lower it with `--update-baseline`. Remove any hand-written `trackView` call for a sheet at the same time; the client now records it.

The script spawns `git` with `CREATE_NO_WINDOW`, derived locally (it is vendor-verbatim, so it cannot import `src/no_window.py`), and with `GIT_OPTIONAL_LOCKS=0`. It shares its config, glob and baseline helpers with the sibling ratchets by copy, because each vendored ratchet must be self-contained. Its HTML and JS readers (an `html.parser` subclass and a small JS tokenizer) live in `usage_track_scan.py`, which keeps both files under the structure limits, the same split as `structure_layout.py` beside the structure ratchet.

## Cost and measured hit rate

A read-only dry run over three fleet web apps, every HTML and JS file outside vendored copies, tests and third-party folders, finished without a "not confirmed" in 0.3 to 0.6 s per repo:

| Repo | `untracked-control` | `untracked-sheet` | `dynamic-id` | `usage-log-wired` |
|---|---|---|---|---|
| app-launcher | 357 | 40 | 4 | passes |
| home-automation | 254 | 51 | 3 | passes |
| voice-transcriber | 11 | 4 | 1 | passes |

Checked by hand: every `dynamic-id` hit and a sample of 14 JS control hits. The `dynamic-id` hits are a fake-click probe with a runtime `data-track`, a table lookup, a concatenated id, a builder's pass-through (resolved by declaring the builder) and the nav wiring `trackView(tab)` in each app (rewritten to pass `usage.trackView` by reference, or a marker). An earlier draft also flagged `placement.track()`, a positioning API, which is why a call with no argument is not read. The JS control sample was all true hits: buttons and summaries built with `createElement` and never given an id, and one `role="option"` list item. No false-positive kind remains that needs more than a marker.

The scaffold runs the three markup rules over its own component tree with a committed baseline (the component gallery and the copy-in markup fragments).

## Tests

`tests/ratchets/test_usage_track_ratchet.py`: for each rule, a seeded violation that fails by name and the compliant form that passes, in HTML, in JS strings and templates (escaped quotes, holes) and from `createElement` (ties in the block, in nested blocks and in another function, tag, type, role and href). Also covered: every control kind and the non-controls, tracked control and group parents versus a tracked plain container, nav tabs, inline scripts and their line numbers (CRLF included), module constants versus locals, parameters, lookups and references, declared builders and a missing one, exempt markers (a reason is needed, the marker must name this rule, a trailing comment is not a block), and exit 3 for JS that never closes. On throwaway git repos it runs a fixture app missing ids (fails by rule, file and line, then passes once the ids are added), every mode and exit code, the never-baselined wiring rule, vendored, excluded and test files, a new untracked file failing and an ignored one skipped, another ratchet's baseline never read as evidence, and exit 3 for an unreadable or non-UTF-8 file and an unusable `git`, in every mode.

The client half is held by `tests/usage_log/test_usage_log_time_spent.py`, which drives the real `usage-log.js` through a scripted day and replays its sends into the real server, so a client change that breaks the time-spent minutes fails there, and by `tests/e2e/test_vendored_usage_log.py`, which proves the sheet stack with real `showModal()`, `close()` and `remove()` in a browser.
