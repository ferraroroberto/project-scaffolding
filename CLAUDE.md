# Project Instructions

Canonical AI-agent instructions; Claude Code reads as project memory, other agents (Cursor, Codex, …) via the one-line `AGENTS.md` pointer.

> **Scope — project-shaped guidance only.** Only project-shape-specific guidance (Streamlit, GitHub-Actions CI, e2e UI testing, tray/long-lived process) lives here, each section gated *"apply only if…"*. Universal dev-workflow directives (plan mode, asking, editing, git, PR pipeline, docs discipline, senior-dev check) live once in `fleet-config/global-CLAUDE.md` (→ `~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md`), not here. Test: *"would it apply to a bare repo with no app?"* Yes → global; no → here; never both — `/context-audit` enforces weekly (`project-scaffolding#68`).

Conventions:
- Issue refs and `docs/…` paths are `project-scaffolding`'s (`ferraroroberto/project-scaffolding`) unless another repo named — a derived project reads those docs there, not in its own tree.
- ***(PWA)*** in a heading = *apply only if this project serves a FastAPI + static PWA web app; Streamlit POC spikes are exempt*. Other gates spelled out under their own heading.
- **Don't diverge, don't re-author.** Every convention/vendored component/token contract here is owned here: fix in this scaffold, re-vendor downstream, never fork in a consuming app. Each section closes with reference docs + decision record; where a section keeps only one-line rules, its full procedure, reasoning and snippets live verbatim under the same heading in the named doc — read it before working in that area. Standing architecture decisions (one `adr` issue each) are registered in `docs/architecture-decisions.md`: read it before building.

## Agent config artifacts (instructions and scoped project skills)
*Apply when adopting this scaffold's agent configuration layout.*

