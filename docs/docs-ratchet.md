# Docs ratchet

`scripts/docs_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It enforces the [README and docs convention](readme-and-docs.md) with two measures, both per file: the **size of the root `README.md`** in bytes, and the number of **history markers** in `README.md` and `docs/**/*.md`. It fails when either **rises** above a committed baseline. Existing debt never blocks work; it cannot grow either.

It reuses the shape of the [static-analysis ratchet](static-ratchet.md) and the [comment ratchet](comment-ratchet.md): an opt-in `.fleet.toml` table, a committed baseline, the same flags, and exit 3 for "not confirmed". It is a separate script from the comment ratchet because the scanner differs (a Markdown line scan, not four language comment extractors), the measures differ, and a repo can adopt one without the other.

## What is counted

A **marker** is one of:

| Kind | Matches |
|---|---|
| `ref` | `#` plus one to five digits: `#NNN`, `repo#NNN`, `owner/repo#NNN`. Not preceded by `&`, `#` or `/`; not followed by a word character or `-` |
| `dated-heading` | An ATX heading line (`#` to `######`) that holds an ISO date (`YYYY-MM-DD`, valid month and day) |
| `changelog-heading` | A heading whose text opens with `Changelog`, `Release notes`, `Release history` or `What's new` (optional leading numbering or emoji) |

A heading that is both a changelog heading and dated counts once. References are counted per occurrence; several on a line count separately. The count is per **file**, so a new marker in one file cannot hide behind a removal in another.

### What is not counted

