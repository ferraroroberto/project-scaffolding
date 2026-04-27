# ADAPT_PROMPT.md

Copy-paste this prompt into a Claude Code session opened at the root of a new (or existing) repo to install the canonical agent instructions.

```
You are setting up CLAUDE.md / AGENTS.md for this repository.

1. Copy `<scaffolding>/docs/agents/CLAUDE.master.md` to `./CLAUDE.md`.
2. Copy `<scaffolding>/docs/agents/AGENTS.master.md` to `./AGENTS.md`.
3. Read README.md (or skim the top-level layout if README is missing).
4. Replace the `## This repository` placeholder at the bottom of CLAUDE.md with EXACTLY two sentences:
   - Sentence 1: what this project is (e.g., "Streamlit app for X.", "CLI tool that does Y.").
   - Sentence 2: literally `See README.md for setup, layout, and usage.`
   No more. No bullet lists. No layout duplication.
5. Delete any AGENTS_CLI.md, AGENTS_PYTHON.md, AGENTS_POWERSHELL.md, AGENTS_STRUCTURE.md, AGENTS_PR.md.
6. Grep README.md (and any docs) for links to those deleted files; replace with a link to `CLAUDE.md`.
7. If the repo uses Streamlit, grep for `use_container_width` and report any occurrences (do not fix without approval).
8. If the repo has a `venv/` folder instead of `.venv/`, report it (do not auto-rename).

Replace `<scaffolding>` with the absolute path to your local copy of project-scaffolding.
```
