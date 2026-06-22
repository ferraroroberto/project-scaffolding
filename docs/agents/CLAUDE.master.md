# Project Instructions

Canonical instructions for AI coding agents working in this repository. Claude Code reads this file directly as project memory. Other agents (Cursor, Codex, etc.) reach it via the one-line `AGENTS.md` pointer.

> **Scope — project-shaped guidance only.** This master owns only what is *specific to a project's shape* — Streamlit, GitHub-Actions CI, end-to-end UI testing, a tray / long-lived process — each section gated *"apply only if…"* and inherited by a project of that shape. **Universal** dev-workflow directives (plan mode, asking, before/while editing, execution, conventions, git, branch & PR pipeline, planning, documentation discipline, senior-dev check) live once in the machine config (`fleet-config/global-CLAUDE.md`, installed as `~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md`) and are **not** restated here. The test for any rule: *"would it apply to a bare repo with no app?"* Yes → global; no → here. Nothing belongs in both — the `/context-audit` skill enforces this single-home split weekly. (Standard: `ferraroroberto/project-scaffolding#68`.)

## Streamlit conventions
*Apply only if this project uses Streamlit.*

- `st.set_page_config(layout="wide", page_title="...")` MUST be the first Streamlit call.
- Use `width="stretch"` (and `width="content"` where appropriate) in new and modified code. **Never** introduce new `use_container_width=True` — it is deprecated. When you touch existing code that uses `use_container_width`, migrate it.
- All mutable state in `st.session_state`. No module-level globals.
- `@st.cache_data` for DataFrames/files; `@st.cache_resource` for DB clients/models.
- Every widget needs a stable, explicit `key=`.
- UI code only in the UI directory (e.g. `app/`). Data logic stays in the non-UI package (e.g. `src/`). Never import `streamlit` from non-UI code.
- User feedback via `st.error()` / `st.warning()` / `st.success()`, not `st.write()`.
- **App layout:** the main file (e.g. `app.py`) handles only page config, shared state, the sidebar, and routing. Default to native multipage navigation — `st.navigation` + `st.Page`, one view per file exposing a `render()` function (the pattern this scaffold ships). Use `st.tabs()` for sub-sections *within* a view, and a sidebar radio only when asked.
- **Ask before assuming (Streamlit specifics):** `st.session_state` key names & scope; caching strategy (`@st.cache_data` TTL vs. `@st.cache_resource`); widget `key=` names & input sources; page placement (new page vs. a section in an existing page). (The universal "ask before assuming" directive is in global.)

## GitHub Actions CI conventions
*Apply whenever this project adds a `.github/workflows/` file.*

- **Pin a dated Windows runner.** Use `runs-on: windows-2025`, never `windows-latest`. GitHub is redirecting `windows-latest` to `windows-2025` (deadline June 2026); for a Windows-only tray/daemon app that spawns real processes (PTYs, uvicorn, Chromium), the OS image silently changing under you is exactly the environment shift that turns a green gate red without a code change. Pin the label so the runner is an explicit, reviewable choice.
- **Use Node-24 action majors.** `actions/checkout@v4`, `actions/setup-python@v5`, and `actions/upload-artifact@v4` all run on Node 20, which is deprecated (forced Node 24 starting June 16 2026; Node 20 removed September 16 2026). Use the current majors that run on Node 24: `checkout@v6`, `setup-python@v6`, `upload-artifact@v7`. Inputs are unchanged for standard usage, so the bump is drop-in.
- **Trigger once per commit: `push:[main]` + `pull_request:[main]`.** Gate `main` with two events that each own exactly one job — `push` to `main` (the post-merge integration gate) and `pull_request` to `main` (validates every feature branch). Do **not** trigger `push` on feature branches (`push:` with no `branches:` filter, or `push: branches-ignore: [main]`): while a PR is open, every branch push fires *both* `push` and `pull_request`, running the same gate **twice on the same commit** — double runtime, double flake exposure, zero added coverage. The `branches-ignore: [main]` shape also silently *omits* the post-merge `main` gate, so the merge commit (which can differ from what the PR validated, if `main` moved underneath it) is never CI-gated. `concurrency` cannot fix this: `github.ref` differs between the two events (`refs/heads/<branch>` for push vs `refs/pull/<N>/merge` for pull_request), so they land in separate concurrency groups and both survive — `concurrency` only collapses successive pushes to the *same* ref. The only thing given up — CI on a branch you pushed but never opened a PR for — is a non-loss: the standard `/issue-finish` flow always pushes and immediately opens the PR.

