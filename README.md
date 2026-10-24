# Project Scaffolding

Starter template for a **Streamlit app + Python pipelines** project.
Clone this directory, rename it, and start building.

## What you get

- `app/` — Streamlit UI: entry point + view registry, views, theme.
- `src/` — Non-UI Python: logger, config, pipelines.  Reusable from
  the CLI and tests.
- An **elegant logger** (`src/logger.py`) that writes to:
  - the **terminal**, color-coded by level,
  - a **rotating file** at `data/logs/app.log`,
  - a **live panel inside the Streamlit UI** (rendered by
    `app/log_panel.py`), all from a single `log.info(...)` call.
- `app/.streamlit/config.toml` — dark theme + sane server defaults.
- A **light-mode toggle** in the sidebar, backed by
  [`app/styles/light.css`](app/styles/light.css) (CSS overlay, no restart).
  See [Theming](#theming) for why dark lives in config and light lives
  in CSS.
- `launch_app.{bat,sh}` — one-click local launch.
- `launch_server.{bat,sh}` — local launch + Cloudflare Tunnel for
  public sharing (no API keys leave your machine).
- `tray.bat.template` — copy-to-adapt canonical Windows tray launcher for apps that run a tray owning a long-lived service. Replace the four `__PLACEHOLDER__` tokens and you get the orphan-proof `tray.bat --restart` by default. See `docs/windows-tray.md`.
- `.github/workflows/ci.yml.template` — copy-to-adapt canonical web-app CI gate: one `gate` job on `windows-2025` that builds a fresh `.venv`, runs the unit suite, then Playwright e2e on desktop chromium and a phone projection (`webkit`, iPhone 13), uploading traces only on failure. Copy it to `.github/workflows/ci.yml` and change only the lines marked `# ADAPT:`. CI stays advisory — the local gate is the contract. Asserted by `tests/test_ci_template.py`. See `docs/ci-conventions.md` ("Web-app CI template").
- `.github/workflows/main-gate-watch.yml.template` — copy-to-adapt GitHub Actions watcher that files a `ci-red-main` tracking issue the moment your gate goes red on a push to `main` (and comments on it, rather than filing duplicates, while it stays red). Copy it to `.github/workflows/main-gate-watch.yml` and replace the one `__GATE_WORKFLOW_NAME__` token. **Only useful if your gate runs in Actions** — a repo gated locally (`verify-before-ship`, pytest on your machine) gets no coverage from it and should not install it. See `CLAUDE.md` ("GitHub Actions CI conventions").
- `scripts/gen_tailscale_cert.py` — copy-to-adapt HTTPS cert generator (provisions a real Let's Encrypt leaf via `tailscale cert` for a tailnet MagicDNS name; `--check` auto-renews within ~30 days of expiry). **Not** in the `[components]` catalog below and not vendor-verbatim — adapt on arrival, like `tray.bat.template`. See `docs/app-onboarding.md` §2.
- `%USERPROFILE%/.claude/tray/tray_lifecycle.ps1` — the ONE shared, machine-local tray lifecycle helper owned by `fleet-config` (not vendored in this repo), which `tray.bat.template` shells to with `-File` once (app-specific venv path / tray-match regex / owned ports / tray launch passed as arguments). Keeps detect → kill → reclaim → start → version verification out of cmd `for /f` parsing and inline `powershell -Command "…"`, both of which can break under a non-interactive `--restart` and silently adopt the stale build. `tray.bat --restart` hard-errors (never no-ops) if the shared path is missing, naming `fleet-config`'s `install.ps1` as the fix; a plain `tray.bat` instead starts the tray standalone from the repo's `.venv`, so an app can move to a PC that has none of the other fleet repos. See `docs/windows-tray.md`.
- `app/tray/single_instance.py` — canonical, **vendor-verbatim** named-mutex primitive for tray apps: `SingleInstance` (the tray's in-process single-instance lock) + `cross_process_lock` (serializes the webapp adopt-or-spawn so two trays can't both spawn it). Copy it byte-for-byte into a tray app — the per-app mutex *names* are passed at the call site, so the file stays identical fleet-wide. See `docs/windows-tray.md` (single-instance gotcha).
- `app/tray/watchdog.py` — canonical, **vendor-verbatim** tray self-heal primitives (manifest key `tray_watchdog`): `retry_with_backoff` (the initial webapp spawn survives a transient race instead of dying for the tray's lifetime), `HealthWatchdog` + `rearm()` (edge-triggered consecutive-failure monitor; the caller's `on_wedge` splits **dead** → auto-respawn from **wedged** → alert only), and `BreadcrumbLog` (the only durable record under `pythonw`, which has no `sys.stderr` for `logging` to write to). The probe, respawn action, log path and toast are all call-site arguments, so the file stays identical fleet-wide. Proven by `tests/test_watchdog.py`. See `docs/windows-tray.md` (webapp self-heal gotcha).
- `app/webapp/static/_vendored/` — **vendor-verbatim web-app UI components** for the FastAPI + static PWA shape: the fleet design system's *implementation* layer (the *spec* lives in `fleet-config`'s `design.md`/`design.dark.md`). Components: `base/` — element-level rules linked before every other stylesheet, so bare form controls inherit the app's font and text color; `nav/` — the canonical floating bottom-tab navigation; `icons/` — the inline Lucide icon sprite + `icon()` helper; and the canon extracted from the home-automation polish round (design.md v2 "Component contracts"): `card/`, `disclosure/`, `modal/`, `empty-state/`, `switch/`, `icon-tile/`, `button/`, `range-tab/`, `page-foot/`, `home-head/`, `select-native/`, `action-row/` (the tap-the-row list row), `text-size/` (the Small / Default / Large setting plus its pre-paint boot script), and `toast/` (the neutral frosted toast), `row-menu/` (the kebab's floating action list, data-driven items), `icon-button/` (the glyph-only control, unpainted at rest with an invisible 44px target), and `segmented/` (one choice among 2–5 peers where the raised selected segment is the state; `action-row/` also takes a leading avatar or check and one trailing switch, value, stepper or segmented verb), plus `usage-log/`, the client half of the local-only usage log (see `src/usage_log.py` below), `day-row/` (an `action-row` led by a date tile, with a chip only for an exception and a chevron only when it opens something), and `day-marks/` (one CSS-drawn shape per day, a ring only on an exception, plus the legend). `demo.html` is the component gallery (open over HTTP, light + dark), driven by the `tests/e2e/test_vendored_components.py` render harness. Copy a component folder byte-for-byte; adapt only your markup + token values. See `app/webapp/static/_vendored/README.md` and `CLAUDE.md` ("Web-app visual identity").
- `tests/e2e/_geometry.py` — canonical, **vendor-verbatim** rendered-geometry design-conformance helper: effective ≥44×44px touch targets (visual box + `::before`/`::after` negative-inset expansion), pairwise non-overlap, horizontal-overflow guard, live Chart.js tick/cue config reads, and the 320/390/430/772px × light/dark matrix runner — the rendered leg of the fleet design canon that `fleet-config`'s static `design_lint.py` can't prove. Copy it byte-for-byte into an app's `tests/e2e/`; selectors, budgets, and the theme mechanism are call-site arguments. Proven by `tests/e2e/test_geometry_helper.py` against hermetic twin fixtures (`tests/e2e/_fixtures/geometry/`). See `docs/playwright-ui-testing.md` ("Rendered-geometry design-conformance helper").
- `tests/e2e/_e2e_live_guard.py` — canonical, **vendor-verbatim** e2e live-instance guard (manifest key `e2e_live_guard`): refuses (`pytest.exit`, code 2) rather than silently killing or adopting a live app already listening on a fixture's target port, unless a loudly-named env var opts in to *acting on* it — what "acting" means (read-only assertions, or a reclaim via the adopting repo's own canonical restart recipe, never a by-hand kill) is caller-owned and repo-specific, never prescribed by this file. Copy it byte-for-byte into an app's `tests/e2e/`; the port and the opt-in flag name are call-site arguments to `require_disposable_instance(port, flag_env_name)`. Proven by `tests/test_e2e_live_guard.py`. See `CLAUDE.md` ("End-to-end UI testing" — regression suite).
- `tests/e2e/_surface.py` — canonical, **vendor-verbatim** design-surface capture hook (manifest key `surface_capture`): a test calls `surface(page, "jobs.sort-sheet")` once a sheet, dialog, menu or state is open, and the app's e2e suite doubles as a design inventory. A no-op after one env lookup unless `DESIGN_SURFACE_CAPTURE=<dir>` names a directory `/design-review` prepared; then it flips light/dark in place and writes a screenshot plus the in-page measurement per theme, restoring the page afterwards. A one-line conftest import adds the collection filter that runs only the tests that capture. Takes a bare Playwright `Page`; stdlib, `pytest` and Playwright only. Proven by `tests/e2e/test_surface_hook.py` against a static fixture page. See `docs/playwright-ui-testing.md` ("Design surface capture").
- `tests/e2e/_shot.py` + `scripts/shot_baseline.py` — **vendor-verbatim** screenshot baseline (manifest keys `shot_capture`, `shot_baseline`): pinned captures at phone and desktop, light and dark, compared with committed PNGs; a visible change fails the gate, exit 3 is a failure. Opt-in via `[shot_baseline]`. See `docs/playwright-ui-testing.md` ("Screenshot baseline").
- `tests/e2e/_browser_sweep.py` — canonical, **vendor-verbatim** post-run sweep for leaked Playwright browser helpers: classifies every WebKit helper left after the session and tree-kills only the ones genuinely orphaned and rooted in the checkout this run owns, reporting everything else by its own verdict (including the unkillable `wedged` state) rather than a blind kill. Wired as `pytest_sessionfinish` in `tests/e2e/conftest.py`; also runs standalone (`python tests/e2e/_browser_sweep.py <path> [--dry-run]`). Copy it byte-for-byte into an app's `tests/e2e/`. Proven by `tests/test_browser_sweep.py`. Full liveness mechanism: `docs/playwright-ui-testing.md` ("Post-run sweep for leaked browser helpers").
- `tests/e2e/conftest.py`'s `_neutral_driver_cwd` + `playwright` fixture override — the *fix* the sweep above can only report on. Everything Playwright spawns inherits a working directory, so a suite run from `<repo>-wt-<N>` roots the driver, the browsers and every helper in the worktree, and a helper wedged inside termination pins it permanently. Starting the driver from `%TEMP%` (`gettempdir()`, never `mkdtemp()`) makes a wedge harmless. Pinned by `tests/e2e/test_helper_cwd_isolation.py`; freeing a directory that is *already* pinned is in `docs/playwright-ui-testing.md` ("Freeing a pinned directory") — rebooting the host is not the remedy.
- `src/pooled_http.py` — canonical, **vendor-verbatim** pooled outbound HTTP client (manifest key `pooled_http`): a keep-alive `requests.Session` with a sized `HTTPAdapter`, built once and never reconfigured per call, plus `pooled_request()` which retries once on a dropped connection. Copy it byte-for-byte into an app's `src/`; the pool size and target URL are call-site arguments to `build_session(pool_size)` / `pooled_request(method, url, ...)`. Proven by `tests/test_pooled_http.py`. Reference measured impact: `app-launcher` (145 → 0 `TIME_WAIT` sockets). See `CLAUDE.md` ("Outbound-connection discipline").
- `src/usage_log.py` + `scripts/usage_summary.py` — the **vendor-verbatim** server half of the local-only usage log (manifest key `usage_log`; client half `app/webapp/static/_vendored/usage-log/`): `usage_router(db_path, dependencies=...)` mounts `POST /api/usage/events` (allowlisted kinds, bounded ids, 365-day / 200,000-row retention), `GET /api/usage/summary` and `GET /api/usage/time` (Screen-Time-style foreground minutes per local day, device and view) over the app's `runtime_db_path(<app>, "usage.sqlite3")`. `scripts/usage_summary.py --app <slug> --days 30 --json` reads that file read-only for `/design-review` (`--time` for the foreground-time table), exiting 2 when there is no data yet. Requires `fastapi` in the adopting app (imported only inside the router factory). Proven by `tests/test_usage_log.py` + `tests/e2e/test_vendored_usage_log.py`. See `CLAUDE.md` ("Usage log").
- `src/no_window.py` — the repo's single definition of the Windows `CREATE_NO_WINDOW` subprocess flag. Import `NO_WINDOW` and pass it as `creationflags=` on every spawn of an external console executable, instead of re-deriving the `sys.platform == "win32"` ternary per call site. **Not** vendor-verbatim, and the one documented exception is deliberate: a file that *is* copied byte-identical into adopter repos (`tests/e2e/_browser_sweep.py`, `scripts/classify_e2e.py`) keeps its own local definition, because an import of this module would not resolve in a consumer's tree. See `CLAUDE.md` ("Windows console-subprocess suppression").
- `src/runtime_data.py` — canonical, **vendor-verbatim** runtime-data location resolver (manifest key `runtime_data`): `runtime_db_path(app, filename, env_var=...)` returns `<root>/<app>/<filename>`, root taken from `FLEET_DATA_ROOT` or defaulting to `C:\sqlite` on Windows / `$XDG_DATA_HOME/sqlite` elsewhere, so an always-on service's SQLite writes land on a fast local drive instead of whichever drive the repo was cloned onto. The app's pre-existing full-path override (`TELEMETRY_DB_PATH`, `WR_DB_PATH`, …) stays highest precedence so test harnesses keep working. Stdlib-only, side-effect-free at import. Proven by `tests/test_runtime_data.py`. See `CLAUDE.md` ("Runtime data lives on a fast drive").
- `src/build_info.py` — canonical, **vendor-verbatim** process build-identity capture (manifest key `build_info`): `build_identity()` resolves the `git_sha` + `built_at` this process actually loaded, once at import time with a bounded retry inside the capture (never re-resolved later, so a long-lived process keeps reporting what it booted with even after `HEAD` moves) — the primitive the "Restart/deploy coverage" convention compares against repo `HEAD` to prove a merged change actually shipped. Self-contained on purpose (no import of this repo's own `src/no_window.py`) so a byte-identical copy resolves on its own in another repo's tree. Proven by `tests/test_build_info.py`. See `CLAUDE.md` ("Restart/deploy coverage — merged is not shipped").
- `src/doc_capture/` — canonical, **vendor-verbatim** doc-capture screenshot engine: manifest-driven, fail-safe-masked (an entry without `mask` selectors is refused, never captured raw), input-hash-idempotent Playwright screenshots of the running app, plus a README "tour" section regenerated between `<!-- docs-shots:start/end -->` markers. Reach adapters per app shape — `streamlit` (proven in the pilot) and `url` (FastAPI + static PWA), selected by the manifest's `app.kind`; the clean non-stealth Chrome launch variant ships self-contained in `launch.py`. Relative imports keep the package location-independent (content-management adopts it at `config/doc_capture/`). CLI: `python -m src.doc_capture capture|readme|all`. Manifest contract + adoption recipe: `src/doc_capture/README.md`; the LLM orchestration half (`/docs-shots`) is owned by `fleet-config`.
- `brand/` + `scripts/brand_gen.py` — the fleet icon/brand generator: `brand/catalog.json` catalogs 22 curated, vendor-verbatim Lucide SVG masters (one per project identity); `brand_gen.py`'s `render_set()` rasterizes a chosen master into every size the fleet needs — favicon, `apple-touch-icon`, Android maskable, Windows tray `.ico`, Stream Deck button. A downstream project calls it from a thin `scripts/gen_icons.py`. See `docs/brand-icons.md`.
- `CLAUDE.md` so AI coding agents (Claude Code, Cursor, Codex, etc.) can extend the project safely. `AGENTS.md` is a one-line pointer to it for non-Claude tools.
- `.fleet.toml` — this repo's card on the fleet architecture map. `fleet-config`'s `/system-map` aggregates every repo's `.fleet.toml`, so a cloned repo appears on the map automatically once you edit it. **After cloning, replace its values** with your repo's own. Schema: `fleet-config/architecture/README.md`.
- `scripts/static_ratchet.py` — canonical, **vendor-verbatim** static-analysis ratchet (manifest key `static_ratchet`): fails the gate only on a **new** duplicate block (`jscpd`, Python + JS) or unused import/variable (`ruff` `F401`/`F841`) against a committed `.static-ratchet-baseline.json`. Opt-in via `[static_ratchet]`; Node is a prerequisite; exit 3 is a failure. See [`docs/static-ratchet.md`](docs/static-ratchet.md).
- `scripts/comment_ratchet.py` — canonical, **vendor-verbatim** comment ratchet (manifest key `comment_ratchet`): fails the gate when a file's count of `#NNN` issue references inside comments (Python, JS, CSS, PowerShell) rises above a committed `.comment-ratchet-baseline.json`. Opt-in via `[comment_ratchet]`; exit 3 is a failure. See [`docs/comment-ratchet.md`](docs/comment-ratchet.md).
- `scripts/docs_ratchet.py` — canonical, **vendor-verbatim** docs ratchet (manifest key `docs_ratchet`): keeps the root README under a 40 KiB byte budget and stops history markers (issue references, dated and changelog headings) from growing in `README.md` and `docs/`, against a committed `.docs-ratchet-baseline.json`. Opt-in via `[docs_ratchet]`; exit 3 is a failure. See [`docs/docs-ratchet.md`](docs/docs-ratchet.md) and the convention in [`docs/readme-and-docs.md`](docs/readme-and-docs.md).
- `scripts/structure_ratchet.py` — canonical, **vendor-verbatim**, stdlib-only structure ratchet (manifest key `structure_ratchet`): stops files growing past 1,000 lines, Python and JS functions past 100 lines and directories past 40 modules, forbids `src/` importing `app/`, and holds the root folders to the repo's declared `shape`, against a committed `.structure-ratchet-baseline.json`. Opt-in via `[structure_ratchet]`; exit 3 is a failure. See [`docs/structure-ratchet.md`](docs/structure-ratchet.md) and the layout it enforces in [`docs/repo-layout.md`](docs/repo-layout.md).
- `scripts/instruction_ratchet.py` — canonical, **vendor-verbatim**, stdlib-only instruction ratchet (manifest key `instruction_ratchet`): runs the prompt audit's deterministic lint rules and size caps over `CLAUDE.md`, `AGENTS.md`, rules and skills, and stops violation-level hits or an over-cap file from growing past a committed `.instruction-ratchet-baseline.json`. Opt-in via `[instruction_ratchet]`; exit 3 is a failure. See [`docs/instruction-ratchet.md`](docs/instruction-ratchet.md).
- `scripts/doc_refs_ratchet.py` — canonical, **vendor-verbatim**, stdlib-only doc references ratchet (manifest key `doc_refs_ratchet`): fails the gate on a `README.md`, `CLAUDE.md` or `docs/` reference to a missing repo path, `python -m` module or port, beyond a committed `.doc-refs-ratchet-baseline.json`. Opt-in via `[doc_refs_ratchet]`; exit 3 is a failure. See [`docs/doc-refs-ratchet.md`](docs/doc-refs-ratchet.md).
- `scripts/gen_verify_skill.py` + `scripts/verify_skill_templates/` — generator for a web app's own `verify-<app>` skill (**not** vendored, adopters run it from this checkout): Launch / Doctor / Drive / Evidence / Cleanup / Maintain written for an agent that has never seen the app, plus a feature map (`features/<view>.md`) seeded statically from the repo's `surface()` calls, `[[design.review.extra_steps]]` and `## UX surface` key views. Idempotent (keeps `## Gotchas`); the launch recipe is the optional `.fleet.toml` `[verify]` table (a missing key is a visible `FILL:`, never guessed). `--check` is the maintain mode: `STATIC=` / `MAINTAIN=clean|changed|blocked`, where an unreachable app or a node that did not pass is `blocked`, never `clean`. See [`docs/verify-skill.md`](docs/verify-skill.md).
- `.fleet.toml`'s `[components]` table + `scripts/vendored_catalog.py` — the canonical, machine-readable catalog of every vendor-verbatim component this scaffold publishes, and the source `/propagate-vendored` and `fleet-config`'s drift check both read. See [`docs/components.md`](docs/components.md).
- `docs/agents/` — the master AGENTS/CLAUDE templates, the adapt prompt, the rollout runbook, and the standalone `print()`→`logging` migration prompt. Single source of truth for the **project-shaped** agent instructions across all my repos (the universal dev-workflow directives live once in the machine config, `fleet-config/global-CLAUDE.md`).
- [`docs/repo-layout.md`](docs/repo-layout.md) — where code goes: the canonical tree, placement rules and allowed extra roots for each fleet repo shape, the four structure rules, and the per-repo `docs/layout.md` contract.
- `docs/playwright-ui-testing.md` — didactic reference for the two-loop browser-testing recipe (headed agent verification + optional headless regression suite). Read this when bootstrapping on a fresh PC.
- `docs/shared-chrome-profile.md` — didactic reference for projects that drive real Chrome with a persistent profile: when two jobs share one profile, serialize access by waiting (never killing the holder). Read this before adding a second job on a shared profile.
- `docs/windows-tray.md` — didactic reference + canonical `tray.bat` shape for projects that ship a Windows tray owning a long-lived service: idempotent single-instance start, and an orphan-proof `--restart` that reclaims owned service ports by PID (scoped to the app's `.venv`, matched on CommandLine). Read this before writing or fixing a tray restart.
- `docs/app-onboarding.md` — didactic end-to-end playbook for standing up a new self-hosted PWA app from this scaffold: bootstrap the app, provision HTTPS (preferred: a real Let's Encrypt cert via `tailscale cert` for a tailnet app — `scripts/gen_tailscale_cert.py`, zero per-device trust; the self-signed-CA `certutil` + Chrome-restart + `/install-ca` mobileconfig dance only as the LAN-only fallback), and the iPhone/Android PWA install. Links to `docs/windows-tray.md` for the tray half. Read this when bringing up a new tray-resident webapp.

## Setup

From the repo root, after cloning (Windows / PowerShell):

```powershell
py -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

POSIX:

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

Never activate the venv — invoke its interpreter directly, as above and everywhere else in this README. That keeps every command copy-pasteable into a script, a hook, or an agent tool call, none of which inherit an `activate` from an interactive shell.

### Agent setup after cloning

`AGENTS.md` points to the maintained `CLAUDE.md`; keep both committed. This scaffold seeds no executable project skills. When adopting existing root or package skills, keep one source per skill and follow [Portable project skills](docs/agents/project-skills.md) to inspect native discovery, preserve private context and real agent directories, and recreate only the missing scoped links. Ignored links are local onboarding artifacts and must be recreated for each clone/worktree. That reference includes the Claude/Codex/Pi/Grok evidence matrix and collision/ignore checks; fleet-wide installation belongs to `fleet-config`.

## Run

```bash
# Local (opens browser)
launch_app.bat            # Windows
./launch_app.sh           # macOS / Linux

# Share via Cloudflare Tunnel
launch_server.bat         # Windows
./launch_server.sh        # macOS / Linux
```

Or directly:

```bash
streamlit run app/app.py
```

Standalone pipeline run (no UI):

```bash
python -m src.pipelines.example_pipeline
```

## Layout

```
app/
  .streamlit/config.toml    default (dark) theme + server defaults
  styles/light.css          light-mode overlay (runtime-injected)
  app.py                    Streamlit entry: page config,
                            st.navigation + light/dark toggle
  log_panel.py              Streamlit live/one-shot log panels over the logger's ring buffer
  views/                    one render() per file (welcome, ...)
  tray/single_instance.py   vendor-verbatim named-mutex primitive for tray apps
  tray/watchdog.py          vendor-verbatim tray self-heal primitives (spawn retry/backoff, health watchdog, breadcrumb log)
  webapp/static/_vendored/  vendor-verbatim web-app UI components (base/, nav/, icons/, card/, disclosure/, modal/, empty-state/, switch/, icon-tile/, button/, range-tab/, page-foot/, home-head/, select-native/, action-row/, text-size/, toast/, row-menu/, icon-button/, day-row/, day-marks/, segmented/, usage-log/ + demo.html gallery)
src/
  config.py                 paths + env-driven settings
  logger.py                 the elegant logger
  no_window.py              the one CREATE_NO_WINDOW flag every spawn imports
  pooled_http.py            vendor-verbatim pooled outbound HTTP client (keep-alive session + single-retry dispatch)
  runtime_data.py           vendor-verbatim SQLite-location resolver (C:\sqlite\<app>\, off the spinning disk)
  usage_log.py              vendor-verbatim local-only usage-log router (views, taps, device class -> usage.sqlite3)
  build_info.py             vendor-verbatim process build-identity capture (git_sha + built_at, captured once at import)
  notify/                   vendor-verbatim Telegram notifier (send_text + factory/config)
  doc_capture/              vendor-verbatim doc-capture screenshot engine (manifest-driven, fail-safe-masked, input-hash-idempotent + README tour regen)
  pipelines/                one run() per file
brand/                      curated, vendor-verbatim Lucide SVG masters + catalog.json (fleet icon identity)
scripts/
  brand_gen.py               render_set() — generates favicon/apple-touch/maskable/tray/Stream-Deck icons from a brand master
  classify_e2e.py             routes the e2e browser phase to skip/static/full from `.fleet.toml`'s [e2e] table
  comment_ratchet.py          gate stage: #NNN comment references may not rise above a committed baseline
  doc_refs_ratchet.py         gate stage: doc references to missing paths, modules or ports may not rise above a committed baseline
  docs_ratchet.py              gate stage: README byte budget + docs history markers may not rise above a committed baseline
  gen_tailscale_cert.py       copy-to-adapt HTTPS cert generator via `tailscale cert`
  gen_verify_skill.py         generates a web app's own verify-<app> skill (Launch/Doctor/Drive/Evidence/Cleanup/Maintain)
  instruction_ratchet.py      gate stage: prompt-audit lint hits and size caps in instruction files may not rise above a committed baseline
  shot_baseline.py             gate stage: recaptured screenshots may not visibly drift from the committed baseline
  static_ratchet.py            gate stage: new duplicate code or unused imports/variables may not rise above a committed baseline
  structure_ratchet.py        gate stage: oversized files/functions, flat directories, src->app imports may not rise above a committed baseline
  usage_summary.py           per-view / per-control / device summary of an app's usage.sqlite3, --time = foreground minutes (exit 2 = no data yet)
  vendored_catalog.py         reads .fleet.toml's [components] table, the vendor-verbatim component catalog
  verify-before-ship.ps1       the one pass/fail pre-ship gate, sequencing every stage above
data/                       input / output / logs (gitignored)
launch_app.{bat,sh}
launch_server.{bat,sh}
tray.bat.template           canonical tray launcher (copy + adapt for tray apps)
.github/workflows/
  ci.yml.template                web-app CI gate: install, unit, Playwright desktop + phone (copy + adapt)
  main-gate-watch.yml.template   red-main issue filer (copy + adapt; needs an Actions gate)
```

See `CLAUDE.md` for the cross-project agent conventions.

## Conventions

### Import rules

- `app/app.py` prepends the project root to `sys.path`, so `from src.X import Y` works everywhere downstream.
- UI code in `app/` imports from `src/`, **never the other way around**.
- `streamlit` is imported only under `app/` — enforced by ruff `TID251` (banned-api in `pyproject.toml`, `app/**` is the one ignore), including imports inside functions. See [`docs/streamlit-conventions.md`](docs/streamlit-conventions.md).
- Views can import siblings as top-level modules (`from views import welcome`) because Streamlit puts `app/` on `sys.path` when it runs `app/app.py`.
- The view directory is named `views/` (not `pages/`) on purpose: Streamlit auto-discovers any subdirectory called `pages/` and adds it to the sidebar, which would duplicate the navigation built in `app.py`.
- Pipelines run standalone with `python -m src.pipelines.<name>` — they must not import from `app/`.

### Views

- One file per view in `app/views/`. Always export `def render() -> None`.
- Register the view in `app/app.py` by appending an `st.Page` entry to `nav_pages` (Streamlit's native multipage navigation renders the sidebar entries automatically).
- `app/app.py` itself only configures the page, renders the sidebar (light/dark toggle), and hands off to `st.navigation` — it does not draw view content directly. The landing view is `app/views/welcome.py` (registered with `default=True`).
- A view should orchestrate; **business logic lives in `src/`** so it can be reused from the CLI or tests.

### Pipelines

- One file per pipeline in `src/pipelines/`. Always export `def run(**kwargs)`.
- Pipelines must **never** call `print()` or `st.*`. They emit progress through the logger so they work the same way from the UI, the CLI, and tests.
- Return a small JSON-serialisable summary dict (counts, timings, output paths). The UI / caller decides how to display it.

### Logger

```python
from src import get_logger

log = get_logger("my_pipeline")
log.info("Loading %d rows", len(rows))
log.warning("Skipping malformed row id=%s", row.id)
log.error("Upload failed", exc_info=True)
```

One call → three sinks:

1. Color-tinted, timestamped terminal output.
2. Rotating file at `data/logs/app.log` (1 MB × 3 backups).
3. In-memory ring buffer that Streamlit views can render live via `app.log_panel.stream_to_streamlit` (runs the work on a background thread and streams its logs into a live panel; see `app/views/pipeline_runner.py` for the canonical usage) or one-shot via `app.log_panel.render_log_panel`.

Do not configure root logging elsewhere — it is set up once in `src/logger.py` and is idempotent.

### Config

Read settings from `src/config.py`, not from `os.environ` directly. Add new keys there with a sensible default so the app boots without a `.env` file.

## Testing

Two layers, both under `tests/`:

- **Unit** (`tests/test_*.py`) — one file per `src/` module, hermetic. Runs in well under a second.
- **Headless e2e** (`tests/e2e/`) — `pytest-playwright` against a real browser. The `streamlit_app` session fixture (`tests/e2e/conftest.py`) **boots a disposable instance and refuses an occupied port**: before booting anything it checks the e2e port through the vendor-verbatim guard (`_e2e_live_guard.py`'s `require_disposable_instance`) and, with no opt-in set, ends the run rather than killing or adopting a process it did not start — a bare `pytest tests/e2e` must never drive a live app. On a free port it boots fresh against the current code on disk via `tests/_streamlit_lifecycle.py`, so the suite can never pass against a stale process. Set `STREAMLIT_E2E_LIVE=1` to explicitly permit reclaiming an occupied port (see below); if a run exits with the guard's refusal, that flag — not a manual kill — is the documented way past it.
  - The suite is eleven files with **more test functions and collected items than the under-15-per-project target** (recount with `pytest tests/e2e --collect-only -q` rather than trusting a hardcoded number here — browser and viewport parametrisation makes the collected-item count drift independently of the file count): `test_smoke.py`, `test_geometry_helper.py`, `test_helper_cwd_isolation.py`, `test_tray_lifecycle_behavior.py`, `test_surface_hook.py`, `test_shot_baseline.py`, the vendored-component harnesses `test_vendored_components.py` + `test_vendored_nav.py` + `test_vendored_font_inherit.py` + `test_vendored_row_menu_placement.py`, and `test_vendored_usage_log.py`. Expand per the regression-suite rules in `CLAUDE.md` ("End-to-end UI testing") — the target is under 15 tests *per project*; this scaffold carries more because it is also the proving ground for the vendor-verbatim primitives it ships.
  - `test_tray_lifecycle_behavior.py` is the odd one out — no browser, Windows-only, `pytest.mark.slow` — it drives the real `tray.bat.template` + canonical `tray_lifecycle.ps1` through a cold-start/restart/verify cycle; see `docs/windows-tray.md`. `test_geometry_helper.py` proves the vendor-verbatim rendered-geometry helper against hermetic twin fixtures (needs a one-time `playwright install webkit` for its two-engine run); see `docs/playwright-ui-testing.md` ("Rendered-geometry design-conformance helper").

One-time setup:

```powershell
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe -m playwright install chromium
```

Run (POSIX: swap `.\.venv\Scripts\python.exe` for `./.venv/bin/python`):

```powershell
& .\.venv\Scripts\python.exe -m pytest                      # everything
& .\.venv\Scripts\python.exe -m pytest --ignore=tests/e2e    # unit only, fast
& .\.venv\Scripts\python.exe -m pytest tests/e2e             # e2e only
```

The e2e port is `STREAMLIT_E2E_PORT` in `tests/_streamlit_lifecycle.py` (default `8766`) — change it per project so two scaffolded projects don't collide.

`STREAMLIT_E2E_LIVE=1` is the one opt-in that lets the fixture **act on** that port when something is already listening on it — a kill + fresh restart through this repo's own `ensure_fresh_streamlit` helper, never a by-hand kill. Unset (the default), an occupied port is a hard refusal with a message naming the flag, not a silent adoption. Opt-**in** on purpose: forgetting an opt-*out* flag is what silently re-enables driving a live app. This scaffold's Streamlit dev server is stateless and cheap to restart, which is what makes reclaiming a legitimate choice here — a host holding user state (a session-host, a worker with in-flight jobs) gets its own disposable instance unconditionally instead. See `CLAUDE.md` ("End-to-end UI testing").

```powershell
$env:STREAMLIT_E2E_LIVE = "1"; & .\.venv\Scripts\python.exe -m pytest tests/e2e
```

**Force-restart the dev Streamlit yourself** — the same thing the e2e fixture does *under `STREAMLIT_E2E_LIVE=1`*, handy when an edit isn't showing up in the browser:

```powershell
& .\.venv\Scripts\python.exe -c "from tests._streamlit_lifecycle import ensure_fresh_streamlit; ensure_fresh_streamlit()"
```

### Verification gate

`scripts/verify-before-ship.ps1` is the one pass/fail pre-ship gate — run it before declaring any change done:

```powershell
& .\scripts\verify-before-ship.ps1
```

It sequences, fail-fast: **byte-compile** → **ruff** (whole repo) → **static ratchet** (opt-in; new duplicates / unused code vs a committed baseline, [`docs/static-ratchet.md`](docs/static-ratchet.md)) → **comment ratchet** (opt-in; a file's `#NNN` references inside comments may not rise above a committed baseline, [`docs/comment-ratchet.md`](docs/comment-ratchet.md)) → **docs ratchet** (opt-in; the README stays under its byte budget and docs history markers may not rise above a committed baseline, [`docs/docs-ratchet.md`](docs/docs-ratchet.md)) → **structure ratchet** (opt-in; file size, function length, flat directories and the `src`→`app` layer contract may not grow past a committed baseline, [`docs/structure-ratchet.md`](docs/structure-ratchet.md)) → **instruction ratchet** (opt-in; the prompt audit's deterministic lint hits and size caps in `CLAUDE.md`, `AGENTS.md`, rules and skills may not rise above a committed baseline, [`docs/instruction-ratchet.md`](docs/instruction-ratchet.md)) → **doc refs ratchet** (opt-in; doc references to missing paths, modules or ports, [`docs/doc-refs-ratchet.md`](docs/doc-refs-ratchet.md)) → **mypy `--strict`** (vendor-verbatim primitives only) → **pytest (unit, non-e2e)** → **routed e2e**. Strictness lives in `pyproject.toml` (`[tool.ruff.lint]` adds `UP` to ruff's defaults; `[tool.mypy]` sets `strict = true`); the script only sequences the tools.

The mypy stage gates **vendor-verbatim primitives** — modules like `app/tray/single_instance.py` and `scripts/classify_e2e.py` that consumers copy byte-identical and run through *their* `ruff` + `mypy --strict` gates. Gating them here means a canonical primitive can never ship lint- or type-dirty and redden every consumer's CI. When you add a new vendored primitive, add it to `.fleet.toml`'s `[components]` table — `tests/test_vendored_catalog.py` is the anti-drift guard.

The final **routed e2e** stage is diff-proportionate ([`docs/e2e-routing.md`](docs/e2e-routing.md)): instead of always running the whole `tests/e2e` browser suite, `scripts/classify_e2e.py` maps the branch's changed files to a tier declared in `.fleet.toml`'s `[e2e]` table — `skip` (backend/docs-only diff → no browser suite), `static` (inert assets → the narrow smoke target), or `full` (real UI/behaviour, or **any** unrecognized/mixed/empty diff → the whole suite). Routing is fail-safe: uncertainty always runs `full`. It only ever narrows an already-narrow diff, never an unmatched one.

## Extending the scaffold

- **New view** → create `app/views/<name>.py` with `render()`, append `st.Page(<module>.render, title=..., icon=...)` to `nav_pages` inside `app/app.py`.
- **New pipeline** → create `src/pipelines/<name>.py` with `run(...)`, log via `get_logger("<name>")`.
- **New shared helper** → put it under `src/` and re-export from `src/__init__.py` if it is part of the public surface.
- **New dependency** → add to `requirements.txt` (follow the existing version-specifier style), then re-run `pip install -r requirements.txt` in `.venv`.

## What NOT to do

- Don't sprinkle `print()` for progress — use the logger.
- Don't import Streamlit anywhere in `src/`, not even lazily inside a function — ruff `TID251` fails the gate. Streamlit-only helpers belong under `app/` (e.g. `app/log_panel.py`).
- Don't hardcode paths. Build them off `src.config.ROOT_DIR`, `INPUT_DIR`, `OUTPUT_DIR`, `LOG_DIR`.
- Don't add per-project files to this scaffold itself. Clone it, rename, and customise downstream.

## Theming

The app ships two themes: **dark** (default) and **light** (sidebar
toggle). They are implemented with two *different* mechanisms on
purpose — not an oversight:

| Theme | Where it lives                | Mechanism                       |
| ----- | ----------------------------- | ------------------------------- |
| Dark  | `app/.streamlit/config.toml`  | Streamlit native theme config   |
| Light | `app/styles/light.css`        | Runtime CSS overlay (`st.markdown`) |

**Why the asymmetry?**

- `config.toml` is Streamlit's *native* theme mechanism. It sets the
  CSS variables that propagate through the entire component tree —
  including charts, internal widget states, and elements that don't
  expose a stable `data-testid`. That's what you want for the default.
- `config.toml` is read **once at server startup**, so it can't be
  toggled at runtime. A light/dark switch therefore *has* to be an
  overlay: a stylesheet injected into the DOM on demand.
- The overlay is a pragmatic bag of `!important` overrides that only
  reaches selectors visible in the DOM. It's good enough to flip
  surface colors, but it won't cleanly re-theme things like Plotly
  charts or Streamlit's internal color variables.

**Practical rule:** the theme you want as default goes in
`config.toml` (complete, native). The alternate theme goes in
`app/styles/*.css` (runtime-switchable, pragmatic). If you want
*light* as the default instead, swap them: set the light palette in
`config.toml` and write a `dark.css` overlay.

**Extending:**

- Tweak colors in [`app/styles/light.css`](app/styles/light.css) —
  plain CSS with full editor support.
- Add more overlays by dropping another `.css` file in `app/styles/`
  and calling `_inject_css("name.css")` from `app/app.py`.
- Selectors target Streamlit's `data-testid` attributes (e.g.
  `[data-testid="stTextInput"] input`) and BaseWeb's `data-baseweb`
  attributes (e.g. `[data-baseweb="select"]`). These are stable in
  practice but not a public API — re-check after major Streamlit
  upgrades.
