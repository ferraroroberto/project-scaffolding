# Doc references ratchet

`scripts/doc_refs_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It reads `README.md`, `CLAUDE.md` and `docs/**/*.md`, picks out every reference to a repo path, a `python -m` module or a loopback port, and resolves each one against the tracked tree and `.fleet.toml`. It fails on a **dangling** reference that the committed baseline does not already record. Existing debt never blocks work; it cannot grow either.

A doc that names a script that moved or a port the app no longer binds sends the next reader, agent or human, down a dead end, and nothing else fails when the code moves. This is the mechanical share of the stale-documentation findings `/codebase-audit` files.

It reuses the shape of the [docs ratchet](docs-ratchet.md) and the [instruction ratchet](instruction-ratchet.md): an opt-in `.fleet.toml` table, a committed baseline, the same flags, and exit 3 for "not confirmed". It is stdlib-only.

## What is a reference

Read outside fenced code blocks and HTML comments, line by line:

| Kind | Read from | Example |
|---|---|---|
| `path` | Any whitespace token of an inline code span whose first segment is a **tracked top-level folder** | `` `scripts/classify_e2e.py` ``, `` `docs/` ``, `` `.\scripts\verify-before-ship.ps1 -Verbose` `` |
| `module` | The token after `-m` in an inline code span, when its first segment is a tracked top-level folder or a root `.py` file | `` `python -m scripts.classify_e2e` `` |
| `link` | A relative Markdown link or image target, a reference definition, an `href` or `src` attribute, resolved from the doc's own folder | `[guide](../README.md)` |
| `port` | `localhost:N`, `127.0.0.1:N`, `0.0.0.0:N` or `[::1]:N` anywhere on the line, or an inline code span that is only `:N` | `` `127.0.0.1:8447` ``, `` `:8447` `` |

Before resolving, a path drops its `./` prefix and any line, symbol or test-id suffix (`:12`, `:12-30`, `#L12`, `:func`, `::test_x[param]`); backslashes become slashes. A link drops its `#fragment` and `?query` and is URL-decoded.

## What resolves

- **A path or link** resolves when it is a tracked file, a folder holding a tracked file, or something git ignores. A path also resolves as shorthand for the `.py` file of the same name, and as `<module>.<symbol>` when the module is a tracked `.py` file or package (`src/runtime_data.runtime_db_path`).
- **A module** resolves when `<a>/<b>.py`, `<a>/<b>/__init__.py` or `<a>/<b>/__main__.py` is tracked.
- **A port** resolves when it is the app's own `port` in `.fleet.toml` (`8447` or `":8447"`). With no `port` declared, ports are not checked, and the pass line says so.

The tree of record is `git ls-files` (spawned with `GIT_OPTIONAL_LOCKS=0`), never the working folder, so a local checkout and CI agree. An ignored path is machine-local by design (`.env`, a build output, a certificate folder), so one batched `git check-ignore --no-index` call asks about every candidate, and about a probe child under it, which catches a folder whose contents are ignored but not the folder itself.

## What is not checked, and why

| Not checked | Why |
|---|---|
| A path whose first segment is not a tracked top-level folder | Another repo's tree reads exactly like a typo. Bare file names (`tray.bat`, `design.md`) are skipped for the same reason: in a fleet dry run they were about 2,000 of 2,500 hits, and a reviewed sample was dotted identifiers (`browser.close`, `st.error`), bare extensions (`.py`) and files that live in another repo |
| A span right after a possessive, a pronoun or a repo slug | `` `fleet-config`'s `docs/repo-layout.md` ``, "its", "their", `local-llm-hub` `docs/repo-layout.md`, a table row whose previous cell is a repo slug. The previous line's end counts when the span opens its line, so a wrapped possessive still qualifies |
| Placeholders, globs and variables | `<`, `>`, `*`, `?`, `{}`, `[]`, `$`, `%`, `\|`, `=`, `…` or `...` in the token |
| Absolute, home and drive paths, URLs, `..` segments in a span | Machine-local, or not a claim about this tree |
| A link that leaves the repo | `../../other-repo/x.md` points at a sibling checkout this stage cannot see |
| Fenced code blocks | Example trees, sample config and command transcripts are full of paths the reader creates; the cost is that a stale command inside a fence is not caught |
| Skills, slash commands, environment variables | Their source of truth is outside the repo (user-scope skill folders, the shell) |
| `stdlib` and installed modules | `python -m pytest` names someone else's module |

