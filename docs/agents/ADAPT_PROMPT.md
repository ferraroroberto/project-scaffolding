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
9. If this repo runs a Windows tray that owns a long-lived service (a webapp, session-host, hub, … on a fixed loopback port), copy `<scaffolding>/tray.bat.template` to `./tray.bat` and replace the four `__PLACEHOLDER__` tokens: `__APP_NAME__` (used in messages + the window title), `__TRAY_LAUNCH__` (the args python starts the tray with, e.g. `launcher.py tray` or `-m tray`), `__TRAY_MATCH__` (a regex matching that invocation in a CommandLine, e.g. `launcher\.py\s+tray`), and `__OWNED_PORTS__` (comma list of ports this tray *exclusively* owns — exclude any mutex-shared port). This gives the app the orphan-proof `tray.bat --restart` by default; see `<scaffolding>/docs/windows-tray.md`. If the repo is not a tray app, skip this. If it already has a `tray.bat`, report it rather than overwriting.
10. If this repo runs a Windows tray (i.e. you did step 9), also copy `<scaffolding>/app/tray/tray_lifecycle.ps1` and `<scaffolding>/app/tray/single_instance.py` to `./app/tray/` **byte-for-byte** — `tray.bat` hard-errors without `tray_lifecycle.ps1` (the detect → kill → reclaim → start → verify lifecycle) and the single-instance/adopt-or-spawn race guard lives in `single_instance.py`. Both are vendored verbatim; only the mutex *names* differ per app. See `<scaffolding>/docs/windows-tray.md`. If the repo is not a tray app, skip this. If a file already exists, report it rather than overwriting.
11. If this repo serves a FastAPI + static PWA web app (not a Streamlit POC spike), vendor the relevant shared UI components from `<scaffolding>/app/webapp/static/_vendored/<component>/` (e.g. `nav/` for the canonical floating bottom-tab pill, `icons/` for the icon sprite) into `./app/webapp/static/_vendored/` **byte-for-byte** per `<scaffolding>/app/webapp/static/_vendored/README.md` — adapt only your own markup (which tabs) and the `storageKey`, never fork a component per-app. If the repo serves no web UI, skip this. If a component folder already exists, report it rather than overwriting.

Replace `<scaffolding>` with the absolute path to your local copy of project-scaffolding.
```
