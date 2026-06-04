# Project Instructions

Canonical instructions for AI coding agents working in this repository. Claude Code reads this file directly as project memory. Other agents (Cursor, Codex, etc.) reach it via the one-line `AGENTS.md` pointer.

## Plan mode is the default
Every non-trivial request starts in plan mode. Non-trivial = anything beyond a one-line fix, a typo, or a question I can answer without touching code.

In plan mode:
- Do NOT edit files, run destructive commands, or commit anything
- Investigate the codebase as needed (read files, search, run read-only commands)
- Resolve ambiguity through questions before proposing a plan
- Present the plan only when you're confident it reflects what I actually want
- Stay in plan mode across rejections — if I push back, revise and re-present, don't bail out to execution

Recommended setting in `.claude/settings.json`:
```json
{ "permissions": { "defaultMode": "plan" } }
```

Exit plan mode only after I explicitly approve. Approval transitions straight to execution in the same turn.

## Asking questions
Ask whenever a decision would be expensive to undo or genuinely ambiguous. One sharp question beats three filler ones. Use multi-choice (2-4 options) when the choice space is bounded — much faster for me to answer than prose.

**Always ask before assuming** any of these:
- File or module location for new code
- Data shape or schema
- Page placement (new page vs. section in existing page)
- `st.session_state` key names and scope (Streamlit projects)
- Caching strategy (`@st.cache_data` TTL vs. `@st.cache_resource`) (Streamlit projects)
- Widget `key=` names and input sources (Streamlit projects)
- Data source (upload, local file, DB via secrets)
- Error and empty-state handling
- Whether to add tests, and at what level

**Don't ask about** things you can determine by reading the code, things I've already specified, or process meta-questions like "is the plan ready?" — that's what plan approval is for.

If multiple reasonable approaches exist, present them as options with tradeoffs. Don't pick silently.

## Before editing
- Re-read any file before modifying it. Don't trust memory across long sessions.
- For files >500 LOC, read in chunks; don't assume you've seen the whole file.
- When renaming a symbol, search separately for: direct calls, type references, string literals, dynamic imports, re-exports, and tests.

## General conventions
- **Project layout** is documented in this repo's `README.md`. Don't assume `/app/`, `/src/`, `launch_app.bat`, or any specific paths exist — read the README first.
- **Config & secrets:** project config in `config.json` or similar; secrets always in `.env`, never committed. The canonical name for the env file is `.env` (not `venv` or anything else — `.venv` is the venv directory).
- **Logging:** use the language's logging facility. In Python that's `logging`, not `print()`. Emojis are welcome in log messages: ℹ️ ⚠️ ❌ ✅
- **Naming:** snake_case for files/functions (Python), PascalCase for classes, UPPER_CASE for constants.
- **Imports:** stdlib → third-party → local.
- **Versioning policy:** follow the existing style in `requirements.txt` / `package.json` — keep `==` where the file uses pins, keep `>=` where it uses lower bounds. Don't change the policy unless explicitly asked.
- **Virtual environment:** use the existing `.venv`. Never create `venv`. Never activate — invoke via `& .\.venv\Scripts\python.exe ...` on Windows, `./.venv/bin/python ...` on POSIX.
- **No hardcoded paths or credentials.**
- **Type hints** on all public Python functions. Use `Optional[T]`, never bare `None` returns.
- Implement only what was asked. No nice-to-haves.

## Streamlit conventions
*Apply only if this project uses Streamlit.*

- `st.set_page_config(layout="wide", page_title="...")` MUST be the first Streamlit call.
- Use `width="stretch"` (and `width="content"` where appropriate) in new and modified code. **Never** introduce new `use_container_width=True` — it is deprecated. When you touch existing code that uses `use_container_width`, migrate it.
- All mutable state in `st.session_state`. No module-level globals.
- `@st.cache_data` for DataFrames/files; `@st.cache_resource` for DB clients/models.
- Every widget needs a stable, explicit `key=`.
- UI code only in the UI directory (e.g. `app/`). Data logic stays in the non-UI package (e.g. `src/`). Never import `streamlit` from non-UI code.
- User feedback via `st.error()` / `st.warning()` / `st.success()`, not `st.write()`.

## End-to-end UI testing
*Apply only if this project serves a browser UI (Streamlit, Flask, etc.).*

Two loops, kept deliberately separate. Don't conflate them. Full reasoning, setup, and bootstrap recipe in the scaffold's `docs/playwright-ui-testing.md`.

### Iterative verification (headed, agent-driven)
Use this during active development so I can watch the agent verify a change.

- Drive the running app via the **Playwright MCP server in `--headed` mode** (Claude Code, Codex CLI). For tools without MCP support, fall back to a small `playwright` Python script run via Bash with `headless=False` — same shape, just less ergonomic.
- Boot the app **once** on a fixed port (Streamlit default: 8501) and leave it running. Do NOT restart between iterations unless `set_page_config` or top-level imports changed.
- Prefer the a11y `snapshot` tool over `screenshot` — DOM is far cheaper than pixels in tokens. Screenshot only on failure or as final visual confirmation.
- Cap actions per cycle in the prompt (≤ 5 actions, then report). Stop and ask if the page state is unexpected; do not loop blindly.
- Target widgets via their stable `key=` (already required by Streamlit conventions above) using `page.get_by_role(..., name=...)` or `page.get_by_test_id(...)`.
- Do NOT create files under `tests/e2e/` for verification — it's throwaway, lives in the conversation only. Promotion to a permanent test is a separate, deliberate decision (see below).

### Regression suite (headless, pytest-playwright)
Optional. Lives at `tests/e2e/`. **Don't create the folder until the first regression test is actually justified.**

