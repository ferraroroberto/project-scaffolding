# Instruction ratchet

`scripts/instruction_ratchet.py` is a baseline-and-ratchet stage for the pre-ship gate. It runs the deterministic, lint-tier rules of the fleet's weekly prompt audit over a repo's instruction files, per file and per rule, and fails when a count **rises** above a committed baseline, or when a file passes its size cap. Existing debt never blocks work; it cannot grow either. A finding the weekly audit would file as a violation is refused at ship time instead of costing a cleanup issue a week later.

It reuses the shape of the [docs ratchet](docs-ratchet.md) and the [structure ratchet](structure-ratchet.md): an opt-in `.fleet.toml` table, a committed baseline, the same flags, and exit 3 for "not confirmed". It is stdlib-only.

The rules themselves (what each one means, why the vendor guides ask for it, and the fix shape) live in fleet-config's `.claude/skills/prompt-audit/rules.md`. This page covers only the mechanism.

## What is counted

The instruction files in scope, each with a **kind**:

| Kind | Files |
|---|---|
| `claude-md` | The root `CLAUDE.md`, and any `extra_files` entry whose name ends in `CLAUDE.md` |
| `agents-md` | The root `AGENTS.md` |
| `rules` | `.claude/rules/*.md` |
| `skill` | `<skill_dir>/<name>/SKILL.md` for each `skill_dirs` entry (default `.claude/skills`) |
| `skill-ref` | A `.md` file a `SKILL.md` references, by markdown link or by a backticked relative path that exists (never another skill's `SKILL.md`, an always-on file, or anything under `conversations/`, `evals/`, `__pycache__/`) |

### The reader decides the cap

A rule is tagged with whose guidance it is: `shared` (both vendors), or one vendor. A shared rule is a **violation** in any file. A single-vendor rule is a violation only in a file or section scoped to that vendor's agent; in an agent-neutral file it is at most **consider**, and in a file scoped to the other vendor it does not apply. **Only violation-cap hits are counted.** Considers stay advisory in the weekly digest, as they do in the audit.

The reader comes from the file, never from the host running the check:

- `.claude/rules/*.md` is read by Claude Code only.
- A `CLAUDE.md` is read by Claude Code only **unless** the repo's `AGENTS.md` names it (the fleet's one-line pointer), which makes it agent-neutral.
- Everything else is agent-neutral.
- A heading carrying `Claude Code only` or `Codex only` scopes its section to that reader.

So in a typical repo, whose `AGENTS.md` points at `CLAUDE.md`, the counted rules are the shared ones: R-03, R-04, R-14, R-16 and R-17, plus R-36's relative backslash paths, which the audit always caps at violation.

### Enforced rules

| Rule | Counts |
|---|---|
| R-01 to R-12, R-30, R-45 | Phrase patterns in prose: ALL-CAPS pressure words, blanket tool defaults, forced re-check lines, periodic progress scaffolding, narration suppression, anti-formatting lines, hand-written reasoning plans, "do not think" rules, recall-suppressing review lines, prefill or thinking-budget references, dated phrasing, upfront-plan demands, reasoning-in-the-answer lines, blanket tool-use discouragement |
| R-14 | Size caps: `CLAUDE.md` and rules files over 200 lines, a `SKILL.md` body over 500 lines, `AGENTS.md` over 32,768 bytes |
| R-15 | A skill description over 1,024 characters, first- or second-person words in its prose (double-quoted trigger phrases excluded), an XML tag in it, or a `name` that is not 1 to 64 characters of `[a-z0-9-]` |
| R-16 | The same action phrase under both an always/must and a never/do-not modal in one file |
| R-17 | An agent-neutral paragraph that names one vendor's products (`Claude`, `Anthropic`; `Codex`, `OpenAI`, `GPT`) and not the other's, without a scope marker |
| R-34 | A skill's reference doc that links a further local `.md` the `SKILL.md` does not reference itself |
| R-35 | A skill's reference doc over 100 lines with no Contents heading in its first 40 lines |
| R-36 | A backslash path in a `SKILL.md` |

Fenced code blocks, inline code spans and frontmatter are not linted (R-36 reads inline code, because that is what gets copied). The count is per file and per rule, so a new hit in one file cannot hide behind a removal in another.

### File-shape rules (opt-in)

Four rules check the shape of the instruction files rather than their lines (S-04 has its own section below). Each is **off until the repo's `[instruction_ratchet]` table turns it on**, so re-vendoring the script never turns an adopter red. Once on, a finding is baselined like any other count (key = the file it is about, even a missing one), may only shrink, and its report line names the fix.

| Rule | Option | Counts |
|---|---|---|
| S-01 | `ci_expectations = true` | A repo with any file under `.github/workflows/` (a `*.yml.template` included) whose root `CLAUDE.md` has no `CI expectations` heading outside a code fence, or has no `CLAUDE.md`. `/issue-finish` reads that section to decide whether to wait for CI and falls back to always watching without it. One hit, on `CLAUDE.md`. |
| S-02 | `agents_pointer = true` | An `AGENTS.md` that is missing, does not name `CLAUDE.md`, or has more than 10 non-blank lines (a copy rather than a pointer). One hit, on `AGENTS.md`. |
| S-03 | `claude_md_max_lines = N` | The root `CLAUDE.md` past `N` lines, counted as the number of lines over, so the baseline falls as the file shrinks. Set it for an app repo (fleet apps use 120); R-14's 200-line cap still applies to every repo. Only the root file is measured, not an `extra_files` entry or a rules file. |
| S-04 | `repeated_text_words = N`, `repeated_text_global = true` | Text a `CLAUDE.md` repeats from `docs/` or the global file; see the next section. |

