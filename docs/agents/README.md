# docs/agents

Single source of truth for AI agent instructions across all my repos.

## Files

- **`CLAUDE.master.md`** — canonical instruction set. Copy verbatim into any repo's `./CLAUDE.md`, then replace the `## This repository` placeholder at the bottom with two sentences.
- **`AGENTS.master.md`** — one-line pointer template. Copy verbatim into any repo's `./AGENTS.md`. Other agents (Cursor, Codex) discover it and hop to CLAUDE.md.
- **`ADAPT_PROMPT.md`** — copy-paste prompt to install the canonical instructions in a new repo.
- **`LOGGING_MIGRATION_PROMPT.md`** — separate, future-use prompt for migrating `print()` → `logging` across a repo.
- **`ROLLOUT_RUNBOOK.md`** — followable plan to replicate this whole consolidation on another machine across a different set of repos.

## Why CLAUDE.md is canonical (not AGENTS.md)

Claude Code auto-loads `CLAUDE.md` as project memory — putting the full instructions there means zero indirection for the primary tool. AGENTS.md is the standard discovery filename for other agents and points to CLAUDE.md.

## Updating the master

When the master changes:
1. Edit `CLAUDE.master.md` here.
2. Re-run the rollout (see `ROLLOUT_RUNBOOK.md`) to propagate to every sibling repo.
3. Each repo's `## This repository` footer stays untouched.
