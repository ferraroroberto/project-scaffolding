# README and docs: shape and the no-history rule

How a fleet repo splits what it tells a reader between `README.md` and `docs/`, and what neither may carry. The deterministic check is the [docs ratchet](docs-ratchet.md); this page is the convention it enforces.

## Why

The README is the first file every agent and every new reader opens, so its size is a cost paid on every session. A README that has grown into a reference manual makes that cost large and buries the three things a reader came for: what the repo is, how to run it, how to verify a change.

History in a doc has a second cost: it goes stale silently. "Added in #NNN", "we changed X after the outage", a dated walk log and a changelog section all describe a past that git, the pull requests and the issues already hold, precisely and with dates. A doc that repeats them drifts from them, and teaches the next editor to append another paragraph of story instead of correcting the current statement.

The rule is the docs counterpart of the [comment ratchet](comment-ratchet.md): **a doc states what is true now and why, in the present tense. How it got that way lives in git, the pull request and the issue.**

## The README

The README is what the repo is, how to install and run it, the gate command, and a **one-line index per feature** that links to a `docs/<topic>.md`. Nothing else earns a place in it.

| Belongs in the README | Belongs in `docs/<topic>.md` |
|---|---|
| What the repo is, in a paragraph | The full description of one feature or subsystem |
| Install, configure, run | Configuration tables, every flag, every endpoint |
| The verification gate command | Design records: what is true and why it is shaped that way |
| One line per feature, linking its doc | Integration guides, playbooks, troubleshooting |
| Expiry and rotation dates (certificates, tokens, deprecations) | Limits and known false positives of a mechanism |

Budget: **40 KiB (40,960 bytes)**, measured in bytes, not lines (a README of a few hundred very long lines can be several times the size of one with a thousand short ones). A repo may set a different `readme_max_bytes` in its `[docs_ratchet]` table; the default is what the fleet expects.

### Splitting an oversized README

A split is a docs-only change that shrinks the baseline:

1. List the README's top-level sections and their sizes. Anything that is reference rather than orientation moves.
2. Move each section verbatim to `docs/<topic>.md` with a topic filename (never a date), then rewrite it in the present tense as it goes.
3. Replace it in the README with one line: the feature in a clause, then the link.
4. Delete, rather than relocate, any history narrative: dated rounds, "what changed" stories, resolved-incident write-ups. The pull request and the issue are the record.
5. Run the docs ratchet's `--update-baseline`. It lowers the README's recorded size, and drops the entry once the README is back under budget.

Do not split first and adopt later: an oversized README is baselined at today's size, and may only shrink from there.

## `docs/`

`docs/` holds **durable reference** a future reader will re-open: design records, architecture overviews, integration guides, shared playbooks. Topic filenames, never dates.

What a doc does not hold:

- **Issue and pull-request references used as narrative** ("added in #NNN", "fixed by repo#NNN"). If the reader needs the reasoning, state it. If they need the provenance, `git log -- <file>` has it.
- **Dated headings** that make a section a log entry (a walk log, a "Round N" narrative, a decision stamped into its heading). Put the decision in the present tense and, if its date matters, in prose.
- **Changelog, release-notes, release-history or "what's new" sections.** Releases and merged pull requests are the changelog.
- **Plans and TODOs.** Those are issues.

What stays legal: dates in prose where they are the point (a certificate expires on a given day, a deprecation lands on one), measurement stamps ("measured on this host"), and a link to a canonical design issue when a reader genuinely needs it. A pointer a repo wants to keep without it counting goes in `allow_refs` (exact text, empty by default); anything else is paid for with a visible baseline raise in review.

## What the check can and cannot say

The ratchet counts three lexical markers (issue references, dated headings, changelog headings) and a byte size. It cannot tell a navigational reference from a narrative one, so a legitimate pointer costs one baseline entry, visible in review. It does not judge phrasing such as "previously" or "no longer"; that stays a review call. Mechanism, exit codes and adoption steps: [docs-ratchet.md](docs-ratchet.md).
