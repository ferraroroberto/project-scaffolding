# Project Instructions

Canonical AI-agent instructions; Claude Code reads as project memory, other agents (Cursor, Codex, …) via the one-line `AGENTS.md` pointer.

> **Scope — project-shaped guidance only.** Only project-shape-specific guidance (Streamlit, GitHub-Actions CI, e2e UI testing, tray/long-lived process) lives here, each section gated *"apply only if…"*. Universal dev-workflow directives (plan mode, asking, editing, git, PR pipeline, docs discipline, senior-dev check) live once in `fleet-config/global-CLAUDE.md` (→ `~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md`), not here. Test: *"would it apply to a bare repo with no app?"* Yes → global; no → here; never both — `/context-audit` enforces weekly (`project-scaffolding#68`).

Conventions:
- Issue refs and `docs/…` paths are `project-scaffolding`'s (`ferraroroberto/project-scaffolding`) unless another repo named — a derived project reads those docs there, not in its own tree.
- ***(PWA)*** in a heading = *apply only if this project serves a FastAPI + static PWA web app; Streamlit POC spikes are exempt*. Other gates spelled out under their own heading.
- **Don't diverge, don't re-author.** Every convention/vendored component/token contract here is owned here: fix in this scaffold, re-vendor downstream, never fork in a consuming app. Each section closes with reference docs + decision record; where a section keeps only one-line rules, its full procedure, reasoning and snippets live verbatim under the same heading in the named doc — read it before working in that area.

## Agent config artifacts (instructions and scoped project skills)
*Apply when adopting this scaffold's agent configuration layout.*

