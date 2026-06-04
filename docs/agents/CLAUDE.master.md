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
- Reproduce before fixing: for any non-trivial bug, write a repro (script, failing test, or documented sequence) before the fix. Forces real understanding; stops "I think this fixes it" → ship → rollback.
- Re-verify the issue's premise: spend 5 min confirming the symptom still reproduces and the code matches the issue before starting. Stale briefs waste PRs.
- `git log -- <file>` the area first. Prior attempts at the same fix are the cheapest source of truth.

## While fixing
- Empirical proof for retry/timeout/backoff logic. Loops that react to return values encode assumptions about API semantics — verify the assumption with a 10-line probe before shipping.
- Distinct error messages for distinct conditions. If "down" and "in flight past timeout" need different responses, they need different messages. Same-message-different-cause is how users stack orphan state.
- Don't bundle independently-revertable bugs in one PR. If bug-A's commit can revert without breaking bug-B's fix, ship two PRs.
- Leave log breadcrumbs after a hard bug. The next occurrence should be diagnosable from logs, not screenshots. Add the info-level log in the same commit as the fix.
- Test-plan checkboxes are observed, not aspirational. `[x]` means "I ran this and saw it pass." If a box can't be checked now, the PR isn't ready now — check it or drop it.

## General conventions
- **Project layout** is documented in this repo's `README.md`. Don't assume `/app/`, `/src/`, `launch_app.bat`, or any specific paths exist — read the README first.
- **Config & secrets:** project config in `config.json` or similar; secrets always in `.env`, never committed. The canonical name for the env file is `.env` (not `venv` or anything else — `.venv` is the venv directory).
- **Logging:** use the language's logging facility. In Python that's `logging`, not `print()`. Emojis are welcome in log messages: ℹ️ ⚠️ ❌ ✅
- **Naming:** snake_case for files/functions (Python), PascalCase for classes, UPPER_CASE for constants.
- **Imports:** stdlib → third-party → local.
- **Versioning policy:** follow the existing style in `requirements.txt` / `package.json` — keep `==` where the file uses pins, keep `>=` where it uses lower bounds. Don't change the policy unless explicitly asked.
- **Virtual environment:** use the existing `.venv`. Never create `venv`. Never activate — invoke via `& .\.venv\Scripts\python.exe ...` on Windows, `./.venv/bin/python ...` on POSIX.
- **Running scripts that import project packages:** Python sets `sys.path[0]` to the *script's* directory, not CWD. A script at `E:\tmp\smoke.py` cannot `from app... import ...` even if you `cd` to the project first. Two acceptable patterns:
  - Script lives **inside** the repo (gitignored `./scratch/` etc.): run with `& .\.venv\Scripts\python.exe -m scratch.foo` from the project root. `-m` adds CWD to `sys.path`.
  - Script lives **outside** the repo (e.g. `E:\tmp\`): prepend `$env:PYTHONPATH = (Get-Location).Path;` (POSIX: `PYTHONPATH=$(pwd)`) before invoking the venv Python.
  Never invoke `& .\.venv\Scripts\python.exe E:\tmp\foo.py` from a project root and expect `app.*` or `src.*` to resolve — they won't.
- **No hardcoded paths or credentials.**
- **Type hints** on all public Python functions. Use `Optional[T]`, never bare `None` returns.
- Implement only what was asked. No nice-to-haves.
- Three similar lines beats a premature abstraction. Add a helper on the third caller, not the second. Don't wrap framework scaffolds on day one.
- Conventional commit prefixes, always: `feat:` `fix:` `refactor:` `docs:` `chore:` `test:` `perf:`. Makes `git log --oneline` scannable and PR-body commit tables possible.

## Streamlit conventions
*Apply only if this project uses Streamlit.*

- `st.set_page_config(layout="wide", page_title="...")` MUST be the first Streamlit call.
- Use `width="stretch"` (and `width="content"` where appropriate) in new and modified code. **Never** introduce new `use_container_width=True` — it is deprecated. When you touch existing code that uses `use_container_width`, migrate it.
- All mutable state in `st.session_state`. No module-level globals.
- `@st.cache_data` for DataFrames/files; `@st.cache_resource` for DB clients/models.
- Every widget needs a stable, explicit `key=`.
- UI code only in the UI directory (e.g. `app/`). Data logic stays in the non-UI package (e.g. `src/`). Never import `streamlit` from non-UI code.
- User feedback via `st.error()` / `st.warning()` / `st.success()`, not `st.write()`.
- **App layout:** main file (e.g. `app.py`) handles only page config, shared state, sidebar, and tab/radio routing. Each tab/mode lives in its own file exposing a `main(...)` (or `render_*`) function. Default to `st.tabs()`; use a sidebar radio only when asked.

## GitHub Actions CI conventions
*Apply whenever this project adds a `.github/workflows/` file.*

- **Pin a dated Windows runner.** Use `runs-on: windows-2025`, never `windows-latest`. GitHub is redirecting `windows-latest` to `windows-2025` (deadline June 2026); for a Windows-only tray/daemon app that spawns real processes (PTYs, uvicorn, Chromium), the OS image silently changing under you is exactly the environment shift that turns a green gate red without a code change. Pin the label so the runner is an explicit, reviewable choice.
- **Use Node-24 action majors.** `actions/checkout@v4`, `actions/setup-python@v5`, and `actions/upload-artifact@v4` all run on Node 20, which is deprecated (forced Node 24 starting June 16 2026; Node 20 removed September 16 2026). Use the current majors that run on Node 24: `checkout@v6`, `setup-python@v6`, `upload-artifact@v7`. Inputs are unchanged for standard usage, so the bump is drop-in.

Canonical pattern:

```yaml
jobs:
  <job>:
    runs-on: windows-2025          # not windows-latest — pin the OS image
    steps:
      - uses: actions/checkout@v6        # Node 24 (not @v4 / Node 20)
      - uses: actions/setup-python@v6    # Node 24 (not @v5 / Node 20)
        with:
          python-version: '3.12'
      # ...
      - uses: actions/upload-artifact@v7 # Node 24 (not @v4 / Node 20)
        with:
          name: <name>
          path: <path>
```

**Sister-repo tracking:** when a fleet repo still has the old runner/actions, it carries a pointer issue back to `ferraroroberto/project-scaffolding#25` (the canonical decision record). Fix it before the deprecation deadline rather than after.

## End-to-end UI testing
*Apply only if this project serves a browser UI (Streamlit, FastAPI, Flask, etc.).*

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
- **One shared session fixture boots the app — and any service dependencies** (a separate API process, a worker, a PTY host, …) — once per pytest run. Boot on a fixed or free port; **adopt** an instance already listening rather than spawning a second. The fixture is engine-agnostic: `streamlit run`, `uvicorn`, `flask run` are all just the launch command.
- **Boot failure is a hard failure — never `pytest.skip`.** A regression suite that skips when the app isn't up reports green on a build it never tested; that is the exact rot this suite exists to prevent. Skip is fine for the *ad-hoc* "use whatever tray I have running" path; the *pre-ship* path must fail loud.
- Keep the suite small — target < 15 tests total. If you're tempted to add #20, delete two first.
- No Page Object Model. Too much ceremony for this size.
- Don't gate commits on e2e. Run on push or in CI, not in pre-commit.
- When you remove a feature, remove its e2e test in the same commit.

### Mobile / phone-first UI testing
*Apply only if the app's primary surface is a phone.*

- Project the regression suite onto **WebKit** with a device-emulation descriptor (Playwright ships iPhone / Android descriptors — viewport, user-agent, touch, scale factor). WebKit shares the iOS Safari rendering + JS engine, so it reproduces the large majority of "Safari is unhappy" bugs on a Windows/Linux box, before they reach a real phone.
- Make the projection **always-on** — a parametrised `browser_name` / device fixture so every test runs the mobile projection too. An opt-in projection gets forgotten.
- WebKit-on-Windows is *not* real iOS: no iOS shell, no real WKWebView memory limits, no Apple keyboard, no Add-to-Home-Screen container. For the residual shell-only bugs, attach PC DevTools to a real phone via `ios-webkit-debug-proxy` (bridges the iOS Web Inspector to a local port Edge/Chrome DevTools can attach to). Playwright cannot drive real iOS Safari — only its bundled WebKit and the iOS Simulator on macOS.

## Execution: scope up front, then carry it through
- Front-load the questions. Settle scope, ambiguity, and hard-to-undo decisions *before* starting — that is the main control point.
- Once scope is agreed, execute end-to-end to a verified, shippable state. Don't stop for per-phase approval; "large" is not "stop".
- Checkpoint on risk, not size. Pause mid-task only for what the agreed scope didn't cover: a real ambiguity, an unforeseen decision, or a finding that contradicts the plan.
- Verify every unit before calling it done (see Verification).

## Chaining connected work
- Issues are split for tracking but are often sequential. After finishing and verifying a unit, check the related open issues.
- If the next step is a natural continuation, state it and proceed — new branch off freshly-merged `main`. Pause for approval only when it's risky, ambiguous, or materially bigger than discussed.
- One branch per coherent unit. Keep commits and branches separable so any piece reviews and reverts on its own; don't sprawl one branch across unrelated issues.

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

**Pre-ship gate (projects with an e2e suite).** Once a project has a regression suite, wire a single project-specific command — e.g. `scripts/verify-before-ship.ps1` — that runs the whole pipeline as one pass/fail: byte-compile → unit `pytest` → e2e suite (auto-booting the app per the harness rule in "End-to-end UI testing"). Make it mandatory before any UI-touching change is declared done. One command, can't half-skip. Do **not** substitute a bare `pytest` run that silently skips e2e when no server is up — that is how a regression ships looking green.

If no checker exists for a project, say so explicitly. Don't claim "tests pass" when there are no tests.

## Restart and verify before hand-off
*Apply only if this project runs a long-lived process (dev server, webapp, daemon, tray) without hot-reload.*

After the verification step — and unless I said otherwise — restart that process so the change is actually live, and confirm it: check a version/build endpoint or equivalent signal that the running process reflects the new code (not just that it answers a health check — a stale process passes health checks fine). Report the build identifier. Don't hand off "done" with a stale process still serving.

**Restart safely.** Kill only the specific process for *this* app (identify it precisely — by listening port / PID / window title), never a blanket process-name kill (`pythonw`, `node`, `python`) that would also take down sibling apps or shared services on the same machine.

**A 'start' script is usually not a 'restart' script.** Re-running `launch_app.bat` / `tray.bat` / `npm start` while an instance is already up typically just spawns a duplicate (or silently no-ops if the port is bound). The pattern is **kill-then-start**, not "run start again". Document the project-specific recipe in this repo's own `CLAUDE.md` under `## This repository` — *which* process to kill (port / PID lookup), *which* command relaunches it, *what* signal confirms the new build (e.g. `GET /api/version` returning the current `git_sha`).

**A tray restart must reclaim the app's service ports by PID (orphan-proof), not just `taskkill /T` the tray subtree.** A tray's service children (a webapp, a session-host, a tunnel) can orphan — the tray dies or is replaced while a child keeps running, so the child leaves the tray's process subtree but still holds its service port. A restart that kills only the tray PID-subtree misses the orphan; the fresh tray can't bind the port, silently fails, and the old orphan keeps serving stale code while the restart *reports success*. So `--restart` must, for each fixed loopback port the app **definitively owns**, find the current listener and kill its owning PID, **then** start. Scope the sweep to **this app's `.venv`** so sibling apps are never touched — and scope it by the holder's **CommandLine**, *not* its process image path: on Python 3.14 Windows venvs a venv-launched `pythonw.exe` re-execs the base interpreter, so the image path reports the *shared base* interpreter while only the CommandLine still carries the `.venv` path; an image-path guard never matches the real webapp and the reclaim silently no-ops. Exclude any port that is **mutex-shared** with another app (reclaiming it would kill the sibling's live process). This is the third tray-lifecycle gotcha in the fleet, alongside **#12** (single-instance via a named mutex, not a bound TCP port) and **#13** (`CREATE_NO_WINDOW` when shelling out to console tools); it does not conflict with #12 — #12 is how you *detect* a running instance, this is how a *restart cleans up* the previous one. Canonical `tray.bat` shape (idempotent detect + reclaim-then-start) and the full reasoning live in the scaffold's `docs/windows-tray.md`.

## Documentation discipline
The `docs/` folder is for **durable reference material** a future reader (you, or a cold LLM) will actually re-open — design records, architecture overviews, integration guides, shared playbooks (e.g. `docs/playwright-ui-testing.md`). Filenames describe the topic, not a date.

Never put in `docs/`:
- Plans, roadmaps, TODOs, "future work" → those are GitHub issues.
- Dated per-PR changelog files (`docs/YYYY-MM-DD-*.md`) → the issue + the PR that closes it + `git log` already capture what was done, files modified, and validation run. Don't write a third copy.

For feature work and refactors:
- Update `README.md` if usage, config, or output changed.
- If the change introduces a durable concept worth re-reading (a new integration, a non-obvious architectural decision, a shared pattern), add a topic-named doc — `docs/<topic>.md`, not `docs/YYYY-MM-DD-<topic>.md`.

For one-line fixes and typos: just commit.

- Rotation / expiration dates go in README, not memory. Certs, tokens, API deprecations, vendor deadlines — anything with a future expiry gets a calendar-anchored line in README. Memory decays; READMEs get read.

## Planning future work
Plans, roadmaps, proposed features live as **GitHub issues** on this repo, never as files in the tree. One issue per topic. Issues must be self-contained enough to hand off cold.

**Defaults on `gh issue create`:** always pass `--assignee @me` and at least one type label (`bug`, `enhancement`, `refactor`, `docs`, `chore`, `test`, `perf` — mirroring commit prefixes; `meta` for cumulative/rollback context issues). Create the label first if missing (`gh label create <name>`). No untagged, unassigned issues.

**Issue template (non-trivial work):**
- **Why** (or **Symptom** + **Root cause** for bugs)
- **Scope** — what's in
- **Out of scope** — explicit non-goals (prevents scope creep)
- **How to verify** — concrete acceptance steps
- **Constraints worth knowing** — env, gotchas, file refs not obvious from code

**Decompose:** if it can't be one PR, split into "Step N/M" sub-issues, each independently shippable. Don't ship "phase 1 of 4" PRs.

**Closing:**
- `Closes #N` in PR body for auto-close on merge.
- For issues closed by direct commit, paste the SHA in a closing comment.
- Close not-planned with a comment explaining the empirical disproof when the premise turns out wrong. No zombie issues.

**Cross-repo:** if a bug lives in a shared script/pattern, file the same issue in each affected sister repo and cross-link by URL.

**On rollback:** file a `meta`-labeled issue capturing what was attempted, what worked/didn't, why — plus a checkbox list of items "conceptually still open" so re-introduction has a roadmap. Reference rollback SHA + base-of-truth SHA explicitly.

## Branch & PR pipeline
`main` is always shippable. One issue → one branch → one PR → merge → branch deleted, issue closed.

Branch naming: `<type>/<issue-N>-<short-slug>` — e.g. `fix/28-terminal-reconnect`, `feat/30-osc-title`. Type matches the commit prefix.

**Lifecycle:**
1. Open the branch off latest `main`.
2. First push → open PR as **draft** with the issue's acceptance checklist copied into the body. Surfaces direction early; cheap to course-correct.
3. While in draft: commits land freely, each with a conventional prefix. Keep the PR body's checklist up to date.
4. When acceptance checks pass, promote to **ready for review/merge**.
5. Merge: squash by default. Keep multi-commit history only when each commit is independently meaningful (cumulative rounds — see below). Always auto-delete the branch on merge.
6. After merge: `git checkout main && git pull && git branch -d <branch>` locally; `git fetch --prune` to drop the remote ref. Confirm the issue auto-closed.

**Hard rules:**
- Never commit to `main` directly.
- Never force-push a branch someone else (or a CI run) might have pulled.
- Never stack a second feature branch on an unmerged first — rebase or wait.
- One feature/fix per branch. If mid-branch you discover an unrelated bug, file an issue and start a new branch; don't smuggle it in.

**PR body discipline:**
- Single-commit PR: `Summary` + `Test plan` checklist + `Closes #N`.
- Multi-commit / cumulative PR: per-commit table (`SHA | What | Why`) + `Closed in this PR` + `Still open` sections.

**Cumulative branch (exception, not default):**
- Allowed only for rapid iterative rounds where each commit is verified end-to-end and the next builds on it.
- Document the policy in the PR body ("branch stays alive after merge, next round continues on top").
- Default back to one-issue-one-branch as soon as the round closes.

**Never stack hotfixes on hotfixes.** If a fix exposes a new bug, revert before adding a third change on top. If three same-day PRs interact badly, roll back to last known-good and re-introduce one at a time on separate branches.

## Project hygiene
- Restart the minimum. If the project runs multiple long-lived processes, document a one-line restart matrix in README (touched X → restart Y). Restarting more than necessary loses warm state and breaks sister processes.
- Pinned known-good worktree for risky work. For architectural changes, keep a parallel checkout pinned at the last known-good commit for live A/B comparison. Don't touch the pinned tree until the risky work re-stabilizes on main.

## Git
Never auto-commit or push, never stage files without being asked. When a task is done, prepare a relevant commit message, ready to copy for the user. Never add `Co-Authored-By: Claude` (or any other LLM/AI attribution trailer) to commit messages.

Use conventional commit prefixes (`feat:` `fix:` `refactor:` `docs:` `chore:` `test:` `perf:`). Multi-line body: first line ≤72 chars, blank line, then bullets explaining *why* not *what*.

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