| Text | Why |
|---|---|
| Fenced code blocks, backtick or tilde | Code and command output are not prose. The closing fence must be the same character and at least as long as the opener; fences inside list items and block quotes are recognised |
| HTML comments, including multi-line | Not rendered |
| Bare URLs, `<autolinks>`, `[text](target)` targets, `![alt](target)` targets, reference-definition URLs, `href` and `src` attribute values | An anchor or an issue link is not a citation. A linked reference such as ``[#N](https://…)`` counts once, through its text |
| `&#123;`-style entities, `#12-style` anchors, six-digit numbers | Not issue references |
| Prose dates, dates in table cells, "as of" stamps | Expiry and rotation dates must stay legal in a README |

**A reference inside inline code counts.** A backticked `#NNN` is still a citation; exempting backticks would be a one-character bypass. A `<!--` inside an inline code span is code, not a comment opener.

### Allowed references

`allow_refs` is an exact-text list, empty by default. An entry matches the reference as written, repo prefix included: an entry spelled `owner/repo#NNN` allows exactly that text and nothing else (not the bare `#NNN`, not the same repo with a longer number). There is no lexical "see also" detection; it would exempt most real narrative. A pointer that is not worth a config entry costs one `--allow-additions`, visible in review.

### Limits

- **A navigational reference cannot be told from a narrative one.** Roughly one hit in fifteen is a legitimate pointer (a heading that lists the issues a section answers). The baseline absorbs these.
- **Dated headings are about half measurement stamps and decision dates.** Not separable lexically, so the baseline absorbs them too. An adopter excludes generated report folders with `exclude`.
- **Indented code blocks are not detected.** They are ambiguous with list continuation. A reference inside one is counted.
- **Narrative phrasing is not measured** ("previously", "no longer", "used to"). It is a judgement call left to review.
- **Setext headings** (underlined with `===`) are not read as headings, so they never count as dated or changelog headings.

## Scope

Files come from `git ls-files`, spawned with `GIT_OPTIONAL_LOCKS=0`: the root `README.md` plus `docs/**/*.md` (the `include` default is `["README.md", "docs/"]`). Always excluded: `node_modules`, `.venv`, `venv`, files whose first five lines contain `DO NOT EDIT` or `@generated` (case-sensitive), `exclude` globs, and every `dest` in the adopter's own `[vendored]` table. `CLAUDE.md`, nested READMEs and `tests/` are out of scope. There is no size budget on `docs/` files; only the root README is measured.

## README size

Bytes of the working-tree file with CRLF normalised to LF, so a Windows checkout and CI agree.

- At or under `readme_max_bytes` (default 40,960): no entry, and it must stay under.
- Over budget: baselined at today's size as `"bytes"`, and may only shrink. Growth fails by name.
- Back under budget: the next `--update-baseline` drops the entry's `bytes`.
- Over budget with no entry (a new README, or one that crossed the line): fails by name.

## Exit codes

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (nothing above its baseline), or the stage is **not enabled** | continues |
| `1` | A marker count rose, a new file carries markers, a README is over budget without an entry or past its entry, or the baseline file is missing | fails |
| `2` | Bad `[docs_ratchet]` table, unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: `git` unusable, a file that is not UTF-8, or a fenced block or HTML comment that never closes. The message names the file and the line the block opened on | fails |

Exit 3 is its own state and never folded into a pass. An unclosed fence is not skipped because CommonMark runs it to the end of the file, which would silently hide every reference below it.

## The baseline file

Committed, sorted JSON, one entry per line, keyed by repo-relative path, with no line numbers so edits elsewhere in a file never churn it:

```json
{
  "version": 1,
  "entries": [
    {"key": "README.md", "markers": 0, "bytes": 52413},
    {"key": "docs/board.md", "markers": 12}
  ]
}
```

`bytes` appears only on an over-budget README. A file not in the baseline may not appear with markers above 0. The cost: moving or renaming a file that carries markers reads as a new file, resolved with the explicit `--allow-additions`.

## Modes

```
python scripts/docs_ratchet.py                                   # check (what the gate runs)
python scripts/docs_ratchet.py --init                            # first baseline; refuses to overwrite
python scripts/docs_ratchet.py --update-baseline                 # lower or drop entries; exit 1 + write nothing if anything rose
python scripts/docs_ratchet.py --update-baseline --allow-additions   # the explicit flag that raises or adds entries
```

A failing check names each file with its count, its baseline and every marker with its kind and line, or the README's size against the budget and its baseline. The fix is to state the present-tense why in words, or to move README detail into `docs/<topic>.md`.

## Adopting it (opt-in per repo)

Re-vendoring the script never breaks a repo that has not opted in: an absent `[docs_ratchet]` table, or `enabled = false`, prints `docs ratchet: not enabled` and exits 0 (declared, not inferred).

1. Vendor `scripts/docs_ratchet.py` byte-for-byte (`/propagate-vendored docs_ratchet`; manifest key `docs_ratchet`) and declare it in the repo's `[vendored]` table. It is stdlib-only and needs Python 3.11+ (`tomllib`).
2. Add to the repo's own `.fleet.toml`:

   ```toml
   [docs_ratchet]
   enabled          = true
   baseline         = ".docs-ratchet-baseline.json"   # default
   include          = ["README.md", "docs/"]           # path prefixes; the default
   exclude          = ["docs/reports/**"]              # globs, e.g. generated per-run reports
   readme_max_bytes = 40960                            # default: 40 KiB
   allow_refs       = ["owner/repo#178"]               # exact text as written; default none
   ```

3. Run `python scripts/docs_ratchet.py --init` and commit the baseline. Review it: the first baseline records all existing debt, and an oversized README is recorded at today's size. **Adoption never requires the split first.**
4. Add a gate stage that runs `python scripts/docs_ratchet.py` and fails on any non-zero exit. The scaffold's `scripts/verify-before-ship.ps1` places it after the comment ratchet and before `mypy`. **Do not path-route it**: a count needs the whole tree.
5. If the repo uses diff-proportionate e2e routing, add a `tier = "none"` rule for the baseline file to `.fleet.toml` `[e2e]` (a root file otherwise fails safe to the full browser suite) and a matching assertion in `tests/test_classify_e2e.py`.

The script spawns `git` with `CREATE_NO_WINDOW`, derived locally (it is vendor-verbatim, so it cannot import `src/no_window.py`).

An adopter that also vendors `static_ratchet.py` will see its duplicate check flag the config-loading and glob helpers the vendored ratchets share, because each vendored file must be self-contained. Baseline that group with `--allow-additions` (this scaffold's `.static-ratchet-baseline.json` carries it).

## Cost

A dry run over throwaway copies of the README and `docs/` folder of seven fleet repos (1 to 42 Markdown files each) scanned every file without a "not confirmed" and took 0.2 to 0.7 s per repo, so there is nothing to tune. A first `--init` records real debt: from 5 markers in a small repo to over 700 in a large one, and oversized READMEs are baselined at their current size, not blocked. This scaffold's own baseline is 18 files and 285 markers, about two thirds of them inside inline code.

## Tests

`tests/test_docs_ratchet.py`: counting on fixture strings (every marker kind, and the fences, URLs, link targets, autolinks, HTML comments, anchors and entities that must not count), the README budget cases (new over budget fails, shrink passes, growth fails, under budget needs no entry, entry dropped when back under, CRLF normalised), scope and exclusions, and every mode and exit code on throwaway git repos. A missing prerequisite is a hard failure there, never `pytest.skip`. The scaffold's own gate stage doubles as the guard that its committed baseline is current, and a test pins that the two docs for this stage carry no marker themselves.