- **`AGENTS.md` is a committed short pointer to `CLAUDE.md`, never a copy.** Keep the instruction chain; machine-scope policy owned by `fleet-config`.
- **One source per project skill.** Keep existing sources; discover native compatibility before adding a per-skill junction/symlink at the same repo/package scope. Never broaden a nested skill into a root or user-global catalog. Preserve real `.agents` directories; report name/target collisions without overwriting.
- **Agent directories are ignored by default, not disposable noise.** `.claude/`, `.agents/`, `.codex/`, `.pi/`, `.grok/` may hold private context or owned discovery artifacts. Only deliberately shared skill sources get narrow ignore exceptions; generated links, local settings, conversations stay ignored. Fresh clones/worktrees recreate own links to own sources.
- **Adoption/proof:** follow [portable project skills](https://github.com/ferraroroberto/project-scaffolding/blob/main/docs/agents/project-skills.md) contract — scope, helper exclusions, collisions, ignore allowlists, native discovery checks. Installer mechanics belong to `fleet-config`, not a per-project fork. (`#28`, `#250`.)

## Where code goes

- Read the repo's `docs/layout.md` first; the tree for its shape is in `docs/repo-layout.md`.
- Four rules ([repo layout](https://github.com/ferraroroberto/project-scaffolding/blob/main/docs/repo-layout.md)): never grow a 1,000-line file (add a sibling module), no new module in a 40-module directory (use a domain subpackage), `src/` never imports `app/`, tests mirror what they test.
- Streamlit views: `app/views/<name>.py` exposing `render()`, registered in `app.py`; never `tab_x.py`, `x_tab.py` or `main()`.
- A justified exception is declared in `extra_roots` in `.fleet.toml` and in `docs/layout.md`, never improvised.
- With `[structure_ratchet]` enabled the gate enforces the first three rules: `docs/structure-ratchet.md`.

## Streamlit conventions
*Apply only if this project uses Streamlit.*

- Before writing or reviewing Streamlit code, read `docs/streamlit-conventions.md` — `st.set_page_config` first (checked by `tests/test_streamlit_conventions.py`), `width=` not `use_container_width=True`, state in `st.session_state`, `@st.cache_data`/`@st.cache_resource`, explicit widget `key=`s, `st.navigation` multipage, `streamlit` imported only from the UI directory (ruff `TID251`), `st.error`/`st.warning`/`st.success` feedback, what to ask before assuming, and the DOM-hooking CSS gotchas.

## Web-app visual identity (fleet design system) *(PWA)*

Fleet web app inherits look **and** navigation; re-authors neither. `fleet-config` owns the *spec* (`design.md` + `design.dark.md`, junctioned into `~/.claude`, plus `/design-sync`); this scaffold owns the *vendored implementation* (`app/webapp/static/_vendored/`).

- **Tokens come from the spec, not you.** Wire CSS custom properties (`:root`/`[data-theme]`) to `~/.claude/design.md` (light) + `~/.claude/design.dark.md` (dark) — colors, typography, spacing, radii. **Don't** copy spec into repo; **don't** invent a second accent/per-app palette. `/design-sync` reports drift.
- **Width follows the shape of the view, per view.** One-dimensional content (settings, a form, one list, a detail) keeps the 772px measure; two-dimensional content (board lanes, a many-field table, a tree with attribute columns, calendar days) may span the window. Declare those views in `.fleet.toml` as `[design] wide_views = ["board"]` (tab ids; commented example there); an undeclared view keeps the measure. Rule: `fleet-config`'s `design.md` Layout; schema: its `architecture/README.md`. (`fleet-config#1113`.)
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

- Tailnet-reached → `tailscale cert` via `scripts/gen_tailscale_cert.py` (preferred), with `--check` auto-renew wired into the app's own webapp launcher before uvicorn binds (mandatory); LAN-only → self-signed CA fallback (`gen_ssl_cert.py`), the only path that ships the `/install-ca` affordance. Full text: [HTTPS provisioning](https://github.com/ferraroroberto/project-scaffolding/blob/main/docs/webapp-pwa-conventions.md); procedure: [app onboarding §2–§3](https://github.com/ferraroroberto/project-scaffolding/blob/main/docs/app-onboarding.md). (`#89`.)

## Webapp PWA required surfaces (build-identity footer + Settings/CA-install) *(PWA)*

- **Version endpoint and footer — `GET /api/version` → `{git_sha, built_at}`**, captured once at module load via a hardened `git rev-parse`, rendered by the vendored `page-foot` component (the one shared build line, last child of `.app`, outside every card), auth-gated with loopback bypass. Universal; restart verification depends on it.
- **Collapsible `⚙️ Settings` block** with a plain `<a href>` to the auth-exempt `/install-ca` route, shipped only on the self-signed/LAN-only HTTPS path. Full text: `docs/webapp-pwa-conventions.md` → "Webapp PWA required surfaces". (`#74`.)

## Webapp PWA static-asset cache-busting (`CachingStaticFiles` + fleet hash) *(PWA)*

- Required: copy `home-automation`'s `src/static_versioning.py` + `CachingStaticFiles` rather than re-deriving; one fleet hash over every file's hash, stamped as `?v=` idempotently; `.js`/`.css` `immutable`, manifest/icons `max-age=86400`, shell `no-cache, must-revalidate`; no service workers — otherwise iOS Safari runs stale cached JS/CSS after a deploy. Full text: `docs/webapp-pwa-conventions.md` → "Webapp PWA static-asset cache-busting"; snippet: `docs/app-onboarding.md` §4. (`#78`.)
- **Compression is one vendored middleware**, `src/compression.py` (manifest key `compression`): `app.add_middleware(StreamSafeGZipMiddleware, bypass_paths=(...))`, registered last. It never compresses `text/event-stream`, `multipart/x-mixed-replace`, websockets or already-compressed media; never a stock or hand-rolled `GZipMiddleware`. Measure with `/perf-review`. Full text: `docs/webapp-pwa-conventions.md` → "Webapp PWA response compression".

## Usage log — local-only views, taps, device class *(PWA)*

- Every fleet web app records real usage through one vendored pair, so `/design-review` reads data instead of asking the owner: the client `app/webapp/static/_vendored/usage-log/` (manifest key `usage-log`; `initUsageLog()`, its `trackView` passed as the nav's `onChange`) and the server `src/usage_log.py` (manifest key `usage_log`; `usage_router(runtime_db_path(<app>, "usage.sqlite3", create=True), dependencies=[<the app's auth>])`; a Starlette app with no FastAPI mounts `usage_route(db_path)` from `src/usage_log_starlette.py`, manifest key `usage_log_starlette`, which limits `GET` to the owner). Same origin only: no cloud analytics, no third-party host, no cross-device aggregation.
- **Every feature that touches the UX is tracked from its first PR.** Each interactive control carries a constant `data-track="<id>"`; each sheet, dialog or drawer is a `<dialog>` with a constant `data-track-view="<id>"`; ids are never built from content. The usage track ratchet fails the ship on an untracked control or sheet, a built id, or an app that does not reach its log (`usage-log-wired`); a deliberate exception carries `<rule>-exempt: <reason>`. Exempt by name: Streamlit spikes, public sites under `design.web.md`, passive text. Read [usage-track-ratchet](https://github.com/ferraroroberto/project-scaffolding/blob/main/docs/usage-track-ratchet.md).
- **Privacy is the contract:** the log holds no content, names, queries, form values, query-string URLs, IPs or raw user-agent; only event kind, view and control ids (constants from `data-track`), a random per-visit session id, device class and timestamps. Instrumentation never breaks the app. `scripts/usage_summary.py --app <slug> --days 30 --json` is the review's reader (exit 2 = no data yet, never zero usage). Full text: [Usage log](https://github.com/ferraroroberto/project-scaffolding/blob/main/docs/webapp-pwa-conventions.md). (`#349`.)

## Webapp launch: HTTP/2 through one vendored module, selector loop pinned *(PWA)*

- Every spawn point (tray `manager.py`, `.bat`, CLI command, e2e autoboot) runs the vendored `app/webapp/serve.py` (manifest key `webapp_serve`): `python -m app.webapp.serve --host H --port P [--ssl-certfile C --ssl-keyfile K] [--app module:attr] [--loop module:factory] [--server hypercorn|uvicorn]` — never `-m uvicorn` or `uvicorn.run()`. TLS + hypercorn negotiates `h2` by ALPN (phone cold load ~2.3 s to ~1.0 s); `--server uvicorn` is the HTTP/1.1 fallback, plain HTTP stays HTTP/1.1; `hypercorn>=0.18` joins `requirements.txt` and `pip install -r requirements.txt` runs before the tray restart. It pins the selector loop (the proactor loop wedges the listener on an aborted client, `app-launcher#388`); an app's own factory goes in `--loop`. Full text: `docs/webapp-pwa-conventions.md` → "Webapp PWA HTTP/2 launch"; playbook: `docs/app-onboarding.md` §1. (`#589`.)
## Windows console-subprocess suppression (`CREATE_NO_WINDOW`)
*Apply only if the project has a long-lived Windows tray, daemon or GUI process with no console of its own (e.g. under `pythonw`) that shells out to a console CLI such as `docker`, `nvidia-smi`, `git` or `taskkill`.*

- Every console-tool subprocess call (`subprocess.run`/`subprocess.Popen`, `asyncio.create_subprocess_exec`) passes `creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0` through one helper — this scaffold's `src/no_window.py`, imported as `from src.no_window import NO_WINDOW` — and never adds `DETACHED_PROCESS` on top. (`#13`, `#209`, `#221`.)
- Trap: a `pythonw` child with no redirected output crashes on its first log write; give it a real log target.
- Read `docs/long-lived-process-conventions.md` → "Windows console-subprocess suppression" before adding a spawn, a standalone entry point or a vendor-verbatim module: the vendor-verbatim exception, the `sys.path` rule, the `DETACHED_PROCESS` measurements and re-parenting live there. Worked helper: `docs/app-onboarding.md` §1.

## FastAPI + SQLite connection lifecycle (one `get_db` `Depends` dependency)
*Apply only if this project is a FastAPI app backed by SQLite.*

- **One dependency owns the connection.** `get_db()` connects, sets `row_factory = sqlite3.Row` + `PRAGMA journal_mode=WAL`, then `try: yield / finally: conn.close()`. Handlers take `db: sqlite3.Connection = Depends(get_db)` rather than opening their own — closes even on handler raise, and setup (pragmas, row factory, timeout) can't drift between handlers. Acceptance: zero per-handler `sqlite3.connect(...)` calls in routers.
- **SQLite + stdlib `sqlite3` stays the fleet default.** Convention covers only the *lifecycle dependency* — no ORM, no async driver, no connection pooling. (Apps legitimately needing a long-lived single connection are the documented exception.) Canonical `get_db` + `Depends` snippet: `docs/app-onboarding.md` §4. (`#96`; source instance `whatsapp-radar#100`.)

## Outbound-connection discipline
*Apply only if the project has a long-lived process (a tray, daemon, webapp or poll loop) that calls another local app, an external API or hardware over HTTP or TCP.*

- **Reuse connections** through the vendored `src/pooled_http.py` (manifest key `pooled_http`) — a bare `requests.get`/`requests.post` inside a poll loop, a health check or per-item fan-out is a defect (Windows ephemeral-port exhaustion, `fleet-config#440`).
- **Back off what is failing** and **cap the fan-out** (`asyncio.Semaphore(N)`) — prose only, no vendored helper.
- **Do not leak child processes:** an e2e suite closes every browser/context it opens, even on a failed run; the `tests/e2e/_browser_sweep.py` sweep classifies before it kills, reports what it can't establish as unknown, and never kills by image name.
- Full text, including the three sweep findings any rewrite must keep: `docs/long-lived-process-conventions.md` → "Outbound-connection discipline".
- **Soak the booted app for leaks:** the gate drives its poll routes (`tests/soak/_resource_soak.py`, key `resource_soak`) and fails on thread/handle growth, exit 3 NOT CONFIRMED when unmeasurable; `src/resource_probe.py` (key `resource_probe`) `start_breadcrumb(logger)` logs `threads=… handles=… rss=…`. Full text: `docs/long-lived-process-conventions.md` → "Resource soak".

## Runtime data lives on a fast drive
*Apply only if the project keeps SQLite (or other fsync-heavy state) in a long-lived process.*

- **Resolve the path through the vendored `src/runtime_data.py` (manifest key `runtime_data`):** `runtime_db_path(app, filename, env_var=...)` returns `<root>/<app>/<filename>`, root `FLEET_DATA_ROOT` → else `C:\sqlite` (Windows) / `$XDG_DATA_HOME/sqlite`. A repo-relative database path is a **defect**; change the path, never junction it; the app's existing full-path override stays highest precedence via `env_var=`. (`#243`.)
- **A harness that spawns the app points `<APP>_DATA_DIR` at a fresh per-run temp folder**, named with `app_dir_env_var(<app>)`, on every spawn. (`#404`.)
- Read `docs/long-lived-process-conventions.md` → "Runtime data lives on a fast drive" before adding or moving a store: the override's scope, the per-app layout, backup coverage and the reason live there.
## GitHub Actions CI conventions
*Apply whenever the project adds a `.github/workflows/` file.*

- Pin `runs-on: windows-2025` (never `windows-latest`); use Node-24 action majors `actions/checkout@v6`, `actions/setup-python@v6`, `actions/upload-artifact@v7`.
- Trigger once per commit: `push:[main]` + `pull_request:[main]` — never `push` on feature branches.
- Install `main-gate-watch` (copied from `.github/workflows/main-gate-watch.yml.template`) only where Actions runs the real gate on pushes to `main`; a local-only-gate repo (this scaffold included) has no automated red-`main` detection — report it **unknown**, never green.
- Canonical YAML, run-count table, sister-repo tracking and the watcher's issue contract: `docs/ci-conventions.md` → "GitHub Actions CI conventions".
- A web app gets its gate by copying `.github/workflows/ci.yml.template` (install, unit, Playwright desktop + phone, artifacts only on failure; no secrets); adoption steps and CI-safe test rules: `docs/ci-conventions.md` → "Web-app CI template". (`#351`.)

## CI is advisory — `## CI expectations` block + e2e-surface skip rule
*Apply whenever the project has a `.github/workflows/` file **and** a gate it runs locally.*

- **CI is advisory and never a required gate** — the local gate (`scripts/verify-before-ship.ps1`, or `pytest + ruff + mypy`) decides; never make `gh pr checks --watch` a mandatory blocking step.
- **Each project declares a `## CI expectations` block in its own `CLAUDE.md`** (durations, flaky leg, e2e-surface paths) that `/issue-finish` reads — don't inline these values into the skill.
- `/issue-finish` waits on CI only when a declared e2e surface is touched, retries the documented flaky leg **once**, never reruns a real failure, and states its CI decision. Block template and full rules: [CI is advisory](https://github.com/ferraroroberto/project-scaffolding/blob/main/docs/ci-conventions.md).

## Diff-proportionate e2e routing (`.fleet.toml` `[e2e]` + `classify_e2e.py`)
*Apply only if the project has a browser e2e suite (`tests/e2e/`) wired into `verify-before-ship.*`.*

- `scripts/classify_e2e.py` routes only the browser phase to `skip`/`static`/`full` from the repo's own `.fleet.toml` `[e2e]` table, worst-wins (optional `[[e2e.surface]]` narrows a single-surface `full` diff to that surface's targets, #258); uncertainty (unmatched path, empty diff, unusable table) always escalates to `full`, CSS/JS route to `full` (a shared stylesheet narrows only when one surface's `selectors` own the changed rules; a lone e2e test module runs itself, #289), and CI always runs the full suite.
- A new e2e-relevant directory gets its `full` rule in `.fleet.toml` **and** a representative assertion in `tests/test_classify_e2e.py` in the same PR. Full text: `docs/e2e-routing.md` → "Diff-proportionate e2e routing". (`#180`.)
## End-to-end UI testing
*Apply only if the project serves a browser UI (Streamlit, FastAPI, Flask, etc.).*

- Two separate loops — read [End-to-end UI testing](https://github.com/ferraroroberto/project-scaffolding/blob/main/docs/playwright-ui-testing.md) before driving or testing the UI. **Iterative verification:** headed Playwright MCP (else a `headless=False` script), app booted once on a fixed port, a11y snapshot over screenshot, ≤5 actions per cycle, never new files under `tests/e2e/`.
- **Regression suite** (`tests/e2e/`, created only once a test is justified): boot a disposable instance and **refuse** an occupied port unless the project's loudly-named opt-in env var is set (vendored `tests/e2e/_e2e_live_guard.py`, manifest key `e2e_live_guard`); always isolate stateful hosts; boot failure is a hard failure, never `pytest.skip`; under 15 tests, no Page Object Model, not gated in pre-commit; remove a feature's test with the feature.
- **Phone-first apps:** a WebKit device-emulation projection, only for tests where the engine or viewport matters (layout, touch targets, nav, composer, safe-area); functional tests run on one engine (`#290`); residual iOS-shell bugs via `ios-webkit-debug-proxy` and the device itself.
## Project verify skill (generated `verify-<app>` + feature map + maintain mode)
*Apply only if this project serves a browser UI and has a `tests/e2e/` suite (Streamlit POC spikes exempt).*

- **Generate it, don't hand-write it.** From this scaffold's checkout, `scripts/tools/gen_verify_skill.py --repo <app>` writes `.claude/skills/verify-<app>/`: `SKILL.md` (Launch, Doctor, Drive, Evidence, Cleanup, Maintain — for an agent that has never seen the app) plus `features/README.md` and one `features/<view>.md` per view. Seeded statically from committed inventories: `surface(page, "<view>.<surface>")` names first, then `[[design.review.extra_steps]]`, then the `## UX surface` key views; `[[e2e.surface]]` is context only. Idempotent; regeneration keeps `## Gotchas`.
- **Declare the launch recipe in `.fleet.toml` `[verify]`** (`boot`, `live_optin_env`; optional `ready_path`, `data_dir_env`). A missing key is a visible `FILL:` placeholder, never guessed, and `--check` is `blocked` until it is filled.
- **Maintain is `--check`.** Static half alone ends `STATIC=clean|changed|blocked`; with `--live-url` and `--junit` it ends `MAINTAIN=clean|changed|blocked` (exit 0 / 1 / 2). An unreachable app, a mapped node that did not pass, or a placeholder is `blocked`, never `clean`. `changed` is one PR touching only the skill's files, never a test edited, a journey deleted or a selector loosened to make a drive pass.
- The skill counts as delivered only once executed end to end against a **disposable** instance, evidence in the PR (node list, pass output, build line; no screenshots). The generator is a per-project instance, not a `[components]` entry, and prints the narrow `.gitignore` allowlist instead of editing it. Full text and limits: `docs/verify-skill.md`. (`#412`.)

## Gate ratchets (static, comment, docs, structure, instruction, doc refs, dead code, conventions, runtime write, usage track — baseline-and-ratchet)
*Apply each only if this project's `.fleet.toml` enables its table with `enabled = true` (`[static_ratchet]`, `[comment_ratchet]`, `[docs_ratchet]`, `[structure_ratchet]`, `[instruction_ratchet]`, `[doc_refs_ratchet]`, `[dead_code_ratchet]`, `[conventions_ratchet]`, `[runtime_write_ratchet]`, `[usage_track_ratchet]`; opt-in per repo, the scaffold itself is the first adopter).*

- Each is a vendor-verbatim script (manifest key = its table name) that fails the gate only when a measure rises above its committed `.<name>-ratchet-baseline.json`. Existing debt does not block; it cannot grow. They run as gate stages after `ruff` in the order static → comment → docs → structure → instruction → doc refs → dead code → conventions → runtime write → usage track, never path-routed. Adopting any of them in a repo inside or outside the fleet: `docs/adopting-ratchets.md`.
- **Exit 3 is "not confirmed"** (a prerequisite missing, git unusable, a file the scanner cannot finish; each doc's "Exit codes" lists its causes): its own failing state, never a pass. A vanished baselined hit passes with a hint; shrink with `--update-baseline`. **Raising the baseline needs `--allow-additions`** and shows in review: never re-baseline to get green without saying so.
- **Static** (`scripts/static_ratchet.py`): a **new** duplicate block (`jscpd`), unused import/variable (`ruff` `F401`/`F841`), curated bug/security pattern (`ruff` `B`/`S`) or unsorted import block (`ruff` `I001`); read `docs/static-ratchet.md` (`#410`). **Comment** (`scripts/comment_ratchet.py`): a file's `#NNN` issue references **inside comments**, a rule the global instructions own (`fleet-config#1517`), plus two opt-in rules under their own baseline keys: `docstrings = true` (`#NNN` inside Python docstrings) and `history_phrases = true` (a short curated list of history phrases); read `docs/comment-ratchet.md` (`#411`).
- **Docs** (`scripts/docs_ratchet.py`): the root `README.md` past its byte budget (40,960 unless `readme_max_bytes`; an over-budget README is baselined and may only shrink), or a file's history markers (`#NNN` references, dated headings, changelog headings; fences, URLs and link targets excluded, inline code counted) in `README.md` and `docs/**/*.md`. It enforces the README-as-index, present-tense-`docs/` convention: read `docs/readme-and-docs.md` before writing or splitting a README, and `docs/docs-ratchet.md` for the mechanism. (`#420`.)
- **Structure** (`scripts/structure_ratchet.py` + sibling `scripts/structure_layout.py`, stdlib only): a file past 1,000 lines, a Python or JS function past 100 lines (an unfindable JS function end is unmeasured, never passed), a directory past 40 modules, or a `src/` module importing `app/`; tests get the same limits. The root-layout check is never baselined: with `shape` (and `extra_roots`) declared, a missing required or undeclared tracked root folder fails; no `shape` skips it, stated. A declared `extra_roots` folder the shape's preset does not list is baselined and shrink-only, and `webapp-tray` also holds files under `app/` and `src/` to their homes. Failures name the `docs/repo-layout.md` section saying where the code goes instead: read it before adding to a large file or a full directory, and `docs/structure-ratchet.md` for the mechanism.
- **Instruction** (`scripts/instruction_ratchet.py`, stdlib only): the prompt audit's deterministic lint rules and size caps over instruction files and skills. Over a cap, move scoped detail into a skill, rule or referenced doc; deleting directives to pass is not a fix. Read `docs/instruction-ratchet.md`. **Doc refs** (`scripts/doc_refs_ratchet.py`, stdlib only): a `README.md`, `CLAUDE.md` or `docs/` reference to a repo path, `python -m` module or port that does not exist; or a name the repo lists in `retired` (a removed flag, skill or env var); an intentional pointer (a file an adopter will create, a port another service owns) goes in `allow_refs`. Read `docs/doc-refs-ratchet.md`. **Dead code** (`scripts/dead_code_ratchet.py`, stdlib only): a Python function, class or method nothing references; a route, `__all__` name, test or hook is an entry point, and one only a framework or template calls goes in `entry_decorators` or `allow`. Read `docs/dead-code-ratchet.md`. **Conventions** (`scripts/conventions_ratchet.py`, stdlib only): hits of the fleet-convention rules a repo lists in `rules` (no-window spawns, `print` in app code, drive paths, raw secret compares, raw `git`, a password input outside the vendored `sign-in` sheet, a page linking the vendored nav without its `viewport-fit=auto` + `black-translucent` head, a login route without the vendored `login_lockout`, the 0-byte `pwsh` stub run as a command in text files, a blocking `subprocess.run`/`call`/`check_*` with no `timeout=`, and any `[[conventions_ratchet.must_use]]` entry: a call to a named primitive outside the one helper the repo declares for it; and the implicit-state-machine suspects `state-literal`, `state-set-repeat`, `state-write`, never reported in a module the top-level `[[state_machines]]` table declares); a legitimate exception carries `# <rule>-exempt: <reason>`. Read `docs/conventions-ratchet.md`. **Runtime write** (`scripts/runtime_write_ratchet.py`, stdlib only): a write target resolving under a code folder (runtime output goes under `data/` or the runtime root); an unresolvable one is unknown, exit 3, never clean; `--snapshot`/`--probe` bracket the tests. Read `docs/runtime-write-ratchet.md`. **Usage track** (`scripts/usage_track_ratchet.py`, stdlib only): a web app's control with no constant `data-track`, a `<dialog>` with no `data-track-view` or a tracking id built at run time; with `usage-log-wired` listed, never baselined, an app that does not vendor, start and mount its usage log. Read `docs/usage-track-ratchet.md`.

## Verification (before declaring a task done)
Examples — adapt to the project's actual tooling. Windows / PowerShell: syntax `& .\.venv\Scripts\python.exe -m py_compile <file>`; lint (if configured) `ruff check .`; tests (if any exist) `& .\.venv\Scripts\python.exe -m pytest`; Streamlit boot check (UI changes) `& .\.venv\Scripts\python.exe -m streamlit run app/app.py --server.headless true`. POSIX: syntax `./.venv/bin/python -m py_compile <file>`; tests `./.venv/bin/python -m pytest`.

**Pre-ship gate (projects with an e2e suite).** Wire a single project-specific command — e.g. `scripts/verify-before-ship.ps1` — running the whole pipeline as one pass/fail: byte-compile → unit `pytest` → e2e suite (auto-booting the app per the harness rule in "End-to-end UI testing"). Mandatory before any UI-touching change is declared done. One command, can't half-skip. Do **not** substitute a bare `pytest` run that silently skips e2e when no server is up — that is how a regression ships looking green.
## Restart and verify before hand-off
*Apply only if the project has a long-lived process (dev server, webapp, daemon or tray) with no hot-reload.*

- After verification (unless told otherwise), restart and confirm the running process serves the new code via a version/build endpoint — a health check passes on a stale process; report the build identifier.
- Kill only this app's own process, found by port, PID or window title; never kill by process name. A start script is not a restart script: kill-then-start, with the recipe documented under `## This repository`.
- **Tray apps: `tray.bat --restart` is the one canonical restart — call it, don't hand-roll the kill.** It runs the shared `fleet-config`-owned `%USERPROFILE%/.claude/tray/tray_lifecycle.ps1`: orphan-proof subtree kill, per-`.venv` port reclaim by CommandLine (mutex-shared ports excluded), start, served-`git_sha`-vs-`HEAD` verify. Agents run it fire-and-forget, then poll `GET /api/version` with a hard timeout, failing loud. Single-instance is a named mutex held in the tray process and adopt-or-spawn is serialized by a port-keyed mutex, both from the vendored `app/tray/single_instance.py`. Linked-but-independent children are re-parented out of the tray subtree (`cmd /c start`) and re-adopted; until a tray is detach-compliant, the agent confirms before `--restart`.
- **Propagation freeze:** a vendored-component fix propagates only once this scaffold's gate is green; a second same-day bug in the same component freezes propagation entirely.
- Full text (reasons, `tray.bat.template` placeholders, adopt/reclaim/spawn model): `docs/long-lived-process-conventions.md` → "Restart and verify before hand-off"; lifecycle: `docs/windows-tray.md`.
## Tray webapp self-heal
*Apply only if the project has a Windows tray app supervising a long-lived service such as a uvicorn webapp, worker or tunnel.*

- Wire the vendored `app/tray/watchdog.py` (manifest key `tray_watchdog`): retry the initial spawn with backoff (loud on exhaustion), auto-respawn a **dead** webapp (`rearm()` if the respawn fails) but only alert on a **wedged** one (real `/healthz` probe), and write every attempt to the `webapp/watchdog.log` breadcrumb — `pythonw` has no stderr. Full text: `docs/long-lived-process-conventions.md` → "Tray webapp self-heal"; wiring: `docs/windows-tray.md` gotcha 5. (`#201`.)

## Restart/deploy coverage — merged is not shipped
*Apply only if the project has several long-lived runtime components, or a runtime outside the checkout, so its restart or deploy recipe may miss a live part.*

- **Invariant:** a change is never reportable as shipped while merely merged — observe the actual target running the new code, or say plainly it did not; unresolvable liveness is **unknown**, never fine.
- **Declare every not-fully-covered runtime component** (out-of-tree, or excluded from the standard restart) in this repo's own `CLAUDE.md` "This repository" section, and report a per-component `{reachable, git_sha, built_at, stale}` sub-block in `/api/version` (`stale` is `None`, not `false`, when unresolvable).
- Capture identity once at process start with a bounded retry *inside* the capture (vendored `src/build_info.py`, manifest key `build_info`), never re-resolved later; give every detached child a real log file; warn (advisory) at verify time when the diff touches a declared component.
- Declaration template, finish-flow obligation and reference implementation: `docs/long-lived-process-conventions.md` → "Restart/deploy coverage". (`#199`, `#246`.)
## Multi-repo agent fanout
*Apply only if the project ships fan-out tooling across several repos (a scatter-gather skill, a batch runner or a board that spawns per-repo agent sessions).*

- Dispatched agents work in a worktree, not the primary checkout: every per-repo agent builds in an isolated sibling worktree (`<repo>-wt-<N>`), enforced in the claim helper (explicit flag or dispatch marker in the environment), never by prose or a per-repo allow-list; interactive human sessions keep claim-or-worktree.
- Teardown is every lane's terminal step and must not assume the happy path (strip the `.venv` junction first); residue halts the run; a live-e2e guard refusal is a hard stop, never bypassed; pin the mandate with an acceptance test. Full text: `docs/multi-repo-fanout.md`. (`#202`.)

---

## This repository
Starter scaffold for a Streamlit app + Python pipelines project — clone, rename, and build. See `README.md` for setup, layout, and usage.

### CI expectations
- No per-change workflow runs here: `.github/workflows/` holds the `*.yml.template` files adopters copy plus `nightly-mac.yml`, which fires only on `schedule`/`workflow_dispatch` on the self-hosted Mac runner (`docs/mac-runner.md`), never on a PR or push. So `/issue-finish` has no CI run to wait on. **Advisory, not required** — the local gate (`scripts/verify-before-ship.ps1`) is the contract.

### Internal architecture
[`docs/architecture.mmd`](docs/architecture.mmd) is a hand-authored Mermaid diagram of this repo's internal structure (`app/`, `src/`, `scripts/`, `tests/`, `docs/`, external deps). Update it in the same PR as any material structural change (new view, new vendored component, script relocated) — same anti-staleness contract as `.fleet.toml`'s `description` field. Not auto-generated; not covered by `scripts/verify-before-ship.ps1`.

### The `[components]` catalog is this repo's alone
Each component this scaffold publishes for vendoring has one row in the `[components]` table of `.fleet.toml` (#230). **Never copy it into a derived project**: an adopter lists its own copies under `[vendored]`. The PR that puts a new component in the tree also adds its row. Why it is load-bearing, what reads it and the anti-drift guard: `docs/components.md`.

Standing up a new self-hosted **PWA** app (FastAPI + static PWA + Windows tray)? `docs/app-onboarding.md` is the canonical end-to-end playbook — bootstrap the app, issue + trust the self-signed-CA HTTPS cert (`certutil -user -addstore Root ca.pem` + full-Chrome-restart gotcha + leaf-cert expiry note), install the PWA on iPhone (`/install-ca` mobileconfig detour) / Android. Cross-links `docs/windows-tray.md` for tray lifecycle rather than duplicating it.