### Limits

- **A qualifier is a heuristic.** A kebab-case word right before a span reads as a repo slug, so `the e2e-suite` `` `tests/x.py` `` is skipped too. Write the path where it reads as yours.
- **A port is ambiguous.** The doc of a web app names the ports of the services it talks to, so every other port must be listed once in `allow_refs` (`":8000"`). That list is the adoption cost, and it is what makes a stale own port fail: when the app moves, its old number is neither its port nor allowed.
- **An intentional pointer cannot be told from a stale one.** A doc that tells the reader to create a file (`docs/layout.md` in an adopter, a workflow copied from a template) names a path that does not exist on purpose. Put it in `allow_refs`.
- **Code spans do not continue across lines.** A backtick run with no partner on its own line is literal text.
- **Indented code blocks are read as prose.** They cannot be told from list continuation.

## Allowed references

`allow_refs` is a list of globs, empty by default, matched against the reported reference: the repo-relative path, `-m <module>` or `:<port>`. `**/` is zero or more folders, `*` stays within one. Use it for intentional pointers: a file an adopter creates, another service's port, a path a template copies into place. A reference not worth a config entry costs one `--allow-additions`, visible in review.

## Scope

Files come from `git ls-files`: the root `README.md` and `CLAUDE.md` plus `docs/**/*.md` (the `include` default is `["README.md", "CLAUDE.md", "docs/"]`). Always excluded: `node_modules`, `.venv`, `venv`, files whose first five lines contain `DO NOT EDIT` or `@generated` (case-sensitive), `exclude` globs, and every `dest` in the adopter's own `[vendored]` table (a vendored doc's references belong to the repo it came from).

## Exit codes

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (no dangling reference beyond the baseline), or the stage is **not enabled** | continues |
| `1` | A dangling reference not in the baseline, or the baseline file is missing | fails |
| `2` | Bad `[doc_refs_ratchet]` table, a malformed `port`, unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: `git` unusable (`ls-files` or `check-ignore`), a file that is not UTF-8, or a fenced block or HTML comment that never closes. The message names the file and the line the block opened on | fails |

Exit 3 is its own state and never folded into a pass. An unclosed fence is not skipped because CommonMark runs it to the end of the file, which would silently hide every reference below it.

## The baseline file

Committed, sorted JSON, one doc per line, keyed by repo-relative path. It records the dangling references themselves, not a count, so fixing one and adding another still fails:

```json
{
  "version": 1,
  "entries": [
    {"key": "README.md", "refs": ["scripts/old.py"]},
    {"key": "docs/setup.md", "refs": [":8501", "src/client.js", "src/client.js"]}
  ]
}
```

A reference that appears twice is recorded twice. There are no line numbers, so edits elsewhere in a file never churn it. Renaming a doc that carries debt reads as a new file, resolved with `--allow-additions`.

## Modes

```
python scripts/doc_refs_ratchet.py                                   # check (what the gate runs)
python scripts/doc_refs_ratchet.py --init                            # first baseline; refuses to overwrite
python scripts/doc_refs_ratchet.py --update-baseline                 # drop what now resolves; exit 1 + write nothing if anything was added
python scripts/doc_refs_ratchet.py --update-baseline --allow-additions   # the explicit flag that adds entries
```

A failing check prints `<doc>:<line>: <kind> `<reference>` does not exist` with the line's text. The fix is to point the reference at what exists now, drop it, or (for an intentional pointer) add it to `allow_refs`.

## Adopting it (opt-in per repo)

