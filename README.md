# Project Scaffolding

Starter template for a **Streamlit app + Python pipelines** project.
Clone this directory, rename it, and start building.

## What you get

- `app/` — Streamlit UI: entry point + view registry, views, theme.
- `src/` — non-UI Python (logger, config, pipelines), reusable from the CLI and tests.
- An **elegant logger** (`src/logger.py`) — one `log.info(...)` call reaches the terminal, a rotating file, and a live Streamlit panel. See [Logger](#logger).
- `app/.streamlit/config.toml` — dark theme + sane server defaults.
- A **light-mode toggle** in the sidebar, CSS overlay, no restart. See [Theming](#theming).
- `launch_app.{bat,sh}` — one-click local launch.
- `launch_server.{bat,sh}` — local launch + Cloudflare Tunnel for public sharing.
- `tray.bat.template` — copy-to-adapt Windows tray launcher for a long-lived-service app. See [`docs/windows-tray.md`](docs/windows-tray.md).
- `.github/workflows/ci.yml.template` — copy-to-adapt web-app CI gate (unit + Playwright desktop/phone). See [`docs/ci-conventions.md`](docs/ci-conventions.md) ("Web-app CI template").
- `.github/workflows/main-gate-watch.yml.template` — copy-to-adapt watcher that files a tracking issue when your Actions gate goes red on `main`. See `CLAUDE.md` ("GitHub Actions CI conventions").
- `scripts/gen_tailscale_cert.py` — copy-to-adapt HTTPS cert generator via `tailscale cert`. See [`docs/app-onboarding.md`](docs/app-onboarding.md) §2.
- `%USERPROFILE%/.claude/tray/tray_lifecycle.ps1` — the one shared, machine-local tray lifecycle helper `tray.bat.template` shells to. See [`docs/windows-tray.md`](docs/windows-tray.md).
- `app/tray/single_instance.py` — vendor-verbatim named-mutex primitive for tray apps. See [`docs/windows-tray.md`](docs/windows-tray.md) (single-instance gotcha).
- `app/tray/watchdog.py` — vendor-verbatim tray self-heal primitives (manifest key `tray_watchdog`): spawn retry/backoff, dead/wedged health watchdog, breadcrumb log. See [`docs/windows-tray.md`](docs/windows-tray.md) (webapp self-heal gotcha).
- `app/webapp/static/_vendored/` — vendor-verbatim fleet design-system component library (nav, card, modal, switch, toast, usage-log, day-row, ...) for the FastAPI + static PWA shape. See [`app/webapp/static/_vendored/README.md`](app/webapp/static/_vendored/README.md) and `CLAUDE.md` ("Web-app visual identity").
- `tests/e2e/_geometry.py` — vendor-verbatim rendered-geometry design-conformance helper (touch targets, overlap, overflow, theme matrix). See [`docs/playwright-ui-testing.md`](docs/playwright-ui-testing.md) ("Rendered-geometry design-conformance helper").
- `tests/e2e/_e2e_live_guard.py` — vendor-verbatim e2e live-instance guard (manifest key `e2e_live_guard`): refuses to drive a port already live unless the caller opts in. See `CLAUDE.md` ("End-to-end UI testing" — regression suite).
- `tests/e2e/_surface.py` — vendor-verbatim design-surface capture hook (manifest key `surface_capture`) for `/design-review`'s screenshot inventory. See [`docs/playwright-ui-testing.md`](docs/playwright-ui-testing.md) ("Design surface capture").
- `tests/e2e/_shot.py` + `scripts/shot_baseline.py` — vendor-verbatim screenshot baseline (manifest keys `shot_capture`, `shot_baseline`): phone/desktop, light/dark, diffed against committed PNGs. See [`docs/playwright-ui-testing.md`](docs/playwright-ui-testing.md) ("Screenshot baseline").
- `tests/e2e/_layout_lint.py` — vendor-verbatim layout lint (manifest key `layout_lint`): captures each changed UI state at phone/desktop x light/dark outside the checkout and fails on overflow, clipped text, overlap, off-screen or small tap targets. See [`docs/playwright-ui-testing.md`](docs/playwright-ui-testing.md) ("Layout lint").
- `tests/e2e/_browser_sweep.py` — vendor-verbatim post-run sweep for leaked Playwright browser helpers. See [`docs/playwright-ui-testing.md`](docs/playwright-ui-testing.md) ("Post-run sweep for leaked browser helpers").
- `tests/e2e/conftest.py`'s `_neutral_driver_cwd` — roots the Playwright driver in `%TEMP%` so a wedged helper can't pin the worktree. See [`docs/playwright-ui-testing.md`](docs/playwright-ui-testing.md) ("Freeing a pinned directory").
- `src/pooled_http.py` — vendor-verbatim pooled outbound HTTP client (manifest key `pooled_http`): keep-alive session + single-retry dispatch. See `CLAUDE.md` ("Outbound-connection discipline").
- `src/usage_log.py` + `scripts/usage_summary.py` — vendor-verbatim server half of the local-only usage log (manifest key `usage_log`). See `CLAUDE.md` ("Usage log").
- `src/compression.py` — vendor-verbatim stream-safe gzip middleware (manifest key `compression`). See [`docs/webapp-pwa-conventions.md`](docs/webapp-pwa-conventions.md).
- `src/no_window.py` — vendor-verbatim `CREATE_NO_WINDOW` subprocess-flag definition (manifest key `no_window`); a file copied byte-identical into adopters (e.g. `_browser_sweep.py`, `classify_e2e.py`) keeps its own local flag instead, since importing this module would not resolve there. See `CLAUDE.md` ("Windows console-subprocess suppression").
- `src/runtime_data.py` — vendor-verbatim runtime-data location resolver (manifest key `runtime_data`), so always-on SQLite writes land on a fast local drive. See `CLAUDE.md` ("Runtime data lives on a fast drive").
- `src/resource_probe.py` + `tests/soak/_resource_soak.py` — vendor-verbatim thread/handle/RSS sampler with a runtime breadcrumb, and the gate soak that fails a webapp leaking threads or handles (manifest keys `resource_probe`, `resource_soak`). See [`docs/long-lived-process-conventions.md`](docs/long-lived-process-conventions.md) ("Resource soak").
- `src/build_info.py` — vendor-verbatim process build-identity capture (manifest key `build_info`). See `CLAUDE.md` ("Restart/deploy coverage — merged is not shipped").
- `src/doc_capture/` — vendor-verbatim doc-capture screenshot engine + README "tour" regen. See [`src/doc_capture/README.md`](src/doc_capture/README.md).
- `brand/` + `scripts/brand_gen.py` — the fleet icon/brand generator (favicon, PWA icons, tray `.ico`, Stream Deck button). See [`docs/brand-icons.md`](docs/brand-icons.md).
- `CLAUDE.md` so AI coding agents can extend the project safely; `AGENTS.md` is a one-line pointer to it for non-Claude tools.
- `.fleet.toml` — this repo's card on the fleet architecture map. **After cloning, replace its values** with your repo's own. Schema: `fleet-config/architecture/README.md`.
- `scripts/*_ratchet.py` (static, comment, docs, structure, instruction, doc refs, dead code, conventions) — opt-in, vendor-verbatim baseline-and-ratchet gate stages; each fails only on a new hit past its committed baseline. See [`docs/static-ratchet.md`](docs/static-ratchet.md), [`docs/comment-ratchet.md`](docs/comment-ratchet.md), [`docs/docs-ratchet.md`](docs/docs-ratchet.md), [`docs/structure-ratchet.md`](docs/structure-ratchet.md), [`docs/instruction-ratchet.md`](docs/instruction-ratchet.md), [`docs/doc-refs-ratchet.md`](docs/doc-refs-ratchet.md), [`docs/dead-code-ratchet.md`](docs/dead-code-ratchet.md), [`docs/conventions-ratchet.md`](docs/conventions-ratchet.md).
- `scripts/box_lock_gate.ps1` — vendor-verbatim wrapper that runs the gate under `fleet-config`'s shared box load lock, so a CPU-burn proof waits instead of starving the browser stage. See [Verification gate](#verification-gate).
- `scripts/gen_verify_skill.py` + `scripts/verify_skill_templates/` — generator for a web app's own `verify-<app>` skill. See [`docs/verify-skill.md`](docs/verify-skill.md).
- `.fleet.toml`'s `[components]` table + `scripts/vendored_catalog.py` — the canonical catalog of every vendor-verbatim component this scaffold publishes. See [`docs/components.md`](docs/components.md).
- `docs/agents/` — the master AGENTS/CLAUDE templates, the adapt prompt and the rollout runbook.
- [`docs/repo-layout.md`](docs/repo-layout.md) — where code goes: canonical tree, placement rules, extra roots per repo shape.
- `docs/playwright-ui-testing.md` — the two-loop browser-testing recipe (headed agent verification + optional headless regression suite).
- `docs/shared-chrome-profile.md` — serializing access to a persistent Chrome profile shared across jobs.
- `docs/windows-tray.md` — canonical `tray.bat` shape: idempotent single-instance start, orphan-proof `--restart`.
- `docs/app-onboarding.md` — end-to-end playbook for standing up a new self-hosted PWA app from this scaffold.

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
  compression.py            vendor-verbatim stream-safe gzip middleware
  resource_probe.py         vendor-verbatim thread/handle/RSS sampler + runtime breadcrumb
  build_info.py             vendor-verbatim process build-identity capture (git_sha + built_at, captured once at import)
  notify/                   vendor-verbatim Telegram notifier (send_text + factory/config)
  doc_capture/              vendor-verbatim doc-capture screenshot engine (manifest-driven, fail-safe-masked, input-hash-idempotent + README tour regen)
  pipelines/                one run() per file
brand/                      curated, vendor-verbatim Lucide SVG masters + catalog.json (fleet icon identity)
scripts/
  box_lock_gate.ps1           vendor-verbatim wrapper: dot-sourced by verify-before-ship.ps1 to hold fleet-config's shared box load lock for the run
  brand_gen.py               render_set() — generates favicon/apple-touch/maskable/tray/Stream-Deck icons from a brand master
  classify_e2e.py             routes the e2e browser phase to skip/static/full from `.fleet.toml`'s [e2e] table
  comment_ratchet.py          gate stage: #NNN comment references may not rise above a committed baseline
  conventions_ratchet.py      gate stage: fleet-convention rule hits may not rise above a committed baseline
  dead_code_ratchet.py        gate stage: unreferenced functions, classes and methods may not rise above a committed baseline
  doc_refs_ratchet.py         gate stage: doc references to missing paths, modules or ports may not rise above a committed baseline
  docs_ratchet.py              gate stage: README byte budget + docs history markers may not rise above a committed baseline
  gen_tailscale_cert.py       copy-to-adapt HTTPS cert generator via `tailscale cert`
  gen_verify_skill.py         generates a web app's own verify-<app> skill (Launch/Doctor/Drive/Evidence/Cleanup/Maintain)
  instruction_ratchet.py      gate stage: prompt-audit lint hits and size caps in instruction files may not rise above a committed baseline
  shot_baseline.py             gate stage: recaptured screenshots may not visibly drift from the committed baseline
  static_ratchet.py            gate stage: new duplicate code, unused names or bug/security patterns may not rise above a committed baseline
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
  - The suite is fifteen files with **more test functions and collected items than the under-15-per-project target** (recount with `pytest tests/e2e --collect-only -q` — browser and viewport parametrisation makes the item count drift from the file count): `test_smoke.py`, `test_geometry_helper.py`, `test_helper_cwd_isolation.py`, `test_tray_lifecycle_behavior.py`, `test_surface_hook.py`, `test_shot_baseline.py`, `test_layout_lint.py`, the vendored-component harnesses `test_vendored_components.py` + `test_vendored_day.py` + `test_vendored_home_head.py` + `test_vendored_row_menu.py` + `test_vendored_nav.py` + `test_vendored_font_inherit.py` + `test_vendored_row_menu_placement.py`, and `test_vendored_usage_log.py`. Expand per the regression-suite rules in `CLAUDE.md` ("End-to-end UI testing") — the target is under 15 tests *per project*; this scaffold carries more because it is also the proving ground for the vendor-verbatim primitives it ships.
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

It sequences, fail-fast: **byte-compile** → **ruff** (whole repo) → the opt-in **ratchets**, each failing only on a measure that rises above its committed baseline: [static](docs/static-ratchet.md) → [comment](docs/comment-ratchet.md) → [docs](docs/docs-ratchet.md) → [structure](docs/structure-ratchet.md) → [instruction](docs/instruction-ratchet.md) → [doc refs](docs/doc-refs-ratchet.md) → [dead code](docs/dead-code-ratchet.md) → [conventions](docs/conventions-ratchet.md) → **mypy `--strict`** (vendor-verbatim primitives only) → **pytest (unit, non-e2e)** → **routed e2e** → **shot baseline** (compares the browser slice's recaptured screenshots with the committed baseline; see [Screenshot baseline](docs/playwright-ui-testing.md)). Strictness lives in `pyproject.toml` (`[tool.ruff.lint]` adds `UP` to ruff's defaults; `[tool.mypy]` sets `strict = true`); the script only sequences the tools. The whole run is wrapped by `scripts/box_lock_gate.ps1` (vendor-verbatim, dot-sourced), which holds `fleet-config`'s shared box load lock so a CPU-burn proof waits instead of starving the browser stage.

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