Canonical pattern:

```yaml
on:
  push:
    branches: [main]          # post-merge integration gate on main only
  pull_request:
    branches: [main]          # validates every feature branch via the PR event

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

Run-count, wrong shape vs this convention:

| Moment | `push: branches-ignore: [main]` + `pull_request` | This convention |
|---|---|---|
| Push to a feature branch with an open PR | **2 runs** (push + pull_request) | **1 run** (pull_request `synchronize`) |
| Push to a feature branch, no PR yet | 1 run | 0 (open the PR before you need CI) |
| Merge commit on `main` | **0 runs** (main is ignored) | 1 run (post-merge gate) |

**Sister-repo tracking:** when a fleet repo still has the old runner/actions (`#25`) or the duplicate `push`-on-branches trigger (`#38`), it carries a pointer issue back to the canonical decision record in `ferraroroberto/project-scaffolding`. Fix it before the deprecation deadline rather than after.

## CI is advisory — `## CI expectations` block + e2e-surface skip rule
*Apply whenever this project has a `.github/workflows/` file **and** a local verification gate.*

**CI is advisory, not a required gate.** The fleet's e2e workflows run on repos with **no branch protection**, so their checks are not required to merge. The **local gate** (`scripts/verify-before-ship.ps1`, or `pytest + ruff + mypy`) is the contract; CI is supplementary. The agent must not treat `gh pr checks --watch` as a mandatory blocking wall.

**CI's only signal beyond the local gate is the e2e suite.** The local gate runs `pytest + ruff + mypy` but **skips the Playwright e2e leg** (it needs browsers + a live webapp). So the *only* thing CI runs that the local gate didn't is the e2e suite — which is also the known-flaky part (browser/PTY input wedging on the slower hosted Windows runner). **Consequence:** a diff that touches **none** of the project's e2e surface gains nothing from waiting on CI, yet a wedged WebKit browser can still block the merge up to the `timeout-minutes` cap. Waiting there is pure cost, no signal.

**Each project declares a `## CI expectations` block in its own `CLAUDE.md`** (the per-project *instance* — durations, flaky leg, e2e-surface paths). `/issue-finish` reads it. Don't inline these values into the skill; they differ per repo. Block template (fill the bracketed values):

```markdown
## CI expectations
- Workflow `[.github/workflows/e2e.yml]`, job `[verify-before-ship]`, on every PR. **Advisory, not required** (no branch protection) — the local gate is the contract.
- Typical green: **~[N] min**. Investigate at **>[2N] min**; treat as wedged at **>[~4N] min**.
- Flaky leg: `[the Playwright WebKit/iPhone projection / PTY-input tests]` can wedge on the hosted runner. `timeout-minutes: [30]` caps a wedge. A wedge is a flake, not the diff.
- CI's only signal beyond the local gate is the **e2e suite** (skipped locally). Its e2e surface = `[app/webapp/, app/tray/, tests/e2e/, static assets, …]`. A diff touching **none** of these gains nothing from CI.
```

**What `/issue-finish` does with it (the shared skill mechanism, two behaviors):**
- **Skip-the-wait keyed on the e2e surface, not "docs vs code."** If the diff touches none of the project's declared e2e surface and the local gate is green → merge on local-green and **state it** in the finish summary (e.g. `CI not awaited — store-only diff, no e2e surface touched`). This generalizes the old narrow `*.md`-only skip rule into the principled one: e2e is the only thing CI adds over the local gate.
- **Proactive flake handling.** Read the expected duration from the block. While watching, the moment elapsed crosses the *investigate* threshold, stop waiting passively — inspect the run (`gh run view --job`), classify flake vs real failure, and for the *documented* flaky leg cancel + rerun **once** automatically, saying so. A second flake → stop and surface it to the user. **Never** rerun a real (non-flake) failure.

**Keep-the-human-in-control guardrails:**
- The agent always **states** its CI decision (skip vs wait, plus any rerun) in the finish summary, so the user can veto.
- Auto-rerun is capped at **once** and only for the *documented* flaky leg; a second flake stops and asks.
- Nothing force-merges. Because CI is advisory (no branch protection) no `--admin` override is ever needed. **If a repo later adds the `e2e` check as a *required* status check, the skip-rule must fall back to watching** — a required check cannot be skipped without `--admin`, and force-merging is out of scope here.