- **`AGENTS.md` is a committed short pointer to `CLAUDE.md`, never a copy.** Keep the instruction chain; machine-scope policy owned by `fleet-config`.
- **One source per project skill.** Keep existing sources; discover native compatibility before adding a per-skill junction/symlink at the same repo/package scope. Never broaden a nested skill into a root or user-global catalog. Preserve real `.agents` directories; report name/target collisions without overwriting.
- **Agent directories are ignored by default, not disposable noise.** `.claude/`, `.agents/`, `.codex/`, `.pi/`, `.grok/` may hold private context or owned discovery artifacts. Only deliberately shared skill sources get narrow ignore exceptions; generated links, local settings, conversations stay ignored. Fresh clones/worktrees recreate own links to own sources.
- **Adoption/proof:** follow [portable project skills](https://github.com/ferraroroberto/project-scaffolding/blob/main/docs/agents/project-skills.md) contract — scope, helper exclusions, collisions, ignore allowlists, native discovery checks. Installer mechanics belong to `fleet-config`, not a per-project fork. (`#28`, `#250`.)

## Streamlit conventions
*Apply only if this project uses Streamlit.*

- Before writing or reviewing Streamlit code, read `docs/streamlit-conventions.md` — `st.set_page_config` first (checked by `tests/test_streamlit_conventions.py`), `width=` not `use_container_width=True`, state in `st.session_state`, `@st.cache_data`/`@st.cache_resource`, explicit widget `key=`s, `st.navigation` multipage, `streamlit` imported only from the UI directory (ruff `TID251`), `st.error`/`st.warning`/`st.success` feedback, what to ask before assuming, and the DOM-hooking CSS gotchas.

## Web-app visual identity (fleet design system) *(PWA)*

Fleet web app inherits look **and** navigation; re-authors neither. `fleet-config` owns the *spec* (`design.md` + `design.dark.md`, junctioned into `~/.claude`, plus `/design-sync`); this scaffold owns the *vendored implementation* (`app/webapp/static/_vendored/`).

- **Tokens come from the spec, not you.** Wire CSS custom properties (`:root`/`[data-theme]`) to `~/.claude/design.md` (light) + `~/.claude/design.dark.md` (dark) — colors, typography, spacing, radii. **Don't** copy spec into repo; **don't** invent a second accent/per-app palette. `/design-sync` reports drift.
- **Nav is vendored, not re-implemented.** Floating bottom-tab pill (desktop segmented control → mobile pill — fleet *navigation contract*) comes from `app/webapp/static/_vendored/nav/` (`nav-tabs.js`+`nav-tabs.css`+`nav-tabs.html`). Copy folder **verbatim**; adapt only markup (which tabs) and `storageKey`. Nav markup must be a direct `<body>` child, sibling of `<main class="app">`, **never** nested inside content wrapper/scroller — iOS anchors fixed-position descendants of scrollers to short-tab content instead of viewport (`home-automation#232`). Same "copy byte-for-byte, never fork per-app" rule as tray's `single_instance.py`.
- **`_vendored/` is the UI component channel.** New shared HTML/CSS/JS components live under `app/webapp/static/_vendored/<component>/`, normalized from best fleet implementation. Don't hand-copy a sibling app's snippet — vendor from here. Convention + how to add one: `app/webapp/static/_vendored/README.md`. (`#79`; aligns to `fleet-config#178`.)
## UX surface — diff-keyed design-conformance gate *(PWA)*

Diff-keyed gate at finish: checks the touched web UI still conforms to the design spec and isn't visually broken. Distinct from the periodic fleet-wide audit (`fleet-config#180`) — this is the don't-introduce-new-drift arm.

**Each project declares a `## UX surface` block in its own CLAUDE.md** (per-project instance the skills read, like `## CI expectations`) — don't inline paths into the skill. This scaffold ships the block below as a *live* declaration, not a fenced sample: enabling the gate is a one-word edit (`design spec applies` → `yes`, then adapt paths/views). `ux_surface.py` tolerates a descriptive `— …` suffix on this heading but matches only the first `## UX surface` heading — never add a second.

**The live block for this repo** — edit these lines in place; the skills read exactly them:

- design spec applies: no        # flip to `yes` once this repo serves a FastAPI + static PWA; `no` = gate no-ops
- paths:
  - app/webapp/static/**/*.css
  - app/webapp/templates/**
  - app/webapp/static/**/*.{js,html}
- key views:                     # used only by the `ux-full` whole-app sweep
  - /          (home + bottom nav)
  - /settings

- **Gate contract** — two separate checks (static token check + one `verify`-skill screenshot), deterministic `git diff` trigger against the declared `paths`, fix-now drift semantics, `ux`/`design`/`no-ux`/`ux-full` overrides, materiality bar, always state the gate decision; screenshots only through the `verify` skill's stealth-Chrome launch. Full text: `docs/webapp-pwa-conventions.md` → "UX surface". (`#83`.)

## HTTPS provisioning *(PWA)*

- Tailnet-reached → `tailscale cert` via `scripts/gen_tailscale_cert.py` (preferred), with `--check` auto-renew wired into the app's own webapp launcher before uvicorn binds (mandatory); LAN-only → self-signed CA fallback (`gen_ssl_cert.py`), the only path that ships the `/install-ca` affordance. Full text: `docs/webapp-pwa-conventions.md` → "HTTPS provisioning"; procedure: `docs/app-onboarding.md` §2–§3. (`#89`.)

## Webapp PWA required surfaces (build-identity footer + Settings/CA-install) *(PWA)*

- **Build-identity footer — `GET /api/version` → `{git_sha, built_at}`**, captured once at module load via a hardened `git rev-parse`, rendered as a plain `Build: <sha> · <ts>` line outside every card, auth-gated with loopback bypass. Universal; restart verification depends on it.
- **Collapsible `⚙️ Settings` block** with a plain `<a href>` to the auth-exempt `/install-ca` route, shipped only on the self-signed/LAN-only HTTPS path. Full text: `docs/webapp-pwa-conventions.md` → "Webapp PWA required surfaces". (`#74`.)

## Webapp PWA static-asset cache-busting (`CachingStaticFiles` + fleet hash) *(PWA)*

- Required: copy `home-automation`'s `src/static_versioning.py` + `CachingStaticFiles` rather than re-deriving; one fleet hash over every file's hash, stamped as `?v=` idempotently; `.js`/`.css` `immutable`, manifest/icons `max-age=86400`, shell `no-cache, must-revalidate`; no service workers — otherwise iOS Safari runs stale cached JS/CSS after a deploy. Full text: `docs/webapp-pwa-conventions.md` → "Webapp PWA static-asset cache-busting"; snippet: `docs/app-onboarding.md` §4. (`#78`.)

## Windows event-loop pinning (uvicorn) *(PWA)*

- Every uvicorn spawn point (tray subprocess spawn via `manager.py`, a programmatic `uvicorn.run()`, `.bat` launcher scripts, e2e autoboot spawns) must pass a pinned selector-loop factory (`--loop`/`loop=`) — asyncio's default Windows proactor loop wedges the listening socket on any aborted client connection (`app-launcher#388`). Worked shim: `docs/app-onboarding.md` §1; reference implementation: `app-launcher`'s `app/webapp/event_loop.py` (`selector_loop_factory`).
## Windows console-subprocess suppression (`CREATE_NO_WINDOW`)
*Apply only if this project runs a long-lived Windows process (tray, daemon, GUI) without its own console — e.g. launched via `pythonw` — that shells out to a console-based CLI tool (`docker`, `nvidia-smi`, `git`, `taskkill`, …).*

- Every console-tool subprocess call (`subprocess.run`/`subprocess.Popen`, `asyncio.create_subprocess_exec`) must pass `creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0` — else Windows flashes a fresh console per child (`#13`). Centralize behind one helper, not inline literals; `asyncio.create_subprocess_exec` takes the same flag and is easy to miss. Helper lives in the project's non-UI package; this scaffold ships `src/no_window.py`, imported as `from src.no_window import NO_WINDOW` (`#209`).
- **Vendor-verbatim modules are the one exception, not drift.** Files copied byte-identical into adopters (this scaffold's `$VendoredModules` list in `scripts/verify-before-ship.ps1` — e.g. `tests/e2e/_browser_sweep.py`, `scripts/classify_e2e.py`) can't import the shared helper (wouldn't resolve in consumer tree; hash-verified bytes must stay self-contained) — they derive the flag locally on purpose with a comment saying so. Don't "fix" into an import; don't count in audits.
- A standalone entry point (`scripts/` CLI, subprocess-launched test helper) has its own dir as `sys.path[0]`, not repo root — needs `sys.path.insert(0, <repo root>)` before the import. Keep the shared helper stdlib-only, side-effect-free, safe under a stripped venv.
- **Never add `DETACHED_PROCESS` on top — it neither suppresses the window nor escapes a subtree kill.** Measured from a console-less `pythonw` parent (`#221`): bare `CREATE_NO_WINDOW` suppressed every run; `DETACHED_PROCESS` alone, `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, and `CREATE_NO_WINDOW | DETACHED_PROCESS` **each** showed a visible window. Mutually exclusive per `global-CLAUDE.md`/`local-llm-hub#282` — defer to it. Keeping a long-lived child alive across tray teardown is a **re-parenting** problem, not a creation-flag one: `taskkill /T` walks the PID tree regardless — use `cmd /c start` re-parenting.
- Trap: a `pythonw` child launched without redirected `stdout`/`stderr` crashes on its first log write — always give it a real target.
- Worked helper: `docs/app-onboarding.md` §1.

## FastAPI + SQLite connection lifecycle (one `get_db` `Depends` dependency)
*Apply only if this project is a FastAPI app backed by SQLite.*

- **One dependency owns the connection.** `get_db()` connects, sets `row_factory = sqlite3.Row` + `PRAGMA journal_mode=WAL`, then `try: yield / finally: conn.close()`. Handlers take `db: sqlite3.Connection = Depends(get_db)` rather than opening their own — closes even on handler raise, and setup (pragmas, row factory, timeout) can't drift between handlers. Acceptance: zero per-handler `sqlite3.connect(...)` calls in routers.
- **SQLite + stdlib `sqlite3` stays the fleet default.** Convention covers only the *lifecycle dependency* — no ORM, no async driver, no connection pooling. (Apps legitimately needing a long-lived single connection are the documented exception.)
- **Ref:** canonical `get_db` + `Depends` snippet: `docs/app-onboarding.md` §4. (`#96`; source instance `whatsapp-radar#100`.)

## Outbound-connection discipline (pooled sessions, backoff, bounded fan-out, no leaked children)
*Apply only if this project runs a long-lived process (tray, daemon, webapp, poll loop) that makes outbound HTTP/TCP calls — to another local app, an external API, or hardware.*

- **Reuse connections** through the vendored `src/pooled_http.py` (manifest key `pooled_http`) — a bare `requests.get`/`requests.post` in a poll loop, health check or per-item fan-out is a defect (Windows ephemeral-port exhaustion, `fleet-config#440`).
- **Back off what is failing** and **cap the fan-out** (`asyncio.Semaphore(N)`) — prose only, no vendored helper.
- **Do not leak child processes:** an e2e suite closes every browser/context it opens, even on a failed run; the `tests/e2e/_browser_sweep.py` sweep classifies before it kills, reports what it can't establish as unknown, and never kills by image name.
- Full text, including the three sweep findings any rewrite must keep: `docs/long-lived-process-conventions.md` → "Outbound-connection discipline".

## Runtime data lives on a fast drive, not wherever the repo was cloned
*Apply only if this project persists SQLite (or similar fsync-heavy state) from a long-lived process.*

- **Resolve the path — `/propagate-vendored` component: `src/runtime_data.py` (manifest key `runtime_data`).** `runtime_db_path(app, filename, env_var=...)` returns `<root>/<app>/<filename>`; root = `FLEET_DATA_ROOT` → else `C:\sqlite` (Windows) / `$XDG_DATA_HOME/sqlite`. One subdirectory **per app**, so two apps can both own a `telemetry.sqlite3`. A repo-relative `Path(__file__).parent.parent / "webapp" / "x.sqlite3"` is a **defect** — it ties the physical drive to where someone cloned.
- **Change the path; never junction it.** A junction migrates data with no code change and records nothing — undrivable by tests, invisible to a reader, walked by any recursive delete.
- **Keep the app's existing full-path override** (`TELEMETRY_DB_PATH`, `WR_DB_PATH`, …) as highest precedence — pass as `env_var=`. Every unit/e2e harness sets it; outrank it and a test run writes into the live store.
- **Outside the git tree is outside git-derived backup.** `fleet-config`'s `backup_private.py` backs up the `C:\sqlite` root as an explicit source; an app inventing its own root elsewhere is unbacked.
- **Why:** seven always-on services `fsync`ing to the drive their checkouts sat on kept a spinning HDD audibly clicking around the clock (`#243`, diagnosed on `tower`; drive itself measured healthy).
## GitHub Actions CI conventions
*Apply whenever this project adds a `.github/workflows/` file.*

- Pin `runs-on: windows-2025` (never `windows-latest`); use Node-24 action majors `actions/checkout@v6`, `actions/setup-python@v6`, `actions/upload-artifact@v7`.
- Trigger once per commit: `push:[main]` + `pull_request:[main]` — never `push` on feature branches.
- Install `main-gate-watch` (copied from `.github/workflows/main-gate-watch.yml.template`) only where Actions runs the real gate on pushes to `main`; a local-only-gate repo (this scaffold included) has no automated red-`main` detection — report it **unknown**, never green.
- Canonical YAML, run-count table, sister-repo tracking and the watcher's issue contract: `docs/ci-conventions.md` → "GitHub Actions CI conventions".

## CI is advisory — `## CI expectations` block + e2e-surface skip rule
*Apply whenever this project has a `.github/workflows/` file **and** a local verification gate.*

- **CI is advisory, not a required gate** — the local gate (`scripts/verify-before-ship.ps1`, or `pytest + ruff + mypy`) is the contract; never treat `gh pr checks --watch` as a mandatory blocking wall.
- **Each project declares a `## CI expectations` block in its own `CLAUDE.md`** (durations, flaky leg, e2e-surface paths) that `/issue-finish` reads — don't inline these values into the skill.
- `/issue-finish` skips the CI wait when no declared e2e surface is touched and the local gate is green, reruns only the documented flaky leg **once**, never reruns a real failure, and always states its CI decision. Block template and full rules: `docs/ci-conventions.md` → "CI is advisory".

## Diff-proportionate e2e routing (`.fleet.toml` `[e2e]` + `classify_e2e.py`)
*Apply only if this project has a browser e2e suite (`tests/e2e/`) wired into `verify-before-ship.*`.*

- `scripts/classify_e2e.py` routes only the browser phase to `skip`/`static`/`full` from the repo's own `.fleet.toml` `[e2e]` table, worst-wins (optional `[[e2e.surface]]` narrows a single-surface `full` diff to that surface's targets, #258); uncertainty (unmatched path, empty diff, unusable table) always escalates to `full`, CSS/JS route to `full`, and CI always runs the full suite.
- A new e2e-relevant directory gets its `full` rule in `.fleet.toml` **and** a representative assertion in `tests/test_classify_e2e.py` in the same PR. Full text: `docs/e2e-routing.md` → "Diff-proportionate e2e routing". (`#180`.)
## End-to-end UI testing
*Apply only if this project serves a browser UI (Streamlit, FastAPI, Flask, etc.).*

- Two loops, kept separate — read `docs/playwright-ui-testing.md` → "End-to-end UI testing" before driving or testing the UI. **Iterative verification:** headed Playwright MCP (else a `headless=False` script), app booted once on a fixed port, a11y snapshot over screenshot, ≤5 actions per cycle, never new files under `tests/e2e/`.
- **Regression suite** (`tests/e2e/`, created only once a test is justified): boot a disposable instance and **refuse** an occupied port unless the project's loudly-named opt-in env var is set (vendored `tests/e2e/_e2e_live_guard.py`, manifest key `e2e_live_guard`); always isolate stateful hosts; boot failure is a hard failure, never `pytest.skip`; under 15 tests, no Page Object Model, not gated in pre-commit; remove a feature's test with the feature.
- **Phone-first apps:** always-on WebKit device-emulation projection; residual iOS-shell bugs via `ios-webkit-debug-proxy`.
## Verification (before declaring a task done)
Examples — adapt to the project's actual tooling.

Windows / PowerShell:
- Syntax: `& .\.venv\Scripts\python.exe -m py_compile <file>`
- Lint (if configured): `ruff check .`
- Tests (if any exist): `& .\.venv\Scripts\python.exe -m pytest`
- Streamlit boot check (UI changes): `& .\.venv\Scripts\python.exe -m streamlit run app/app.py --server.headless true`

POSIX:
- Syntax: `./.venv/bin/python -m py_compile <file>`
- Tests: `./.venv/bin/python -m pytest`

**Pre-ship gate (projects with an e2e suite).** Wire a single project-specific command — e.g. `scripts/verify-before-ship.ps1` — running the whole pipeline as one pass/fail: byte-compile → unit `pytest` → e2e suite (auto-booting the app per the harness rule in "End-to-end UI testing"). Mandatory before any UI-touching change is declared done. One command, can't half-skip. Do **not** substitute a bare `pytest` run that silently skips e2e when no server is up — that is how a regression ships looking green.
## Restart and verify before hand-off
*Apply only if this project runs a long-lived process (dev server, webapp, daemon, tray) without hot-reload.*

- After verification (unless told otherwise), restart and confirm the running process serves the new code via a version/build endpoint — a health check passes on a stale process; report the build identifier.
- Kill only *this* app's process, identified precisely (port / PID / window title) — never a blanket process-name kill. A start script is not a restart script: kill-then-start, with the recipe documented under `## This repository`.
- **Tray apps: `tray.bat --restart` is the one canonical restart — call it, don't hand-roll the kill.** It runs the shared `fleet-config`-owned `%USERPROFILE%/.claude/tray/tray_lifecycle.ps1`: orphan-proof subtree kill, per-`.venv` port reclaim by CommandLine (mutex-shared ports excluded), start, served-`git_sha`-vs-`HEAD` verify. Agents run it fire-and-forget, then poll `GET /api/version` with a hard timeout, failing loud.
- Single-instance is a named mutex held in the tray process and adopt-or-spawn is serialized by a port-keyed mutex, both from the vendored `app/tray/single_instance.py`. Linked-but-independent children are re-parented out of the tray subtree (`cmd /c start`) and re-adopted; until a tray is detach-compliant, the agent confirms before `--restart`.
- **Propagation freeze:** a vendored-component fix propagates only once this scaffold's gate is green; a second same-day bug in the same component freezes propagation entirely.
- Full text (reasons, `tray.bat.template` placeholders, adopt/reclaim/spawn model): `docs/long-lived-process-conventions.md` → "Restart and verify before hand-off"; lifecycle: `docs/windows-tray.md`.
## Tray webapp self-heal (retry-with-backoff spawn + dead/wedged watchdog + breadcrumb log)
*Apply only if this project runs a Windows tray that owns a long-lived service (a uvicorn webapp, a worker, a tunnel).*

- Wire the vendored `app/tray/watchdog.py` (manifest key `tray_watchdog`): retry the initial spawn with backoff (loud on exhaustion), auto-respawn a **dead** webapp (`rearm()` if the respawn fails) but only alert on a **wedged** one (real `/healthz` probe), and write every attempt to the `webapp/watchdog.log` breadcrumb — `pythonw` has no stderr. Full text: `docs/long-lived-process-conventions.md` → "Tray webapp self-heal"; wiring: `docs/windows-tray.md` gotcha #5. (`#201`.)

## Restart/deploy coverage — merged is not shipped
*Apply only if this project has more than one long-lived runtime component, or a runtime that lives outside the checkout, such that the project's restart or deploy recipe does not necessarily reach every live thing it owns.*

- **Invariant:** a change is never reportable as shipped while merely merged — observe the actual target running the new code, or say plainly it did not; unresolvable liveness is **unknown**, never fine.
- **Declare every not-fully-covered runtime component** (out-of-tree, or excluded from the standard restart) in this repo's own `CLAUDE.md` "This repository" section, and report a per-component `{reachable, git_sha, captured_at, stale}` sub-block in `/api/version` (`stale` is `None`, not `false`, when unresolvable).
- Capture identity once at process start with a bounded retry *inside* the capture (vendored `src/build_info.py`, manifest key `build_info`), never re-resolved later; give every detached child a real log file; warn (advisory) at verify time when the diff touches a declared component.
- Declaration template, finish-flow obligation and reference implementation: `docs/long-lived-process-conventions.md` → "Restart/deploy coverage". (`#199`, `#246`.)
## Multi-repo agent fanout — a dispatched agent works in a worktree, never the primary checkout
*Apply only if this project ships tooling that fans work out across several repos — a scatter-gather skill, a batch runner, a board/scheduler that spawns per-repo agent sessions.*

- Every dispatched per-repo agent builds in an isolated sibling worktree (`<repo>-wt-<N>`), enforced in the claim helper (explicit flag or dispatch marker in the environment), never by prose or a per-repo allow-list; interactive human sessions keep claim-or-worktree.
- Teardown is every lane's terminal step and must not assume the happy path (strip the `.venv` junction first); residue halts the run; a live-e2e guard refusal is a hard stop, never bypassed; pin the mandate with an acceptance test. Full text: `docs/multi-repo-fanout.md`. (`#202`.)

---

## This repository
<!-- Replaced per repo. Keep to two sentences max. -->
<one sentence: what this project is>.
See `README.md` for setup, layout, and usage.
