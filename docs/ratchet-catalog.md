# Ratchet catalog

Every rule every vendored ratchet enforces, grouped by what it protects, each with what it catches, a minimal bad and fixed snippet, whether it is on by default, and how to except one hit. Read it top to bottom to learn the system; open one section to look a rule up. A person and an agent read the same page.

The ratchets are the baseline-and-ratchet stages of the pre-ship gate: stdlib-only scripts in `scripts/` that measure one kind of debt and fail only when it grows. This page is the rule reference. The steps to bring them into a repository are in [adopting-ratchets.md](adopting-ratchets.md), the shared contract is in [architecture-decisions.md](architecture-decisions.md), and each ratchet's own page (linked in its section) holds its limits and procedure. Every rule below was derived from the scripts' own rule tables and the bad and fixed snippets were run against them; `tests/ratchets/test_ratchet_catalog.py` fails when a script gains or drops a rule this page does not list.

- [The mechanism in one screen](#the-mechanism-in-one-screen)
- [How to read an entry](#how-to-read-an-entry)
- [Code shape: structure](#code-shape-structure)
- [Comments and docs: comment, docs, doc references](#comments-and-docs)
- [Dead and duplicate code: dead code, static](#dead-and-duplicate-code)
- [Runtime safety: conventions, runtime write](#runtime-safety)
- [Agent instructions: instruction](#agent-instructions)
- [Usage tracking: usage track](#usage-tracking)
- [Exceptions and burn-down](#exceptions-and-burn-down)
- [Adoption order](#adoption-order)

## The mechanism in one screen

A ratchet **measures** one kind of debt, **records** today's count in a committed baseline, and **fails only when a count rises**. Existing debt never blocks work, and it cannot grow.

Each ratchet is off until the repository's `.fleet.toml` has a table for it with `enabled = true`. An absent table, or `enabled = false`, prints "not enabled" and exits 0: a declared skip, never an inferred one.

```toml
[comment_ratchet]
enabled  = true
baseline = ".comment-ratchet-baseline.json"   # the default; one baseline file per ratchet
include  = ["src/"]                            # path prefixes; the default is the whole tree
```

The first run writes the baseline. It is sorted JSON with one entry per line and no line numbers, so an edit above a finding never churns it:

```
$ python scripts/comment_ratchet.py --init
comment ratchet: wrote .comment-ratchet-baseline.json with 1 entr(ies), 1 finding(s)
```

```json
{
  "version": 1,
  "entries": [
    {"key": "src/billing.py", "count": 1}
  ]
}
```

A change that adds a finding fails by name, with the line and the fix:

```
$ python scripts/comment_ratchet.py
comment ratchet: 1 entr(ies) with MORE findings than the baseline:
  src/orders.py: 1 (baseline none -- not baselined)
      line 2: #77  | # retry once, added for #77
```

Paying debt down is a separate, visible step:

```
$ python scripts/comment_ratchet.py --update-baseline
comment ratchet: .comment-ratchet-baseline.json now has 0 entr(ies), 0 finding(s) (1 lowered or dropped, 0 raised or added)
```

| Command | What it does |
|---|---|
| (no flag) | Check: what the gate runs. Compares the tree with the baseline. |
| `--init` | Write the first baseline. Never overwrites an existing one. |
| `--update-baseline` | Lower or drop entries. Refuses, and writes nothing, while anything rose. |
| `--update-baseline --allow-additions` | The one flag that raises or adds entries. It shows in review as added baseline lines. |

| Exit | Meaning | Gate |
|---|---|---|
| 0 | Pass, or the ratchet is not enabled | passes |
| 1 | A count rose, or the baseline file is missing | fails |
| 2 | Bad configuration, baseline or arguments | fails |
| 3 | **Not confirmed**: the check could not run (a tool, sibling module or file missing, `git` unusable). Its own state, never folded into a pass | fails |

A check that is switched off (`duplicates = false`, a runtime probe with no test command) prints **OFF**, never "clean". `scripts/run_ratchets.py` runs every enabled ratchet in stage order: static, comment, docs, structure, instruction, doc references, dead code, conventions, runtime write, usage track.

## How to read an entry

- **Default** says whether the rule counts as soon as its ratchet is enabled (**on**), or only after the repository lists it or sets an option (**opt-in**). Every ratchet itself is opt-in.
- **Except** says how one hit is excused: a reasoned marker on the line, or a setting in the ratchet's table. See [Exceptions and burn-down](#exceptions-and-burn-down) for when to use which.
- Each bad and fixed pair is minimal: the smallest code that trips the rule and the smallest change that clears it.
- Paths in the snippets are placeholders for your own tree.

## Code shape: structure

[structure-ratchet.md](structure-ratchet.md) and [repo-layout.md](repo-layout.md). The structure ratchet stops a file, a function or a folder from only ever growing, and holds the repository's top-level layout to its declared shape. Failures name the section of the layout reference that says where the code goes instead.

The limits are settings, shown with their defaults:

```toml
[structure_ratchet]
enabled            = true
max_file_lines     = 1000
max_function_lines = 100
max_dir_modules    = 40
near_limit_ratio   = 0.9
layers             = [["src", "app"]]   # the first folder may never import the second
exclude            = ["src/generated/**"]
```

None of these rules has a per-hit marker. Except by `exclude`, or by leaving the offender in the baseline.

#### `size`

A file past `max_file_lines` (counted for `.py`, `.js`, `.mjs`, `.ts`, `.css`, `.html`, `.ps1` and `.sql`). A big file is what every agent then imitates. **Default:** on. A file already over the limit is baselined at its size and may only shrink.

```
# bad:  src/orders.py is 1,240 lines and gains a new function
# fixed: the new code goes in src/order_totals.py beside it; the big file does not grow
```

#### `fn`

A Python function (from `ast`) or a JavaScript function (from a brace matcher) past `max_function_lines`. **Default:** on.

```python
# bad: one 130-line function
def build_report(rows): ...

# fixed: named helpers of about 75 lines each
def build_report(rows):
    return render(summarise(group(rows)))
```

#### `unmeasured`

A JavaScript function whose end the brace matcher cannot find. It is reported as unmeasured, never passed. **Default:** on. Fix by simplifying the construct that hid the closing brace (an unusual regex or template literal), so the function can be measured.

#### `dir`

A folder holding more than `max_dir_modules` modules directly (`.py`, `.js`, `.mjs`, `.css`; `__init__.py` aside; subfolders not counted). **Default:** on.

```
# bad:  src/ holds 41 flat modules and gains a 42nd
# fixed: src/billing/ is a subpackage; the new module goes in it
```

#### `layer`

A module in the lower layer importing the upper one. The default pair is `src` and `app`: logic never imports the UI. **Default:** on; change the pairs with `layers`.

```python
# bad: src/totals.py
from app.views import format_row

# fixed: the shared helper lives in src/, and app/ imports it
from src.formatting import format_row
```

#### `near-limit-files`

A file inside the band just under `max_file_lines` (from `near_limit_ratio`, 0.9 by default, so 900 to 1,000 lines). The count of such files is a second, shrink-only baseline number, so a split that stops just under the limit fails like a new offender. Every check also lists the band's members as warnings that never fail. **Default:** on.

```
# bad:  a 1,300-line file split into 950 and 350 lines; the 950-line half is in the band
# fixed: split to about 750 lines, the target the failure message names
```

#### `near-limit-functions`

The same band for functions: a function at or above `near_limit_ratio` of `max_function_lines`. **Default:** on.

```python
# bad: a 130-line function split into 95 lines and 35 lines
# fixed: split into helpers of about 75 lines
```

The remaining rules read the repository's declared `shape` (a top-level key in `.fleet.toml`: `webapp-tray`, `streamlit`, `pipeline-cli`, `skills-governance`, `node`, `static-site` and others, listed in [repo-layout.md](repo-layout.md)). With no `shape` they are skipped, and the run says so.

```toml
shape = "streamlit"
```

#### `root-layout`

A required root folder with no tracked file, or a tracked root folder that neither the shape nor `extra_roots` lists. **Default:** on once `shape` is declared. **Never baselined:** an undeclared root must be declared or removed.

```
# bad:  a tracked top-level folder named misc/ in a streamlit-shaped repo
# fixed: move its files to a folder the shape lists, or declare it: extra_roots = ["misc"]
```

#### `root`

A declared `extra_roots` folder that the shape's preset does not already list. It is a deviation, so it is baselined and the list only shrinks. **Default:** on once `shape` is declared.

#### `rootfile`

A tracked file at the repository root that neither the common set (`README.md`, `CLAUDE.md`, `.fleet.toml`, `pyproject.toml` and similar) nor the shape lists. Baselined by name. **Default:** on once `shape` is declared. Except by `extra_root_files`, which is also where the reason lives.

```
# bad:  notes.txt at the root
# fixed: move it under docs/, or declare it: extra_root_files = ["notes.txt"]
```

#### `type`

A file whose extension its folder's type does not take (a `.py` file in a folder typed `css`, an `.html` file in `src/`), counted per folder. **Default:** on once `shape` is declared.

```
# bad:  src/page.html            (src takes code)
# fixed: app/webapp/static/page.html, or a folder the shape types as web
```

#### `place`

Where a shape declares homes for a root's second level, a file under that root that sits outside every home, counted per folder. **Default:** on once `shape` is declared, for the shapes that declare homes.

```
# bad:  app/utils/format.py     (utils/ is not one of the shape's homes)
# fixed: app/views/format.py
```

#### `redundant`

An `extra_roots` or `extra_root_files` entry the shape's preset already allows. **Default:** on once `shape` is declared. Delete the entry.

```
# bad:  extra_roots = ["scripts"]    (a streamlit-shaped repo already allows scripts)
# fixed: extra_roots = []
```

## Comments and docs

Three ratchets keep prose current: the comment ratchet for comments, the docs ratchet for the README and `docs/`, and the doc references ratchet for pointers that no longer resolve. The convention is in [readme-and-docs.md](readme-and-docs.md): a comment or a doc states what is true now and why; how it got here lives in the issue, the pull request and `git log`.

### Comment ratchet

[comment-ratchet.md](comment-ratchet.md). Reads comments with a real scanner for each language (`.py` via `tokenize`, `.js`/`.mjs`/`.cjs`, `.css`, `.ps1`/`.psm1`, `.yml`/`.yaml`), never by grepping source lines, so a string is not a comment. Product code only: tests, minified files, generated files (first lines say `DO NOT EDIT` or `@generated`) and every `[vendored]` destination are skipped. Counts are per file; the two opt-in rules count under their own baseline keys (`<path>::docstring`, `<path>::history`), so a removal under one never pays for an addition under the other. Except by `exclude`; there is no per-hit marker.

```toml
[comment_ratchet]
enabled         = true
include         = ["app/", "src/"]
exclude         = ["**/generated/**"]
docstrings      = false
history_phrases = false
```

#### `comment-issue-reference`

An issue reference (a `#` followed by one to five digits, optionally after a repository name) inside a comment. A comment that carries the story of how the code got here teaches the next change to add another. **Default:** on.

```python
# bad
# keep cents as ints, fixed for #412
# fixed
# integer cents: floats drift on repeated addition
```

#### `docstring-issue-reference`

The same reference inside a module, class or function docstring of a `.py` file, the one place the comment scan cannot see. **Default:** opt-in, `docstrings = true`.

```python
# bad
def total(items):
    """Sum the items. See #77 for the rounding story."""
# fixed
def total(items):
    """Sum the items; money stays in integer cents."""
```

#### `history-phrase`

A phrase from a short curated list, matched case-insensitively on whole words, in comments of every language and in Python docstrings: `used to be`, `formerly`, `extracted verbatim`, `pure code move`, `previously recorded`, `had drifted`. **Default:** opt-in, `history_phrases = true`.

```python
# bad
# this used to be a float loop
# fixed
# a generator keeps memory flat for large inputs
```

### Docs ratchet

[docs-ratchet.md](docs-ratchet.md). Reads the root `README.md` and `docs/**/*.md`. Fenced code blocks, HTML comments, bare URLs, link targets and `href`/`src` values are not read; an issue reference inside inline code still counts, because a backtick is not a way around the rule. Except by `exclude` (generated reports) or `allow_refs` (exact reference text, for an intentional link); there is no per-hit marker.

```toml
[docs_ratchet]
enabled          = true
include          = ["README.md", "docs/"]
exclude          = ["docs/reports/**"]
readme_max_bytes = 40960
allow_refs       = ["owner/repo#178"]
```

#### `readme-size`

The root `README.md` past `readme_max_bytes` (40,960, with CRLF counted as LF so a Windows checkout and CI agree). The README is the first file every agent reads, so its size is a cost per session. **Default:** on. An over-budget README is baselined at today's size and may only shrink; a new over-budget README fails by name.

```
# bad:  README.md is 52 KB, with the install guide, the API tables and the FAQ inline
# fixed: README.md is an index under 40 KB; reference moves to docs/<topic>.md
```

#### `doc-issue-reference`

An issue reference (a `#` and digits, alone or after a repository name or an owner and repository) in the README or a doc. Git, the pull requests and the issues already hold that history. **Default:** on.

```
# bad
Added in #123 after the outage.
# fixed
Retries use exponential backoff because the upstream rate-limits bursts.
```

#### `dated-heading`

A heading that holds an ISO date. Prose dates are legal (rotation and expiry dates belong in the README); a dated heading is a walk log. **Default:** on.

```
# bad
## 2026-06-24 notes
# fixed
## Rate limits
```

#### `heading-changelog`

A heading that opens with `Changelog`, `Release notes`, `Release history` or `What's new`. **Default:** on.

```
# bad
## Changelog
# fixed
(no section: the pull requests and `git log` are the changelog)
```

### Doc references ratchet

[doc-refs-ratchet.md](doc-refs-ratchet.md). Reads `README.md`, `CLAUDE.md` and `docs/**/*.md` (override with `include`), outside fenced blocks and HTML comments, and resolves each reference against the tracked tree. A path resolves when it is a tracked file, a folder holding one, or git-ignored. Not checked: placeholders (`<name>`, `*`, `{a,b}`, `$VAR`), absolute and home paths, URLs, links that leave the repo, bare file names, and paths whose first segment is not a tracked root folder. Except by `allow_refs`, globs over the reported text, for an intentional pointer (a file an adopter creates, another service's port).

```toml
[doc_refs_ratchet]
enabled    = true
include    = ["README.md", "CLAUDE.md", "docs/"]
exclude    = ["docs/reports/**"]
allow_refs = ["docs/layout.md", ":8000"]
retired    = [{ term = "--old-flag", why = "flag removed; use --new-flag" }]
```

#### `path`

A path in inline code whose first segment is a tracked top-level folder, read word by word (so a command span is checked per token), that does not exist. A span right after a possessive or a repo slug belongs to another owner and is skipped. **Default:** on.

```
# bad:   Run `scripts/deploy.py` to publish.        (the script moved)
# fixed: Run `scripts/publish.py` to publish.
```

#### `module`

A `python -m <module>` in inline code whose first segment is a tracked folder or root `.py` file, and whose module does not exist. Stdlib and installed tools are someone else's. **Default:** on.

```
# bad:   `python -m app.tools.sync`     (renamed)
# fixed: `python -m app.sync`
```

#### `link`

A relative Markdown link, image, reference definition or `href`/`src` target that does not resolve from the doc's own folder (`#fragment` and `?query` dropped). **Default:** on.

```
# bad:   See [the guide](docs/setup.md).     (the file was renamed)
# fixed: See [the guide](docs/getting-started.md).
```

#### `port`

A loopback port (`localhost:N`, `127.0.0.1:N`, `0.0.0.0:N`, inline `:N`) that is not the one the app declares. **Default:** on only once `.fleet.toml` declares the app's own `port`; otherwise it is not checked.

```
# bad:   Open http://localhost:9999/        (port = 8000 in .fleet.toml)
# fixed: Open http://localhost:8000/
```

#### `retired`

Any occurrence, on word boundaries, in prose, code spans and fences alike, of a term the repository lists as retired: a removed flag, skill, environment variable or config key. The hit prints its `why`. With `retired` set, `SKILL.md` files and the Markdown files they link to are read for retired terms too (and for nothing else). **Default:** opt-in; off while the list is empty.

```
# bad:   Pass `--old-flag` to enable it.
# fixed: Pass `--new-flag` to enable it.
```

## Dead and duplicate code

### Dead code ratchet

[dead-code-ratchet.md](dead-code-ratchet.md). Unused imports and locals are the static ratchet's job; this one finds dead *definitions*.

#### `dead-definition`

A Python `def`, `async def` or `class`, at any depth, whose name is read nowhere in the tracked Python tree (a bare name, an attribute, a `from m import f`). Matching is by name, so a dead `close` hides behind any other `.close`: the check misses, it does not cry wolf. **Default:** on.

Never reported: dunder names, a module's `__all__`, pytest tests, hooks and unittest set-ups, definitions with a built-in entry decorator (route verbs, fixtures, validators, commands, `*.register`), and a public top-level name of a component this repository publishes.

**Confidence** is 100 when the name appears nowhere else, and 60 when it may be reached dynamically (the name sits in a string or a tracked non-Python file, its module calls `getattr` with a computed name or reads `globals()`, or it is a method of a class whose base comes from outside the repo). Only findings at or above `min_confidence` (default 100) count.

```python
# bad: nothing calls orphan(), nothing builds Unbuilt
def used():
    return 1

def orphan():
    return 2

class Unbuilt:
    pass

# fixed: delete both
def used():
    return 1
```

**Except** by `allow` (globs over `<path>:<qualname>`) for a function something outside the tree calls, or `entry_decorators` (globs over a decorator) for a framework hook. There is no per-hit marker.

```toml
[dead_code_ratchet]
enabled          = true
include          = ["src/", "app/"]
min_confidence   = 100
entry_decorators = ["bus.subscribe"]
allow            = ["app/tray/menu.py:on_*"]
```

### Static ratchet

[static-ratchet.md](static-ratchet.md). Four detectors under one baseline. Findings are reduced to line-number-free keys so the baseline survives edits above them. A vendored destination is excluded: a vendor-verbatim copy is checked once, where it lives. Except by `exclude`, or `# noqa: <code>` (ruff's own marker, which the repository's ruff configuration still applies). An off half (`duplicates = false`, `ruff = false`) reports OFF on every run and keeps its baselined entries untouched; both off is a configuration error.

```toml
[static_ratchet]
enabled    = true
min_lines  = 10
min_tokens = 100
exclude    = ["**/_vendored/**"]
ruff_rules = ["B006", "S113", "I001"]   # replaces the default set below; [] means none
duplicates = true                        # false: no jscpd, no Node needed
ruff       = true                        # false: no ruff detectors
```

#### `duplicate-block`

A block of at least `min_lines` lines and `min_tokens` tokens repeated across Python and JavaScript files, found by `jscpd` (pinned to an exact version, run through `npx`, so Node is a prerequisite). Editing a cloned block reads as one hit gone and one new. **Default:** on.

```python
# bad: the same 14-line block in src/a.py and src/b.py
# fixed: one helper in src/shared.py, called from both
```

#### Unused names

Found by `ruff --select F401,F841`, Python only. **Default:** on.

| Rule | Catches | Bad | Fixed |
|---|---|---|---|
| `F401` | an import nothing uses | `import json` | delete the line |
| `F841` | a local variable assigned and never read | `unused = 1` | delete the assignment |

#### Likely bugs, security patterns and import order

A curated set of ruff `B` (bugbear) and `S` (bandit) codes, plus `I001`, run in the same ruff call. Each is one a reviewer fixes rather than argues with. **Default:** all on; `ruff_rules` replaces the set. In test files the codes `S102`, `S307`, `S602`, `S604` and `S605` are not reported: running code or a shell command there is the test's own job on fixture input.

| Rule | Catches | Bad | Fixed |
|---|---|---|---|
| `B002` | `++n` is two unary pluses, not an increment | `++n` | `n += 1` |
| `B003` | rebinding `os.environ` does not reach child processes | `os.environ = {}` | `os.environ["A"] = "1"` |
| `B004` | `hasattr(x, "__call__")` misses callables | `hasattr(x, "__call__")` | `callable(x)` |
| `B005` | `.strip(".txt")` strips a character set, not a suffix | `name.strip(".txt")` | `name.removesuffix(".txt")` |
| `B006` | a mutable default argument is shared by every call | `def f(x=[]):` | `def f(x=None):` |
| `B012` | `return` in `finally` swallows the in-flight exception | `finally: return 2` | drop the `return` |
| `B015` | a comparison whose result is discarded is a missing `assert` | `x == 1` | `assert x == 1` |
| `B016` | raising a literal is a `TypeError` | `raise "boom"` | `raise ValueError("boom")` |
| `B017` | `pytest.raises(Exception)` passes on any error | `pytest.raises(Exception)` | `pytest.raises(ValueError)` |
| `B018` | a statement with no effect is a typo or a missing call | `[x, 3]` | `total = [x, 3]` |
| `B020` | a loop variable that rebinds its own iterable | `for items in items:` | `for item in items:` |
| `B021` | an f-string docstring is not a docstring | `f"doc {x}"` as the first statement | a plain string docstring |
| `B022` | `contextlib.suppress()` with no exceptions suppresses nothing | `suppress()` | `suppress(KeyError)` |
| `B025` | the second handler for the same exception is dead code | two `except ValueError:` | distinct exception types |
| `B026` | `*args` after a keyword argument binds positionally first | `f(a=1, *args)` | `f(*args, a=1)` |
| `B029` | `except ():` catches nothing | `except ():` | `except ValueError:` |
| `B030` | `except` on a non-exception class raises `TypeError` when reached | `except 1:` | `except ValueError:` |
| `B031` | a `groupby` group reused after the generator moved on is empty | `list(g)` twice | `rows = list(g)` once |
| `B032` | `d["k"]: 1` is an annotation, not an assignment | `d["k"]: 1` | `d["k"] = 1` |
| `B033` | a set literal that repeats an item | `{"a", "a"}` | `{"a"}` |
| `B034` | `re.sub` count or flags passed positionally are easy to swap | `re.sub("a", "b", s, 2)` | `re.sub("a", "b", s, count=2)` |
| `B035` | a dict comprehension with a constant key keeps only the last item | `{"k": v for v in vs}` | `{v: 1 for v in vs}` |
| `B039` | a mutable `ContextVar` default is shared by every context | `ContextVar("v", default=[])` | `ContextVar("v", default=())` |
| `S102` | `exec` runs whatever string reaches it | `exec(code)` | call the function directly |
| `S103` | a world-writable `chmod` | `os.chmod(p, 0o777)` | `os.chmod(p, 0o700)` |
| `S113` | an HTTP call without a timeout hangs on a silent peer | `requests.get(url)` | `requests.get(url, timeout=10)` |
| `S201` | Flask `debug=True` serves the remote-code console | `app.run(debug=True)` | `app.run()` |
| `S307` | `eval` of data is code execution | `eval(s)` | `ast.literal_eval(s)` |
| `S506` | `yaml.load` without a safe loader builds arbitrary objects | `yaml.load(s)` | `yaml.safe_load(s)` |
| `S602` | `shell=True` runs shell metacharacters inside an argument | `subprocess.run("ls -l", shell=True)` | `subprocess.run(["ls", "-l"])` |
| `S604` | the same, through a non-subprocess call taking `shell=True` | `go("ls", shell=True)` | `go("ls")` |
| `S605` | `os.system` and `os.popen` always go through a shell | `os.system("ls")` | `subprocess.run(["ls"])` |
| `S701` | Jinja2 with autoescape off renders HTML injection | `Environment(autoescape=False)` | `Environment(autoescape=select_autoescape())` |
| `I001` | an unsorted import block (stdlib, third-party, local) | `import sys` then `import os` | `ruff check --select I001 --fix` |

## Runtime safety

### Conventions ratchet

[conventions-ratchet.md](conventions-ratchet.md). Fleet conventions that one syntax-tree or markup rule can check, each opted into per repository. **No rule is on by default:** `rules` is required and names the ones the repository enforces, and an unknown name is a configuration error, so a typo never runs with less than asked for. Test modules (and any file under `tests/` or `test/`) are held to `no-window` only. Counts are per file and rule.

```toml
[conventions_ratchet]
enabled        = true
rules          = ["no-window", "no-drive-path", "subprocess-timeout"]
exclude        = ["src/generated/**"]
print_paths    = ["app/", "src/"]            # logging-not-print scope; the default
secret_helpers = ["src/secret_compare.py"]   # required by secret-compare
git_wrappers   = ["src/git_run.py"]          # required by git-wrapper
```

**Except** one call with `# <rule>-exempt: <reason>` on the call's own lines or in the comment block right above it. In a web file the comment is `<!-- ... -->`, `// ...` or `/* ... */`. A marker with no reason, or one that names a different rule, exempts nothing.

#### `no-window`

A `subprocess.run/Popen/call/check_call/check_output` or `asyncio.create_subprocess_*` call with no `creationflags=` keyword. On Windows, a console child of a windowless process flashes a console window. A call that passes `**kwargs` is not seen. This is the one rule test modules are held to.

```python
# bad
subprocess.Popen(["tool", "--version"])

# fixed
NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
subprocess.Popen(["tool", "--version"], creationflags=NO_WINDOW)
```

#### `logging-not-print`

A builtin `print(...)` in app code (`print_paths`), outside a command-line module (one with an `if __name__ == "__main__":` block, an `argparse`, `click`, `typer`, `fire` or `optparse` import, a `cli.py` or `__main__.py` name, or a `cli/` folder), not writing to a file, and not a `print` the module binds itself. A long-lived process has no console to read.

```python
# bad
print("starting")

# fixed
log = logging.getLogger(__name__)
log.info("starting")
```

#### `no-drive-path`

A string literal that starts with a Windows drive letter. The system folders `Windows`, `Program Files`, `Program Files (x86)` and `ProgramData` are never reported (the instructions mandate absolute system binaries), and neither is a bare drive root.

```python
# bad
DATA = "E:\\data\\in"

# fixed
DATA = Path(os.environ["APP_DATA_DIR"])
```

#### `secret-compare`

An `hmac.compare_digest` or `secrets.compare_digest` call outside the repository's declared helper, so every secret comparison goes through one audited place. Needs `secret_helpers`.

```python
# bad
return hmac.compare_digest(supplied, expected)

# fixed
from src.secret_compare import same
return same(supplied, expected)
```

#### `git-wrapper`

A spawn whose program is literally `git` outside the repository's declared wrapper, which owns the environment, timeout and window flags for every git call. Needs `git_wrappers`.

```python
# bad
subprocess.run(["git", "status"], creationflags=NO_WINDOW, timeout=30)

# fixed
from src.git_run import run_git
run_git("status")
```

#### `password-input-vendored`

A password input (`type="password"`, `type: 'password'`, `.type = 'password'`, `setAttribute('type', 'password')`) in a web file outside a `_vendored/sign-in/` folder: every app's sign-in goes through the one vendored component. The only rule that reads web files (`.html`, `.htm`, `.js`, `.mjs`, `.cjs`, `.ts`, `.jsx`, `.tsx`, `.vue`, `.svelte` and the Jinja suffixes), and it reads no `.py`.

```html
<!-- bad -->
<input type="password" name="pw">

<!-- fixed: the app mounts the vendored sign-in sheet and ships no password input of its own -->
<div data-sign-in></div>
```

#### `login-lockout`

A FastAPI password route, `@<x>.post("<path>")` whose last path segment is `login`, in a module that does not import the vendored `login_lockout`, or whose handler never calls `retry_after(...)`. Every password route answers `429` with `Retry-After` after repeated wrong passwords. A route registered another way (`add_api_route`) or with a computed path is not seen.

```python
# bad
@app.post("/api/login")
def login(body: dict):
    return {"ok": True}

# fixed
from src.login_lockout import LoginLockout, retry_after_header

lockout = LoginLockout()

@app.post("/api/login")
def login(body: dict, request: Request):
    wait = lockout.retry_after(request.client.host)
    if wait > 0:
        raise HTTPException(429, "too many attempts", headers=retry_after_header(wait))
    ...
```

#### `no-pwsh-stub`

The `pwsh` stub run as a command (`pwsh` or `pwsh.exe` followed by a switch, or the first quoted item of an argv list) in a `.md`, `.ps1`, `.bat`, `.cmd`, `.toml`, `.json`, `.yml`, `.yaml` or `.py` file. On the machine this rule protects, `pwsh` is a 0-byte alias, so a gate or restart command written with it never runs. An absolute path to a real install, `shell: pwsh` and prose that names the stub with no switch are not hits. It reads lines of text, so a line that only names the stub to forbid it carries its marker on the same line or the line right above.

```
# bad
Run `pwsh -File gate.ps1` before shipping.

# fixed
Run the gate with the absolute Windows PowerShell path:
C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe -File gate.ps1
```

#### `subprocess-timeout`

A `subprocess.run/call/check_call/check_output` call with no `timeout=` keyword (and no `**kwargs`, which may carry it). An unattended run that hangs on its child never reports it. `Popen` and `asyncio.create_subprocess_*` are not hits: their lifetime is managed by the caller.

```python
# bad
subprocess.run(["tool"], creationflags=NO_WINDOW)

# fixed
subprocess.run(["tool"], creationflags=NO_WINDOW, timeout=30)
```

#### `must-use`

A call to a dotted name outside the file or files the repository declares as the one home for that job. Listing a `[[conventions_ratchet.must_use]]` entry is what turns the rule on; each entry takes `call` (a dotted name or a list), `helper`, `why` and an optional `paths` scope. The name is resolved through the module's imports (`import x as y`, `from x import f`). A method on an instance is not seen. `secret-compare` and `git-wrapper` are this same check with the call set built in. Marker: `# must-use-exempt: <reason>`.

```toml
[[conventions_ratchet.must_use]]
call   = "sqlite3.connect"
helper = ["src/db.py"]
why    = "one get_db dependency owns the connection"
paths  = ["src/", "app/"]
```

```python
# bad: src/orders.py
conn = sqlite3.connect("orders.db")

# fixed: src/orders.py
conn = get_db()          # defined in src/db.py, the only module that connects
```

### Runtime write ratchet

[runtime-write-ratchet.md](runtime-write-ratchet.md). Runtime output (logs, run records, caches, databases) belongs under `data/` or the machine's runtime root, never next to the code that writes it. The ratchet finds every write target in the repository's Python source and resolves its path statically. Write targets are `open()` with a writing mode, `<path>.write_text/write_bytes/touch/mkdir()`, `os.mkdir/makedirs`, `shutil.copy*/move` (the destination), `logging.*FileHandler`, `logging.basicConfig(filename=)` and `sqlite3.connect()`. A relative path is read from the repository root. Test modules are not scanned: they write under pytest's `tmp_path`, and the probe covers a run. **Except** one call with `# runtime-write-exempt: <reason>`, or by `exclude` and `safe_calls` (calls that return a path outside the tree).

```toml
[runtime_write_ratchet]
enabled      = true
code_folders = ["src", "app", "scripts", "hooks", "skills"]   # the default
exclude      = ["src/generated/**"]
safe_calls   = ["my_runtime_dir"]
```

#### `code-folder`

A write target that resolves under a code folder. **Default:** on. A rise fails with exit 1.

```python
# bad
with open("src/state.json", "w") as fh:
    fh.write("{}")

# fixed
(Path("data") / "state.json").write_text("{}")
```

#### `unresolved`

A write target the source does not settle (a parameter, an attribute, an environment variable). That is **unknown, never clean**: a new one exits 3 until the path is made resolvable, the call carries `# runtime-write-exempt: <reason>`, or the baseline is raised in review. **Default:** on.

```python
# bad
def save(path, text):
    with open(path, "w") as fh:
        fh.write(text)

# fixed: the destination is built from a known root inside the function
def save(text):
    (DATA_DIR / "state.json").write_text(text)
```

#### `probe`

A file the test run added under a code folder, found by comparing two snapshots around the run. Bytecode and tool caches aside. **Default:** on when run with a test command (`scripts/run_ratchets.py --tests <command>`); without one the probe prints OFF. Never baselined.

```
$ python scripts/runtime_write_ratchet.py --snapshot snap.json
$ <run the tests>
$ python scripts/runtime_write_ratchet.py --probe snap.json
runtime write probe: FAIL: the run wrote 1 file(s) under the code folders:
  src/run.log
```

## Agent instructions

[instruction-ratchet.md](instruction-ratchet.md). The deterministic, lint-tier rules of a prompt audit, run over the instruction files: the root `CLAUDE.md` and `AGENTS.md`, `.claude/rules/*.md`, each `<skill_dir>/*/SKILL.md`, the `.md` files a skill references, and `extra_files`. A line that makes a model over-trigger costs every session that reads the file.

**The reader decides whether a hit counts.** A rule is tagged `shared` or with one vendor. A shared rule counts in any file. A single-vendor rule counts only in a file or heading section scoped to that vendor's agent (`.claude/rules/*.md`, a `CLAUDE.md` that `AGENTS.md` does not point at, or a heading carrying `Claude Code only` or `Codex only`); in an agent-neutral file it is advisory and adds nothing to the count. Fenced code blocks, inline code and frontmatter are not linted (the backslash-path rule reads inline code, because that is what gets copied). Counts are per file and rule. **Except:** there is no per-hit marker; reword the line, or accept the hit in the baseline.

```toml
[instruction_ratchet]
enabled              = true
skill_dirs           = [".claude/skills"]   # the default
extra_files          = []
ci_expectations      = false                # S-01
agents_pointer       = false                # S-02
claude_md_max_lines  = 120                  # S-03; unset means off
repeated_text_words  = 12                   # S-04; unset means off
repeated_text_global = false                # S-04
repeated_text_exclude = []                   # S-04; docs/ files that are never a source
```

**Default:** the `R-` rules below are on. The four `S-` rules are opt-in.

| Rule | Reader | Catches | Bad | Fixed |
|---|---|---|---|---|
| `R-01` | Anthropic | ALL-CAPS pressure words | `You MUST run the tests.` | `Run the tests.` |
| `R-02` | Anthropic | blanket tool defaults | `When in doubt, use the search tool.` | `Use the search tool for questions about the codebase.` |
| `R-03` | shared | forced verification or re-check lines | `Double-check your answer before replying.` | `Run the gate command and report its result.` |
| `R-04` | shared | periodic progress-summary scaffolding | `Summarise progress after every 3 tool calls.` | `Report progress when a phase finishes.` |
| `R-05` | Anthropic | narration suppression | `Hold all findings until the final report.` | `Report each finding as you confirm it.` |
| `R-06` | Anthropic | blanket anti-formatting lines | `Do not use markdown in answers.` | `Answer in short paragraphs; put code in fences.` |
| `R-07` | Anthropic | hand-written reasoning plans | `Think step by step before answering.` | `State the cause, then the fix.` |
| `R-08` | Anthropic | "do not think" rules | `Never think before editing.` | `Read the file before editing.` |
| `R-09` | Anthropic | recall-suppressing review lines | `Only report high-severity issues.` | `Report every issue with its severity.` |
| `R-10` | Anthropic | prefill or thinking-budget references | `Use a prefilled assistant turn.` | `Start the reply with the answer.` |
| `R-11` | Anthropic | time-sensitive phrasing | `Before March 2025 use the old API.` | `Use the current API.` |
| `R-12` | OpenAI | upfront-plan or preamble demands | `Outline a plan before answering.` | `Start with the first action.` |
| `R-14` | shared | an instruction file past its size cap (below) | a 251-line rules file | move scoped detail into a skill or a referenced doc |
| `R-15` | Anthropic | a skill description over 1,024 characters, first- or second-person words, an XML tag, or a `name` that is not 1 to 64 characters of `[a-z0-9-]` | `description: I help you review code.` | `description: Reviews a diff for unsafe defaults. Use when asked to review a change.` |
| `R-16` | shared | the same action phrase under both an always/must and a never/do-not modal in one file | `Always run the linter.` and `Never run the linter.` | keep one |
| `R-17` | shared | an agent-neutral paragraph that names one vendor's products without a scope marker | `Claude reads this file at the start of every session.` | `The agent reads this file at the start of every session.` |
| `R-30` | Anthropic | reasoning-in-the-answer instructions | `Show your work in the answer.` | `Give the result and the evidence.` |
| `R-34` | Anthropic | a skill's reference doc linking a further local `.md` that the `SKILL.md` does not reference | `ref.md` links `more.md` | link `more.md` from `SKILL.md` too |
| `R-35` | Anthropic | a reference doc over 100 lines with no Contents heading in its first 40 lines | a 120-line `ref.md` that opens with prose | open it with a `## Contents` list |
| `R-36` | Anthropic | a backslash path in a `SKILL.md` (a relative one counts; a drive or `.venv` path is advisory) | `.claude\skills\review\x.md` | `.claude/skills/review/x.md` |
| `R-45` | Anthropic | blanket tool-use discouragement | `Minimize tool calls.` | `Call the tool when the answer needs repo state.` |

In a typical repository, whose `AGENTS.md` points at `CLAUDE.md`, the counted rules are the shared ones (`R-03`, `R-04`, `R-14`, `R-16`, `R-17`) plus the relative backslash paths of `R-36`. `R-15` reports against the frontmatter on line 1 of a `SKILL.md`, which no heading can scope, so it stays advisory and adds nothing to a count. `R-34` counts only inside a heading section scoped to Claude, and `R-35` only when the reference doc's first line is itself a heading scoped to Claude. Two audit rules are deliberately left to the weekly audit, because a count cannot decide them: a positive-framing ratio, and fully qualified tool names across the fleet's skills.

**Size caps** (the `R-14` rule): `CLAUDE.md` and `.claude/rules/*.md` at 200 lines, the body of a `SKILL.md` at 500 lines, `AGENTS.md` at 32,768 bytes (CRLF counted as LF). An over-cap file is baselined at its size (`{"key": ".claude/rules/long.md", "size": 251}`) and may only shrink. Deleting directives to pass is never the fix.

The four file-shape rules count a property of the files, not a line. Each is off until its option is set, so re-vendoring never turns a repository red. A finding is baselined under the file it is about, even a missing one.

| Rule | Option | Catches | Bad | Fixed |
|---|---|---|---|---|
| `S-01` | `ci_expectations = true` | a repository with a file under `.github/workflows/` whose root `CLAUDE.md` has no `CI expectations` heading (or has no `CLAUDE.md`) | a workflow folder and no such heading | add `## CI expectations` with durations and the flaky leg |
| `S-02` | `agents_pointer = true` | an `AGENTS.md` that is missing, does not name `CLAUDE.md`, or has more than 10 non-blank lines (a copy, not a pointer) | a 40-line `AGENTS.md` | `See CLAUDE.md.` |
| `S-03` | `claude_md_max_lines = N` | the root `CLAUDE.md` past `N` lines, counted as the number of lines over, so the baseline falls as the file shrinks | a 140-line file with `N = 120` | move scoped detail into a doc or skill |
| `S-04` | `repeated_text_words = N` (5 or more) | a run of `N` or more consecutive words that a `CLAUDE.md` shares with a `docs/**/*.md` file (or, with `repeated_text_global = true`, the owner's global file); one hit per maximal run | a paragraph pasted from a doc | replace it with a pointer to the doc |

## Usage tracking

[usage-track-ratchet.md](usage-track-ratchet.md). A web app's usage log sees only what the markup names. This ratchet reads the app's HTML and JavaScript and counts, per file and rule, the controls and sheets that would be invisible to it. **No rule is on by default:** `rules` is required and names at least one. A nav tab (`data-tab` inside a `<nav>`) is a view, not a tap. **Except** one hit with `<rule>-exempt: <reason>` in a `//` comment in JavaScript or a `<!-- -->` comment in HTML, on its own line or in the comment block right above it; a marker with no reason exempts nothing. Or by `exclude`.

```toml
[usage_track_ratchet]
enabled  = true
rules    = ["untracked-control", "untracked-sheet", "dynamic-id", "usage-log-wired"]
paths    = ["app/webapp/static/**", "app/webapp/templates/**"]   # the default
exclude  = ["app/webapp/static/vendor/**"]
builders = ["app/webapp/static/row.js:row"]   # control builders whose callers pass `track:`
```

#### `untracked-control`

A control (`<button>`, `<summary>`, `<select>`, an `<input>` of type button, submit, reset, checkbox, radio or image, an element with a control `role`, an `<a>` whose `href` is `#...` or `javascript:`) with no constant `data-track` of its own and no tracked control or grouping parent (`role` group, radiogroup, tablist, toolbar, menu, menubar or listbox). In JavaScript it also reads a control inside a string or template literal, a `createElement` control that never gets `dataset.track` or `setAttribute('data-track', ...)` in the same block, and a call to a declared builder with no `track:` key.

```html
<!-- bad -->
<button class="go">Save</button>

<!-- fixed -->
<button class="go" data-track="save">Save</button>
```

#### `untracked-sheet`

A `<dialog>` (in HTML, in a JavaScript string, or from `createElement('dialog')`) with no `data-track-view`. Without it, a sheet's minutes are billed to the tab under it.

```html
<!-- bad -->
<dialog id="d"><p>hi</p></dialog>

<!-- fixed -->
<dialog id="d" data-track-view="save-sheet"><p>hi</p></dialog>
```

#### `dynamic-id`

A `data-track` or `data-track-view` value (also a `dataset.track` assignment, a `setAttribute('data-track...')` value, a `.track(...)` or `.trackView(...)` argument, or a builder's `track:` value) that is not a string literal matching the id pattern: a letter or digit first, then up to 63 of letters, digits, `.`, `_`, `:` and `-`, with no whitespace and no `/`. A name bound to a module-level `const` string literal is resolved and accepted. An id built from content breaks the privacy contract.

```js
// bad
el.innerHTML = `<button data-track="row-${item.name}">Open</button>`;

// fixed
el.innerHTML = `<button data-track="row-open">Open</button>`;
```

#### `usage-log-wired`

The repository-level check, and **never baselined**: `[vendored]` declares both `usage-log` (the client) and `usage_log` (the server), a file in scope calls `initUsageLog(`, and a tracked Python file calls `usage_router(` (the vendored Starlette adapter counts when `[vendored]` declares it). A web app that does not reach its own log is the failure.

```
usage track ratchet: [usage-log-wired] the app does not reach its usage log:
  `[vendored]` does not declare `usage-log` (the client)
  `[vendored]` does not declare `usage_log` (the server)
  no file in `paths` calls `initUsageLog(`
```

## Exceptions and burn-down

A hit has five possible fates. Pick the narrowest.

| Fate | Use it when | Visible in review as |
|---|---|---|
| **Fix it** | The rule is right and the fix is small. The default. | the code change |
| **A reasoned marker** (`# <rule>-exempt: <reason>`, or `# noqa: <code>` for the static ratchet) | This one call or control is a deliberate exception, and the reason belongs next to it. A marker with no reason, or for another rule, exempts nothing. | a comment at the call |
| **A setting** (`allow`, `allow_refs`, `safe_calls`, `entry_decorators`, `builders`, `extra_roots`, `extra_root_files`) | A whole class of thing is legitimate in this repository: a function a framework calls, an intentional link, a folder the shape does not list. | a line in `.fleet.toml` |
| **`exclude`** | Generated or third-party code the repository does not own. Excluded files are never scanned, so it also hides future hits; keep the glob narrow. A vendor-verbatim copy listed in `[vendored]` is excluded for you. | a glob in `.fleet.toml` |
| **The baseline** | Existing debt that cannot be fixed in this change. | added lines in a `.<name>-ratchet-baseline.json` |

Which ratchets take which:

| Ratchet | Per-hit marker | Settings that except |
|---|---|---|
| static | `# noqa: <code>` | `exclude`, `ruff_rules` |
| comment | none | `include`, `exclude` |
| docs | none | `include`, `exclude`, `allow_refs` |
| structure | none | `exclude`, `layers`, `extra_roots`, `extra_root_files` |
| instruction | none | `skill_dirs`, `extra_files` widen the scope; no exclusion |
| doc references | none | `include`, `exclude`, `allow_refs` |
| dead code | none | `include`, `exclude`, `allow`, `entry_decorators` |
| conventions | `# <rule>-exempt: <reason>` | `exclude`, `print_paths` |
| runtime write | `# runtime-write-exempt: <reason>` | `exclude`, `safe_calls`, `code_folders` |
| usage track | `<rule>-exempt: <reason>` | `exclude`, `paths`, `builders` |

**A baseline is a ledger to burn to zero, never a permanent allowance.** It records debt, not approval:

- When a counted hit disappears, the check still passes and prints a hint. Run `--update-baseline` and commit the smaller file. The baseline only ever shrinks on its own.
- A new hit that must stay needs `--update-baseline --allow-additions`, which shows up in review as added lines. Re-baselining just to get green is the one thing a ratchet exists to stop; say so in the pull request when you do it.
- A burn-down is a series of small changes that each shrink the file: fix a group of hits, run `--update-baseline`, commit. Several rules also have an automatic fix (`ruff check --select I001 --fix` clears the import-order baseline in one pass).
- Moving or renaming a file with baselined hits reads as a new file with new hits, so resolve it with `--allow-additions` in that one change, or fix the hits first.

## Adoption order

[adopting-ratchets.md](adopting-ratchets.md) has the steps and the prerequisites table, and `scripts/adopt_ratchets.py` does them. A sensible order: start with the set that is Python only and needs no choices (comment, docs, structure, instruction, doc references, dead code, runtime write), then add static once `ruff` is installed, then conventions and usage track by choosing the rules that match the repository. Run `--init` on each, review the baseline, and burn it down in later changes.