**Where each piece lives** (per the fleet "don't diverge" rule): this scaffold documents the convention + the block template; the **skill mechanism** lives in `fleet-config` `skills/issue-finish/SKILL.md` step 5 (synced to `~/.claude`); the **per-project instances** live in each project's own `CLAUDE.md` block; **sister-repo pointer issues** (start: `whatsapp-radar`, `app-launcher`) track adoption back to the canonical decision record. Making the e2e leg actually stop flaking (env-aware wait budgets / retry) is a separate per-project fix — this convention makes a flake *cheap*, it does not cure it.

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

## Restart and verify before hand-off
*Apply only if this project runs a long-lived process (dev server, webapp, daemon, tray) without hot-reload.*

After the verification step — and unless I said otherwise — restart that process so the change is actually live, and confirm it: check a version/build endpoint or equivalent signal that the running process reflects the new code (not just that it answers a health check — a stale process passes health checks fine). Report the build identifier. Don't hand off "done" with a stale process still serving.

**Restart safely.** Kill only the specific process for *this* app (identify it precisely — by listening port / PID / window title), never a blanket process-name kill (`pythonw`, `node`, `python`) that would also take down sibling apps or shared services on the same machine.

**A 'start' script is usually not a 'restart' script.** Re-running `launch_app.bat` / `tray.bat` / `npm start` while an instance is already up typically just spawns a duplicate (or silently no-ops if the port is bound). The pattern is **kill-then-start**, not "run start again". Document the project-specific recipe in this repo's own `CLAUDE.md` under `## This repository` — *which* process to kill (port / PID lookup), *which* command relaunches it, *what* signal confirms the new build (e.g. `GET /api/version` returning the current `git_sha`).