### Repeated text (S-04, opt-in)

`CLAUDE.md` should point to a doc rather than restate it; restated text costs every session its tokens and drifts from the original. S-04 counts the runs of `repeated_text_words = N` or more consecutive words that a `CLAUDE.md` shares with a source. It is **off until the table sets that key** (a whole number, 5 or more; the fleet default is 12), so re-vendoring never turns an adopter red; once on, hits are baselined per file like any other count and may only shrink.

- **Sources.** Every tracked `docs/**/*.md`, plus the owner's global `~/.claude/CLAUDE.md` when `repeated_text_global = true`. An instruction file under `docs/` is compared, never a source, and a file is never compared with itself (a repo that carries the global file as `extra_files` is checked against `docs/` only).
- **Compared text.** The prose of each file: frontmatter, fenced blocks and inline code are dropped, then words are lowercased alphanumerics, so wrapping, markdown marks and punctuation do not hide a copy.
- **Counted.** One hit per maximal run, so a pasted paragraph is one hit however long it is, and two separate copies are two. The report line names the first line of the run, its length and the source; the fix is to replace the text with a pointer to the source.
- **Not confirmed.** `repeated_text_global = true` with no readable global file is exit 3, never a pass: the global file exists only on the owner's machine, so a repo that runs this gate in CI leaves `repeated_text_global` off. The option needs the `instruction_repeats` sibling; a script without it exits 3 only when the option is on.

### Not enforced

| Rule | Why it stays with the weekly audit |
|---|---|
| R-13 positive framing | The lint counts every line with a negative word, but the rule judges the file's ratio. A ratchet on the count would refuse every legitimate new prohibition. |
| R-37 fully qualified tool names | Its vocabulary is every qualified tool name across the whole fleet's skills, so a commit in another repo could fail this one. It is not decidable from one tree. |

Judgment rules, the lint-assisted candidates for R-39 and R-43, and the eval rule R-44 are out of scope by definition.

### Limits

- **A hit is a candidate.** The weekly audit's judgment pass clears some lint hits (a re-check line that names the real gate command is compliant under R-03). Here a legitimate new hit costs one `--allow-additions`, visible in review. Rewording is usually the better fix.
- **R-45 counts from day one.** The audit holds a new rule at consider for its first weekly cycle as a noise guard for its digest; existing hits here are baselined anyway, so the ratchet applies the rule as tagged.
- **`AGENTS.md` bytes are measured with CRLF normalised to LF**, so a Windows checkout and CI agree. The audit reads raw bytes, so a CRLF checkout within a few hundred bytes of the cap can differ.

## Scope

Files come from `git ls-files --cached --others --exclude-standard`, spawned with `GIT_OPTIONAL_LOCKS=0`: tracked files and new untracked ones are linted, never ignored ones, and only the root `CLAUDE.md` and `AGENTS.md` (a nested `CLAUDE.md` is not read). Reference docs are found from the skills in scope. An `extra_files` entry that is absent from that list (missing, or ignored) is a configuration error.

## Exit codes

| Exit | Meaning | Gate |
|---|---|---|
| `0` | Pass (nothing above its baseline), or the stage is **not enabled** | continues |
| `1` | A count rose, a file passed its size cap without an entry or past its entry, or the baseline file is missing | fails |
| `2` | Bad `[instruction_ratchet]` table, an `extra_files` entry that is missing or ignored, unreadable baseline, bad arguments | fails |
| `3` | **NOT CONFIRMED**: `git` unusable, a file that cannot be read or is not UTF-8, a fenced block that never closes, or a skill whose `description:` cannot be read (missing, or frontmatter a YAML loader would reject or truncate) | fails |

Exit 3 is its own state and never folded into a pass. An unclosed fence would hide every line below it; an unreadable description is a skill that has lost its routing text, which the audit reports as unmeasured.

## The baseline file

Committed, sorted JSON, one entry per line, keyed by repo-relative path, with no line numbers so edits elsewhere in a file never churn it:

```json
{
  "version": 1,
  "entries": [
    {"key": "CLAUDE.md", "hits": {"R-03": 1}, "size": 236},
    {"key": ".claude/skills/release/SKILL.md", "hits": {"R-17": 2}}
  ]
}
```

`hits` counts violation-cap hits per rule. `size` appears only on a file over its cap (lines, or bytes for `AGENTS.md`), which may then only shrink; back under the cap, the next `--update-baseline` drops it. Moving or renaming a file with hits reads as a new file, resolved with the explicit `--allow-additions`.

## Modes

