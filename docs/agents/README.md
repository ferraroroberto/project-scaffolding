# docs/agents

Single source of truth for the **project-shaped** AI agent instructions across all my repos. The universal dev-workflow directives live once in the machine config (`fleet-config/global-CLAUDE.md`); this folder owns only the shape-specific half.

## Files

- **`CLAUDE.master.md`** — canonical **project-shaped** instruction set (the shape-specific sections — Streamlit, the FastAPI + static PWA web-app shape (web-app visual identity, UX-conformance gate, HTTPS provisioning, PWA required surfaces, PWA static-asset cache-busting), FastAPI + SQLite connection lifecycle, GitHub-Actions CI, e2e UI testing, tray / long-lived process; universal dev-workflow directives live in `fleet-config/global-CLAUDE.md`, not here). Copy verbatim into any repo's `./CLAUDE.md`, then replace the `## This repository` placeholder at the bottom with two sentences.
- **`AGENTS.master.md`** — one-line pointer template. Copy verbatim into any repo's `./AGENTS.md`. Other agents (Cursor, Codex) discover it and hop to CLAUDE.md.
- **`ADAPT_PROMPT.md`** — copy-paste prompt to install the canonical instructions in a new repo.
- **`LOGGING_MIGRATION_PROMPT.md`** — separate, future-use prompt for migrating `print()` → `logging` across a repo.
- **`ROLLOUT_RUNBOOK.md`** — followable plan to replicate this whole consolidation on another machine across a different set of repos.
- **`skills/`** — pointers to machine-wide Claude Code skills. User-level skills sit *above* all projects, so their canonical home is the machine config (`ferraroroberto/fleet-config` → `skills/`), which installs them once into `~/.claude/skills/`. This folder keeps only a pointer per skill, never a verbatim fork.
  - **`skills/handoff-commit/`** — pointer to the canonical `/handoff-commit` skill in `fleet-config`. (`/handoff-commit [<commit-ish>]` generates a copy-paste markdown prompt that hands a specific pushed GitHub commit to another LLM, so it can replicate the same logical change in a sister project — e.g. public repo → private fork — without copy-pasting code.)

## Why CLAUDE.md is canonical (not AGENTS.md)

Claude Code auto-loads `CLAUDE.md` as project memory — putting the full instructions there means zero indirection for the primary tool. AGENTS.md is the standard discovery filename for other agents and points to CLAUDE.md.

## Updating the master

This repo's own `./CLAUDE.md` is the master copied verbatim — only the `## This repository` footer differs. **When you edit one, mirror the change to the other in the same commit.** Fleet-specific reality belongs in the *footer* or a sister repo's own `## This repository` block, never hardcoded into the shared body — keep the body generic so it copies cleanly into every repo.

**This is enforced, not merely asked** — `tests/test_claude_master_sync.py` asserts the two bodies are byte-identical (footer excluded) and runs in the non-e2e phase of `scripts/verify-before-ship.ps1`, so an unmirrored edit fails the gate. The prose rule alone did not hold: the same drift had to be reconciled twice (`project-scaffolding#59`, then `#211`), and it is silent *and* propagating — `ADAPT_PROMPT.md` copies the master verbatim into every new repo, so whatever the master is missing, every repo stood up from it is missing too.

When the master changes:
1. Edit `CLAUDE.master.md` here **and** mirror the same edit into this repo's `./CLAUDE.md`.
2. Re-run the rollout (see `ROLLOUT_RUNBOOK.md`) to propagate to every sibling repo.
3. Each repo's `## This repository` footer stays untouched.