**A tray restart must reclaim the app's service ports by PID (orphan-proof), not just `taskkill /T` the tray subtree.** A tray's service children (a webapp, a session-host, a tunnel) can orphan — the tray dies or is replaced while a child keeps running, so the child leaves the tray's process subtree but still holds its service port. A restart that kills only the tray PID-subtree misses the orphan; the fresh tray can't bind the port, silently fails, and the old orphan keeps serving stale code while the restart *reports success*. So `--restart` must, for each fixed loopback port the app **definitively owns**, find the current listener and kill its owning PID, **then** start. Scope the sweep to **this app's `.venv`** so sibling apps are never touched — and scope it by the holder's **CommandLine**, *not* its process image path: on Python 3.14 Windows venvs a venv-launched `pythonw.exe` re-execs the base interpreter, so the image path reports the *shared base* interpreter while only the CommandLine still carries the `.venv` path; an image-path guard never matches the real webapp and the reclaim silently no-ops. Exclude any port that is **mutex-shared** with another app (reclaiming it would kill the sibling's live process). This is the third tray-lifecycle gotcha in the fleet, alongside **#12** (single-instance via a named mutex, not a bound TCP port) and **#13** (`CREATE_NO_WINDOW` when shelling out to console tools); it does not conflict with #12 — #12 is how you *detect* a running instance, this is how a *restart cleans up* the previous one. Canonical `tray.bat` shape (idempotent start + verified reclaim-then-start) and the full reasoning live in the scaffold's `docs/windows-tray.md`; a copy-to-adapt `tray.bat.template` ships at the scaffold root so a new tray app inherits the orphan-proof restart by default (replace four `__PLACEHOLDER__` tokens — app name, tray-launch args, tray-match regex, owned ports). **The full detect → kill → reclaim → start → verify lifecycle must live in the committed, vendored-verbatim `app/tray/tray_lifecycle.ps1` (shelled to with `-File` once), never in cmd `for /f` output capture or inline `powershell -Command "…"`** (`project-scaffolding#54`): both cmd-side forms have failed when `tray.bat` is launched **non-interactively** (Git Bash → `cmd /c "tray.bat --restart"`, or a finisher skill's Bash tool), returning empty detection/reclaim data so nothing is killed and `--restart` silently degrades to a plain start. That matters because **a plain start *adopts* whatever already serves the port** (`WebappManager.start()` → `OWNERSHIP_EXTERNAL`) and reports healthy — only `--restart`'s reclaim forces new code to load, so a mangled lifecycle makes `--restart` serve the *stale* build while looking successful. Verification is therefore by served `git_sha` vs repo `HEAD`, **never** a `healthz` 200 (a stale adopted process passes health checks), and a mismatch must exit non-zero. A tray app vendors **two** scaffold files — `tray_lifecycle.ps1` and `single_instance.py` — and `tray.bat` hard-errors if the helper is missing rather than no-op'ing.

**The canonical restart invocation is `tray.bat --restart` — call it, don't hand-roll the kill.** Once a project ships a `tray.bat` with `--restart`, that one command *is* the restart: it does the orphan-proof subtree-kill + per-`.venv` port reclaim + start atomically. Automated finishers (`/issue-finish`, `/issue-yolo`) and any agent restart must run `tray.bat --restart` rather than re-deriving a `Get-NetTCPConnection`/`taskkill` sequence by hand — a hand-rolled kill only catches the one listener it happens to find and misses the orphan the reclaim sweep exists to kill. The manual port-PID kill is a *fallback* for the rare app that has no `--restart`, never the default. Each tray app's own `CLAUDE.md` `## This repository` section names `tray.bat --restart` as its restart command plus the signal that confirms the new build is live.

**A tray's single-instance guard must hold *in the tray process* (a named mutex), and its adopt-or-spawn must be *race-safe*.** This is the **fourth** tray-lifecycle gotcha, alongside **#12** / **#13** / **#29** above. The launcher `.bat`'s pre-launch CIM detection is necessary but not sufficient — two near-simultaneous `tray.bat` runs both read the process table before either tray is visible, pass the check, and both survive; per #12 the guarantee belongs to a named mutex the tray holds for its lifetime (acquire at the top of `run_tray()`; if already held, exit). Independently, a `WebappManager.start()` that does `status()`-then-`Popen` is check-then-act: two trays that both see "port free" both spawn a duplicate uvicorn (a TOCTOU race). Serialize the check-then-spawn with a named mutex keyed on the owned port so the loser **adopts** the now-listening service instead of spawning. Both are solved by one byte-identical primitive — `app/tray/single_instance.py` (`SingleInstance` + `cross_process_lock`) — shipped in the scaffold and **vendored verbatim** (only the mutex *names* differ per app). Proven on `whatsapp-radar`: one clean `tray.bat` spawned two trays + two uvicorns contending for one port. Full reasoning in the scaffold's `docs/windows-tray.md` (gotcha #4).

**The agent restarts a tray by invoking `tray.bat --restart` fire-and-forget, then verifying with a *bounded* poll — never a foreground launch or an unbounded wait.** A tray launcher holds the console it starts in, so a normal foreground tool call never returns and burns the 10-minute timeout (this is where the historical restart hangs lived). Call `--restart` non-blocking (background/detached) so the tool returns at once, then poll `GET /api/version` with a **hard timeout and attempt cap** (e.g. ≤30 s) and **fail loud** on a slow/failed boot — a `/healthz` 200 is not enough, a stale process passes it; assert `git_sha == HEAD` and report the build line. The app's `--restart` owns the *what-to-kill/reclaim* intelligence (ports, children), so the agent delegates rather than re-derives. A correct restart is **adopt / reclaim / spawn** — re-attach to healthy owned children, reclaim stale port-holders, spawn only what's missing — and it classifies children as **owned-and-cycled** (webapp/worker/cloudflared: live *inside* the tray subtree, die + respawn with new code, port in the reclaim list) vs **linked-but-independent** (a session-host + its PTY shells / launched apps: must **survive**). "Must survive" is enforced structurally, not by a warning: linked children are **spawned re-parented out of the tray subtree** (via `cmd /c start` — `taskkill /T` walks the parent-child PID tree, so `DETACHED_PROCESS`/`CREATE_NEW_PROCESS_GROUP` do **not** escape it; only re-parenting does, verified empirically) so the `/T` subtree kill can't reach them, and the fresh tray **re-adopts** them on start by port/identity. That is what makes the one canonical `tray.bat --restart` safe everywhere — including from *inside* a session the tray's session-host is hosting. **Safety caveat:** until a tray with linked children is detach-compliant, `--restart` still kills those children — that tray's `CLAUDE.md` flags this and the agent confirms first. This agent-side recipe is mirrored in the `/issue-finish` finisher and the global restart skill (`project-scaffolding#35`).

---

## This repository
<!-- Replaced per repo. Keep to two sentences max. -->
<one sentence: what this project is>.
See `README.md` for setup, layout, and usage.