```
python scripts/instruction_ratchet.py                                   # check (what the gate runs)
python scripts/instruction_ratchet.py --init                            # first baseline; refuses to overwrite
python scripts/instruction_ratchet.py --update-baseline                 # lower or drop entries; exit 1 + write nothing if anything rose
python scripts/instruction_ratchet.py --update-baseline --allow-additions   # the explicit flag that raises or adds entries
```

A failing check names each file, the rule and its title, the count against its baseline (or the size against the cap), and every hit with its line. Over a size cap, the fix is to move scoped detail into a skill, a rules file or a referenced doc; an `@path` import does not shrink the budget, and deleting directives to pass is never the fix.

## Adopting it (opt-in per repo)

Re-vendoring the script never breaks a repo that has not opted in: an absent `[instruction_ratchet]` table, or `enabled = false`, prints `instruction ratchet: not enabled` and exits 0 (declared, not inferred).

1. Vendor `scripts/instruction_ratchet.py` and its siblings `scripts/instruction_frontmatter.py` and `scripts/instruction_repeats.py` byte-for-byte (`/propagate-vendored instruction_ratchet,instruction_frontmatter,instruction_repeats`; manifest keys of the same names) and declare all three in the repo's `[vendored]` table. A script without `instruction_frontmatter` exits 3, never a pass; without `instruction_repeats` it exits 3 only once `repeated_text_words` is set. It needs Python 3.11+ (`tomllib`).
2. Add to the repo's own `.fleet.toml`:

   ```toml
   [instruction_ratchet]
   enabled     = true
   baseline    = ".instruction-ratchet-baseline.json"   # default
   skill_dirs  = [".claude/skills"]                      # default; each holds <name>/SKILL.md
   extra_files = []                                      # more instruction files, e.g. a global CLAUDE.md
   ci_expectations     = true                            # S-01, optional, default off
   agents_pointer      = true                            # S-02, optional, default off
   claude_md_max_lines = 120                             # S-03, optional, default off; an app repo
   repeated_text_words = 12                              # S-04, optional, default off; a run of 12 shared words is a hit
   repeated_text_global = false                          # S-04, optional; true also compares ~/.claude/CLAUDE.md (owner's machine only)
   ```

   A repo that ships skills from another folder lists it in `skill_dirs` (fleet-config: `["skills", ".claude/skills"]`, with `extra_files = ["global-CLAUDE.md"]`).
3. Run `python scripts/instruction_ratchet.py --init` and commit the baseline. Review it: it records every existing violation-cap hit and every over-cap file at today's size. **Adoption never requires the cleanup first**; burn-down issues lower it.
4. Add a gate stage that runs `python scripts/instruction_ratchet.py` and fails on any non-zero exit. The scaffold's `scripts/verify-before-ship.ps1` places it after the structure ratchet and before `mypy`. **Do not path-route it**: the reader of one file depends on another (`AGENTS.md`), and a skill's reference docs live outside its folder.
5. If the repo uses diff-proportionate e2e routing, add a `tier = "none"` rule for the baseline file to `.fleet.toml` `[e2e]` and a matching assertion in `tests/test_classify_e2e.py`.

The script spawns `git` with `CREATE_NO_WINDOW`, derived locally (it is vendor-verbatim, so it cannot import `src/no_window.py`).

## One implementation

The rule logic is a port of the prompt audit's `prompt_audit/lint.py` and its helpers (fence handling, frontmatter validation, reference resolution, audience scoping). `tests/ratchets/test_instruction_ratchet.py` holds the drift guard: with a fleet-config checkout beside this repo (or `FLEET_CONFIG_DIR` set) it asserts the size caps, rule tags, patterns and audiences match the audit's, and that both engines give the same hits, line for line, on a fixture tree and on this repo's own files. Without a checkout the drift tests report as skipped with the reason, never as passed. This lets the audit import this script's rule tables instead of keeping its own copy.

## Cost

Over 287 instruction files in the fleet's repos the port gave the same hits as the audit's engine on every file. A run takes about 0.1 s on this scaffold (two files), 0.2 s on a repo with 26 instruction files and about 1 s on fleet-config (70 files). This scaffold's own baseline is empty: its `CLAUDE.md` and `AGENTS.md` carry no violation-cap hit, `CLAUDE.md` is within its 200-line cap and has a `CI expectations` section, and `AGENTS.md` is a pointer.

## Tests

`tests/ratchets/test_instruction_shape.py` covers the three file-shape rules S-01 to S-03 (options, what each counts and ignores, the ratchet and the fix named in the report, the sibling and the scaffold's own adoption). `tests/ratchets/test_instruction_repeats.py` covers S-04: the finder (merged runs, the word floor, formatting-blind matching), the options, the `docs/` and global sources, self-comparison, the "not confirmed" causes and the sibling. `tests/ratchets/test_instruction_ratchet.py`: the configuration contract, the reader rules (pointer, rules files, scope-marker sections, other-vendor rules), every enforced rule family and what must not count (fences, inline code, frontmatter, R-13, R-37), the size caps per kind with CRLF normalisation, every "not confirmed" cause, every mode and exit code on throwaway git repos, the scaffold's own adoption and gate wiring, and the drift guard against the prompt audit.
