# Dead code ratchet

`scripts/dead_code_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It parses every tracked Python file with the standard library's `ast`, collects each function, class and method, and fails when one that **nothing references** is not already recorded in the committed baseline. Existing debt never blocks work; it cannot grow either.

The [static ratchet](static-ratchet.md) already stops unused imports and locals (`ruff` `F401`/`F841`). A helper nobody calls, a class nothing builds and a handler that lost its route are what `/codebase-audit` keeps finding by hand. Telling them apart from code a framework calls takes a list of entry points, and that list is most of this stage.

It reuses the shape of the [doc references ratchet](doc-refs-ratchet.md): an opt-in `.fleet.toml` table, a committed baseline, the same flags, and exit 3 for "not confirmed". It is stdlib-only and imports nothing it scans.

## What counts as dead

A **definition** is any `def`, `async def` or `class`, at any depth: module functions, methods, nested functions (reported as `outer.inner`) and nested classes.

It is **referenced** when its name is read anywhere in the tracked Python tree, in any file, tests and excluded files included:

| Read as | Example |
|---|---|
| A bare name, in any position but an assignment target | `f()`, `cb=f`, `x: Model`, `isinstance(x, Model)` |
| An attribute, loaded or stored | `obj.f()`, `self.f`, `obj.prop = v` (a property setter runs) |
| An imported name | `from pkg.mod import f` (a re-export counts as use) |

Matching is **by name, not by binding**. A dead `close` hides behind any other `.close` in the repo, and a recursive function counts as calling itself. The stage misses dead code; it does not invent it. That is the trade for a gate stage that runs on every change without an agent confirming each hit.

## Entry points

Something outside the Python call graph runs these, so they are never reported:

| Entry point | Rule |
|---|---|
| Dunder names | `__init__`, `__repr__`, `__getattr__`, any `__x__` |
| A module's `__all__` | top-level names listed in the defining module's `__all__` |
| A decorated definition | the decorator's dotted name (call stripped: `@app.get("/x")` reads `app.get`) matches a built-in or `entry_decorators` glob |
| pytest and unittest | in a test module (`test*.py`, `*_test.py`, `conftest.py`): every `test*` function and method, `Test*` classes and `unittest.TestCase` subclasses (followed through the repo's own base classes); anywhere: top-level `pytest_*` hooks and the runner's set-up and tear-down names |
| A component's public API | in this scaffold, the top-level public names of every `[components]` file, because adopters call them |
| `allow` | globs over `<path>:<qualname>` |

The built-in decorator globs: route verbs and routing on any object (`*.get`, `*.post`, `*.put`, `*.patch`, `*.delete`, `*.head`, `*.options`, `*.trace`, `*.route`, `*.api_route`, `*.websocket`, `*.websocket_route`), FastAPI hooks (`*.on_event`, `*.exception_handler`, `*.middleware`), CLI and plugin registration (`*.command`, `*.group`, `*.callback`, `*.register`, `*.hookimpl`, `*.hookspec`, `*.listens_for`, `*.task`, `*.receiver`), pytest fixtures, pydantic validators, serializers and computed fields, and MCP server tools, resources and prompts (`*.tool`, `*.resource`, `*.prompt`).

Files under an adopter's `[vendored]` destinations are read for references but never reported: dead code in a vendored copy belongs to the repo it came from.

## Confidence

Each finding gets a confidence, and only findings at or above `min_confidence` count:

| Confidence | When |
|---|---|
| 100 | The name appears nowhere else |
| 60 | It may be reached dynamically: the name is an identifier-shaped string literal (`getattr(obj, "name")`, `"pkg.mod:func"`, a string annotation) or a call or attribute inside any other string (`"window.api.set_theme(x)"`, JavaScript a webview runs); a word in a tracked non-Python file (templates, scripts, JSON, YAML, TOML entry points; Markdown is left out because docs describe dead code as readily as live code); its module calls `getattr`/`hasattr`/`setattr`/`delattr` with a computed name, calls `globals()`, `locals()` or `vars()`, or defines a module `__getattr__`; or it is a method of a class whose base, followed through the repo's own classes, comes from outside the repo (`threading.Thread.run`, `logging.Handler.emit`, `HTMLParser.handle_starttag`) |

Docstrings never lower confidence. Bases that do not call a subclass on their own (`object`, `ABC`, `Generic`, `Protocol`, `NamedTuple`, `TypedDict`, `Exception`, the `Enum` family) keep it at 100.

The default floor is **100**. In the fleet dry run below, the 60 tier was nearly all framework overrides, so a lower floor floods the gate with false positives. Lower it for a one-off audit, not as a gate setting.

## Exit codes

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (no dead definition beyond the baseline), or the stage is **not enabled** | continues |
| `1` | A dead definition not in the baseline, or the baseline file is missing | fails |
| `2` | Bad `[dead_code_ratchet]` table, unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: `git` unusable, or a tracked `.py` file that cannot be read or does not parse (a syntax error, or bytes that are not valid in its declared encoding). The message names the file and line | fails |

Exit 3 is its own state and never folded into a pass. A file that does not parse may hold the only reference to a definition elsewhere, so skipping it would report live code as dead, or hide dead code behind a guess.

## The baseline file

Committed, sorted JSON, one source file per line, keyed by repo-relative path. It records the qualified names themselves, not a count, so deleting one dead helper and adding another still fails:

```json
{
  "version": 1,
  "entries": [
    {"key": "src/client.py", "names": ["Client.retry_later", "legacy_login"]}
  ]
}
```

There are no line numbers, so edits elsewhere in a file never churn it. Renaming a file that carries debt reads as a new file, resolved with `--allow-additions`.

## Modes

```
python scripts/dead_code_ratchet.py                                   # check (what the gate runs)
python scripts/dead_code_ratchet.py --init                            # first baseline; refuses to overwrite
python scripts/dead_code_ratchet.py --update-baseline                 # drop what is now referenced or gone; exit 1 + write nothing if anything was added
python scripts/dead_code_ratchet.py --update-baseline --allow-additions   # the explicit flag that adds entries
```

A failing check prints `<path>:<line>: <kind> `<qualname>` is never referenced (confidence <n>)`. The fix is to delete the definition or call it. A real entry point the rules miss (a framework hook called by name, a callback a template names) goes in `entry_decorators` or `allow`.

## Adopting it (opt-in per repo)

Re-vendoring the script never breaks a repo that has not opted in: an absent `[dead_code_ratchet]` table, or `enabled = false`, prints `dead code ratchet: not enabled` and exits 0 (declared, not inferred).

1. Vendor `scripts/dead_code_ratchet.py` byte-for-byte (`/propagate-vendored dead_code_ratchet`; manifest key `dead_code_ratchet`) and declare it in the repo's `[vendored]` table. It needs Python 3.11+ (`tomllib`) and `git`; it parses code with the running interpreter's grammar, so run it with the interpreter the project targets.
2. Add to the repo's own `.fleet.toml`:

   ```toml
   [dead_code_ratchet]
   enabled          = true
   baseline         = ".dead-code-ratchet-baseline.json"  # default
   include          = ["src/", "app/"]                    # path prefixes; default: the whole repo
   exclude          = ["src/generated/**"]                # globs; never reported, still read for references
   min_confidence   = 100                                 # default
   entry_decorators = ["bus.subscribe"]                   # globs over the decorator's dotted name
   allow            = ["custom_components/**/*.py:async_setup*"]  # globs over <path>:<qualname>
   ```

3. Declare every vendored copy in `[vendored]` first (an undeclared copy reports the vendor's unused API as yours). Then run `python scripts/dead_code_ratchet.py --init`, review the baseline, and commit it. Each entry is either dead code worth a follow-up deletion or an entry point worth an `allow` or `entry_decorators` line. **Adoption never requires the deletions first.**
4. Add a gate stage that runs `python scripts/dead_code_ratchet.py` and fails on any non-zero exit. The scaffold's `scripts/verify-before-ship.ps1` places it after the doc references ratchet and before `mypy`. **Do not path-route it**: deleting the last caller in one file strands a definition in another.
5. If the repo uses diff-proportionate e2e routing, add a `tier = "none"` rule for the baseline file to `.fleet.toml` `[e2e]` and a matching assertion in `tests/test_classify_e2e.py`.

The script spawns `git` with `CREATE_NO_WINDOW`, derived locally (it is vendor-verbatim, so it cannot import `src/no_window.py`), and with `GIT_OPTIONAL_LOCKS=0`. It shares its config, glob and baseline helpers with the sibling ratchets by copy, because each vendored file must be self-contained.

### Relation to the audit's dead-code leads

`/codebase-audit` runs vulture at its fixed 60 confidence over a repo and has an agent confirm each lead before filing it. That is an audit tool: broad, and checked by a reader. This stage is the gate side: it must be quiet enough to fail a change unattended, so it reports only what nothing names anywhere, and it needs no third-party install.

## Cost and measured hit rate

A read-only dry run with the default configuration (no `allow`, no `entry_decorators`, each repo's own `[vendored]` and `[components]`) over every fleet checkout (42 repos) finished without a "not confirmed" in 0.06 to 6 s per repo; as a gate stage here it adds about 0.9 s, interpreter start included.

| Floor | Hits | Repos | Really dead |
|---|---|---|---|
| 100 (default) | 60 | 21 | 50, every hit checked by hand with a whole-word `git grep` of its name and a read of the code where it was named elsewhere: unused client methods, helpers left after a refactor, test helpers nothing calls, a method commented "not called anywhere", unused storage utilities |
| 60 | 233 | 30 | A sample of 15 from the extra 173: about one in five. The rest are framework overrides (`handle_starttag`, `do_GET`, `log_message`, `emit`, Home Assistant entity methods) |

The 10 false positives at the default floor are what `allow` absorbs: 6 Home Assistant platform hooks (`async_setup`, `async_setup_platform`) called by convention, 1 duck-typed pytest protocol method on a repr object, 1 method of a vendored copy the repo had not declared, and the 2 scaffold functions adopters call from their own tree, which this repo lists in its own `allow`. Precision at the default floor is therefore 50 of 60, and 50 of 50 once those `allow` lines exist.

The first draft reported 504 hits. About 420 were `unittest.TestCase` subclasses named `*Tests`, then MCP server tools, pytest hooks in plugin modules, test modules named `test01_*.py`, `test_*` methods on mixins that test classes inherit, and a webview method called from JavaScript in a Python string. Each became a built-in rule above.

## Tests

`tests/ratchets/test_dead_code_ratchet.py`: detection on fixture sources (each kind of reference, nested qualnames, every entry-point rule, the component rule, each dynamic-use signal and the floor, docstrings, framework subclasses), scope, and every mode and exit code on throwaway git repos, including a newly added uncalled function failing by name, route handlers and exports passing, vendored and untracked files, and references from excluded files. A missing prerequisite is a hard failure there, never `pytest.skip`. The scaffold's own gate stage doubles as the guard that its committed baseline is current.