- Add a test only when all three hold: (1) silent breakage would hurt, (2) it can't be caught by a unit test under `tests/`, (3) the behavior has stabilized (not still in flux).
- Runs via `& .\.venv\Scripts\python.exe -m pytest tests/e2e/` (Windows) / `./.venv/bin/python -m pytest tests/e2e/` (POSIX). No LLM in the loop, zero per-run cost.
- One shared `streamlit_app` session fixture boots the app once per pytest run.
- Keep the suite small — target < 15 tests total. If you're tempted to add #20, delete two first.
- No Page Object Model. Too much ceremony for this size.
- Don't gate commits on e2e. Run on push or in CI, not in pre-commit.
- When you remove a feature, remove its e2e test in the same commit.

## Phased execution for larger work
Multi-file refactors don't go in a single response. Break into phases of ≤5 files each. Complete phase 1, run verification, wait for my approval, then phase 2. Same rule for any task you'd estimate at >30 minutes of work.

## Verification (before declaring a task done)
Examples — adapt to the project's actual tooling:

Windows / PowerShell:
- Syntax: `& .\.venv\Scripts\python.exe -m py_compile <file>`
- Lint (if configured): `ruff check .`
- Tests (if any exist): `& .\.venv\Scripts\python.exe -m pytest`
- Streamlit boot check (UI changes): `& .\.venv\Scripts\python.exe -m streamlit run app/app.py --server.headless true`

POSIX:
- Syntax: `./.venv/bin/python -m py_compile <file>`
- Tests: `./.venv/bin/python -m pytest`

If no checker exists for a project, say so explicitly. Don't claim "tests pass" when there are no tests.

## Restart and verify before hand-off
*Apply only if this project runs a long-lived process (dev server, webapp, daemon, tray) without hot-reload.*

After the verification step — and unless I said otherwise — restart that process so the change is actually live, and confirm it: check a version/build endpoint or equivalent signal that the running process reflects the new code (not just that it answers a health check — a stale process passes health checks fine). Report the build identifier. Don't hand off "done" with a stale process still serving.

**Restart safely.** Kill only the specific process for *this* app (identify it precisely — by listening port / PID / window title), never a blanket process-name kill (`pythonw`, `node`, `python`) that would also take down sibling apps or shared services on the same machine.

**A 'start' script is usually not a 'restart' script.** Re-running `launch_app.bat` / `tray.bat` / `npm start` while an instance is already up typically just spawns a duplicate (or silently no-ops if the port is bound). The pattern is **kill-then-start**, not "run start again". Document the project-specific recipe in this repo's own `CLAUDE.md` under `## This repository` — *which* process to kill (port / PID lookup), *which* command relaunches it, *what* signal confirms the new build (e.g. `GET /api/version` returning the current `git_sha`).

**A tray restart must reclaim the app's service ports by PID (orphan-proof), not just `taskkill /T` the tray subtree.** A tray's service children (a webapp, a session-host, a tunnel) can orphan — the tray dies or is replaced while a child keeps running, so the child leaves the tray's process subtree but still holds its service port. A restart that kills only the tray PID-subtree misses the orphan; the fresh tray can't bind the port, silently fails, and the old orphan keeps serving stale code while the restart *reports success*. So `--restart` must, for each fixed loopback port the app **definitively owns**, find the current listener and kill its owning PID, **then** start. Scope the sweep to **this app's `.venv`** so sibling apps are never touched — and scope it by the holder's **CommandLine**, *not* its process image path: on Python 3.14 Windows venvs a venv-launched `pythonw.exe` re-execs the base interpreter, so the image path reports the *shared base* interpreter while only the CommandLine still carries the `.venv` path; an image-path guard never matches the real webapp and the reclaim silently no-ops. Exclude any port that is **mutex-shared** with another app (reclaiming it would kill the sibling's live process). This is the third tray-lifecycle gotcha in the fleet, alongside **#12** (single-instance via a named mutex, not a bound TCP port) and **#13** (`CREATE_NO_WINDOW` when shelling out to console tools); it does not conflict with #12 — #12 is how you *detect* a running instance, this is how a *restart cleans up* the previous one. Canonical `tray.bat` shape (idempotent detect + reclaim-then-start) and the full reasoning live in the scaffold's `docs/windows-tray.md`.

## Documentation discipline
The `docs/` folder is for **durable reference material** a future reader (you, or a cold LLM) will actually re-open — design records, architecture overviews, integration guides, shared playbooks. Filenames describe the topic, not a date.

Never put in `docs/`:
- Plans, roadmaps, TODOs, "future work" → those are GitHub issues.
- Dated per-PR changelog files (`docs/YYYY-MM-DD-*.md`) → the issue + the PR that closes it + `git log` already capture what was done, files modified, and validation run. Don't write a third copy.

For feature work and refactors:
- Update `README.md` if usage, config, or output changed.
- If the change introduces a durable concept worth re-reading (a new integration, a non-obvious architectural decision, a shared pattern), add a topic-named doc — `docs/<topic>.md`, not `docs/YYYY-MM-DD-<topic>.md`.

For one-line fixes and typos: just commit.

## Git
Never auto-commit or push. Never stage files without being asked. When a task is done, ask: "Shall I prepare the commit message?" When asked, provide a ready-to-copy block:

```bash
git add <files>
git commit -m "type: short description

- detail 1
- detail 2"
```

I run it in my own terminal.

## Senior-dev check
Before finishing, ask: "What would a senior, perfectionist dev reject in review?" If the answer points at duplicated state, inconsistent patterns, or broken architecture *within the file you're already editing*, fix it. Don't expand scope to unrelated files.

---

## This repository
<!-- Replaced per repo. Keep to two sentences max. -->
<one sentence: what this project is>.
See `README.md` for setup, layout, and usage.