Re-vendoring the script never breaks a repo that has not opted in: an absent `[doc_refs_ratchet]` table, or `enabled = false`, prints `doc refs ratchet: not enabled` and exits 0 (declared, not inferred).

1. Vendor `scripts/doc_refs_ratchet.py` byte-for-byte (`/propagate-vendored doc_refs_ratchet`; manifest key `doc_refs_ratchet`) and declare it in the repo's `[vendored]` table. It needs Python 3.11+ (`tomllib`) and `git`.
2. Add to the repo's own `.fleet.toml`:

   ```toml
   [doc_refs_ratchet]
   enabled    = true
   baseline   = ".doc-refs-ratchet-baseline.json"  # default
   include    = ["README.md", "CLAUDE.md", "docs/"] # path prefixes; the default
   exclude    = ["docs/reports/**"]                 # globs, e.g. generated per-run reports
   allow_refs = [":8000", ":8090"]                  # globs; another service's port, a file adopters create
   ```

3. If the repo serves an app, list the ports of the other services its docs name in `allow_refs` first: a fleet web app names one to seven of them, the hub repo eighteen. Then run `python scripts/doc_refs_ratchet.py --init`, review the baseline, and commit it. Each entry is either a real stale reference worth a follow-up fix or an intentional pointer worth an `allow_refs` line. **Adoption never requires the fixes first.**
4. Add a gate stage that runs `python scripts/doc_refs_ratchet.py` and fails on any non-zero exit. The scaffold's `scripts/verify-before-ship.ps1` places it after the instruction ratchet and before `mypy`. **Do not path-route it**: a code change can strand a doc reference without touching the doc.
5. If the repo uses diff-proportionate e2e routing, add a `tier = "none"` rule for the baseline file to `.fleet.toml` `[e2e]` and a matching assertion in `tests/test_classify_e2e.py`.

The script spawns `git` with `CREATE_NO_WINDOW`, derived locally (it is vendor-verbatim, so it cannot import `src/no_window.py`). It shares its config, glob, Markdown-block and baseline helpers with the sibling ratchets by copy, because each vendored file must be self-contained.

## Cost and measured hit rate

A read-only dry run with the default configuration over every fleet checkout (42 repos, 2 to 70 Markdown files each) finished without a "not confirmed" in 0.06 to 0.8 s per repo; as a gate stage here it adds about 0.35 s, interpreter start included.

| Kind | Hits | Repos | Real stale references |
|---|---|---|---|
| `path` and `link` | 83 | 21 | 21, reviewed by hand: deleted icons, scripts, tests and skill helpers, a protocol tree that moved, a `LICENSE` link with no file. The rest are intentional pointers (40 of them in the scaffold and its two sibling configuration repos, which describe files adopters create or other repos own), runtime output folders, and cross-repo pointers the qualifier rule misses |
| `port` | 171 | 10 | None. Every hit was another service's port; the ten repos name 51 distinct ones, which is the one-time `allow_refs` list |
| `module` | 0 | 0 | None |

Of the 2,500 hits the first draft reported, about 2,000 came from bare file names, about 165 from test ids and symbol suffixes, and about 75 from cross-repo pointers, placeholders and ignored folders, which is why those classes are skipped. Precision on paths is therefore about one in four fleet-wide, and nearly one in two (19 of 41) outside the scaffold and its configuration siblings: the first `--init` absorbs the rest, and each new false positive costs one `allow_refs` line.

## Tests

`tests/test_doc_refs_ratchet.py`: extraction on fixture strings (what counts as a path, module, link or port; the placeholders, qualifiers, URLs, fences and comments that do not), resolution (files, folders, `.py` shorthand, symbols in modules and packages, module forms, the declared port), scope, and every mode and exit code on throwaway git repos, including ignored paths and folders, `allow_refs` globs and the port check. A missing prerequisite is a hard failure there, never `pytest.skip`. The scaffold's own gate stage doubles as the guard that its committed baseline is current, and a test pins that this page carries no dangling reference itself.
