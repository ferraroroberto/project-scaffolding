# ROLLOUT_RUNBOOK.md

Self-contained, followable plan to replicate the AGENTS.md / CLAUDE.md consolidation across a set of sibling repos on a different machine. Hand this prompt to a Claude Code session whose cwd contains both this `docs/agents/` directory and the parent folder of the target repos.

> Reference execution: the original rollout was planned at `~/.claude/plans/i-am-going-to-flickering-beaver.md` on the source machine — informational only.

```
You are replicating an AGENTS.md / CLAUDE.md consolidation across a set of sibling repos on this machine.

Inputs you have:
- This `docs/agents/` directory containing CLAUDE.master.md, AGENTS.master.md, ADAPT_PROMPT.md.
- A parent directory containing one or more sibling project repos (the user will name it).

Phase 0 — Discovery
1. Ask the user: parent directory path; which subfolders to skip (defaults: `old/`, `node_modules/`, anything without a README.md or requirements.txt and not obviously a code repo).
2. Per in-scope repo, inventory:
   - existing AGENTS.md / AGENTS_*.md / CLAUDE.md
   - .claude/ directory contents
   - whether Streamlit is used (grep `import streamlit` and `streamlit` in requirements.txt)
   - venv folder name (.venv vs venv vs other)
   - git remote presence (skip push if absent)
3. Per Streamlit repo, count `use_container_width` occurrences and report the file:line list.
4. Grep every README.md in scope for links to `AGENTS_PYTHON|AGENTS_CLI|AGENTS_PR|AGENTS_STRUCTURE|AGENTS_POWERSHELL`; report broken-link locations.

Phase 1 — Confirm scope with user
- Present the discovery report.
- Show proposed per-repo 2-line footers (read each README.md to draft sentence 1; sentence 2 is always "See README.md for setup, layout, and usage.").
- Ask the user to approve the list and the footers before doing any writes.

Phase 2 — Scaffold's own files (only if missing or stale)
- If `<scaffolding>/CLAUDE.md` doesn't exist or doesn't match `docs/agents/CLAUDE.master.md` (modulo footer), write it (master + scaffolding footer).
- If `<scaffolding>/AGENTS.md` is not the one-line pointer, replace it.
- If `<scaffolding>/README.md` is missing the deep scaffold guidance (logger, theme, view conventions, import rules), absorb that content from any old AGENTS.md before overwriting.

Phase 3 — Rollout per repo (≤5 file ops per phase, then verify)
For each in-scope repo, in this order:
1. Write CLAUDE.md = master + project footer.
2. Write AGENTS.md = one-line pointer ("See CLAUDE.md.").
3. Delete any AGENTS_CLI.md, AGENTS_PYTHON.md, AGENTS_POWERSHELL.md, AGENTS_STRUCTURE.md, AGENTS_PR.md.
4. Fix broken README.md links to those deleted files (replace with link to CLAUDE.md).
5. If Streamlit repo: replace `use_container_width=True` → `width="stretch"` and `use_container_width=False` → `width="content"`.
6. Verify: `grep -rn "use_container_width" <repo>` returns 0; broken-link grep returns 0; CLAUDE.md and AGENTS.md exist.
7. Boot-test Streamlit apps that received width fixes (headless, one boot per repo).
8. If user authorized commit + push: git status (sanity check), git add only expected files, git commit with the standard message (template below), git push to tracked remote. Skip push silently for repos with no remote (report at end). Never use `--no-verify`, `--amend`, or `git add -A`.

Standard commit template (adjust per repo to mention only changes that actually apply):
    docs(agents): consolidate AGENTS/CLAUDE into shared master + width=stretch fixes

    - CLAUDE.md is now canonical (full instructions); AGENTS.md points to it
    - Remove split AGENTS_*.md files (where present)
    - Migrate use_container_width=True → width="stretch" (where applicable)
    - Fix dangling README links to deleted split files (where applicable)

Phase 4 — Final verification sweep
- Repo-wide: every in-scope repo has CLAUDE.md, AGENTS.md, no split files, no use_container_width (Streamlit repos), no dangling AGENTS_*.md links.
- Report any repos that need follow-up (push skipped, .venv naming mismatch, anything unexpected).

Out of scope (call out to the user):
- `print()` → `logging` migration — see `LOGGING_MIGRATION_PROMPT.md`.
- Renaming `venv/` to `.venv/` — report only; manual recreation required (renaming an active venv breaks paths inside it on Windows).
```
