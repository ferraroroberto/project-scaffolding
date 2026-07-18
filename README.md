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
  - a **live panel inside the Streamlit UI**, all from a single
    `log.info(...)` call.
- `app/.streamlit/config.toml` — dark theme + sane server defaults.
- A **light-mode toggle** in the sidebar, backed by
  [`app/styles/light.css`](app/styles/light.css) (CSS overlay, no restart).
  See [Theming](#theming) for why dark lives in config and light lives
  in CSS.
- `launch_app.{bat,sh}` — one-click local launch.
- `launch_server.{bat,sh}` — local launch + Cloudflare Tunnel for
  public sharing (no API keys leave your machine).
- `tray.bat.template` — copy-to-adapt canonical Windows tray launcher for apps that run a tray owning a long-lived service. Replace the four `__PLACEHOLDER__` tokens and you get the orphan-proof `tray.bat --restart` by default. See `docs/windows-tray.md`.
- `%USERPROFILE%/.claude/tray/tray_lifecycle.ps1` — the ONE shared, machine-local tray lifecycle helper owned by `fleet-config` (not vendored in this repo), which `tray.bat.template` shells to with `-File` once (app-specific venv path / tray-match regex / owned ports / tray launch passed as arguments). Keeps detect → kill → reclaim → start → version verification out of cmd `for /f` parsing and inline `powershell -Command "…"`, both of which can break under a non-interactive `--restart` and silently adopt the stale build. `tray.bat` hard-errors (never no-ops) if the shared path is missing, naming `fleet-config`'s `install.ps1` as the fix. See `docs/windows-tray.md` (#54, #153).
- `app/tray/single_instance.py` — canonical, **vendor-verbatim** named-mutex primitive for tray apps: `SingleInstance` (the tray's in-process single-instance lock) + `cross_process_lock` (serializes the webapp adopt-or-spawn so two trays can't both spawn it). Copy it byte-for-byte into a tray app — the per-app mutex *names* are passed at the call site, so the file stays identical fleet-wide. See `docs/windows-tray.md` (gotcha #4).
- `app/webapp/static/_vendored/` — **vendor-verbatim web-app UI components** for the FastAPI + static PWA shape: the fleet design system's *implementation* layer (the *spec* lives in `fleet-config`'s `design.md`/`design.dark.md`). Components: `nav/` — the canonical floating bottom-tab navigation; `icons/` — the inline Lucide icon sprite + `icon()` helper; and the canon extracted from the home-automation polish round (design.md v2 "Component contracts"): `card/`, `disclosure/`, `modal/`, `empty-state/`, `switch/`, `icon-tile/`, `button/`, `range-tab/`, `page-foot/`, `home-head/`, `select-native/`. `demo.html` is the component gallery (open over HTTP, light + dark), driven by the `tests/e2e/test_vendored_components.py` render harness. Copy a component folder byte-for-byte; adapt only your markup + token values. See `app/webapp/static/_vendored/README.md` and `CLAUDE.md` ("Web-app visual identity").
- `tests/e2e/_geometry.py` — canonical, **vendor-verbatim** rendered-geometry design-conformance helper (#157): effective ≥44×44px touch targets (visual box + `::before`/`::after` negative-inset expansion), pairwise non-overlap, horizontal-overflow guard, live Chart.js tick/cue config reads, and the 320/390/430/772px × light/dark matrix runner — the rendered leg of the fleet design canon that `fleet-config`'s static `design_lint.py` can't prove. Copy it byte-for-byte into an app's `tests/e2e/`; selectors, budgets, and the theme mechanism are call-site arguments. Proven by `tests/e2e/test_geometry_helper.py` against hermetic twin fixtures (`tests/e2e/_fixtures/geometry/`). See `docs/playwright-ui-testing.md` ("Rendered-geometry design-conformance helper").
- `src/doc_capture/` — canonical, **vendor-verbatim** doc-capture screenshot engine (#171; pilot: `content-management#110`): manifest-driven, fail-safe-masked (an entry without `mask` selectors is refused, never captured raw), input-hash-idempotent Playwright screenshots of the running app, plus a README "tour" section regenerated between `<!-- docs-shots:start/end -->` markers. Reach adapters per app shape — `streamlit` (proven in the pilot) and `url` (FastAPI + static PWA), selected by the manifest's `app.kind`; the clean non-stealth Chrome launch variant ships self-contained in `launch.py`. Relative imports keep the package location-independent (content-management adopts it at `config/doc_capture/`). CLI: `python -m src.doc_capture capture|readme|all`. Manifest contract + adoption recipe: `src/doc_capture/README.md`; the LLM orchestration half (`/docs-shots`) is `fleet-config#93`.
- `CLAUDE.md` so AI coding agents (Claude Code, Cursor, Codex, etc.) can extend the project safely. `AGENTS.md` is a one-line pointer to it for non-Claude tools.
- `.fleet.toml` — this repo's card on the fleet architecture map. `fleet-config`'s `/system-map` aggregates every repo's `.fleet.toml`, so a cloned repo appears on the map automatically once you edit it. **After cloning, replace its values** with your repo's own. Schema: `fleet-config/architecture/README.md`.
- `docs/agents/` — the master AGENTS/CLAUDE templates, the adapt prompt, the rollout runbook, and the standalone `print()`→`logging` migration prompt. Single source of truth for the **project-shaped** agent instructions across all my repos (the universal dev-workflow directives live once in the machine config, `fleet-config/global-CLAUDE.md`).
- `docs/playwright-ui-testing.md` — didactic reference for the two-loop browser-testing recipe (headed agent verification + optional headless regression suite). Read this when bootstrapping on a fresh PC.
- `docs/shared-chrome-profile.md` — didactic reference for projects that drive real Chrome with a persistent profile: when two jobs share one profile, serialize access by waiting (never killing the holder). Read this before adding a second job on a shared profile.
- `docs/windows-tray.md` — didactic reference + canonical `tray.bat` shape for projects that ship a Windows tray owning a long-lived service: idempotent single-instance start, and an orphan-proof `--restart` that reclaims owned service ports by PID (scoped to the app's `.venv`, matched on CommandLine). Read this before writing or fixing a tray restart.
- `docs/app-onboarding.md` — didactic end-to-end playbook for standing up a new self-hosted PWA app from this scaffold: bootstrap the app, provision HTTPS (preferred: a real Let's Encrypt cert via `tailscale cert` for a tailnet app — `scripts/gen_tailscale_cert.py`, zero per-device trust; the self-signed-CA `certutil` + Chrome-restart + `/install-ca` mobileconfig dance only as the LAN-only fallback), and the iPhone/Android PWA install. Links to `docs/windows-tray.md` for the tray half. Read this when bringing up a new tray-resident webapp.

## Setup

```bash
cd E:\automation\project-scaffolding
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

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
  views/                    one render() per file (welcome, ...)
  tray/single_instance.py   vendor-verbatim named-mutex primitive for tray apps
  webapp/static/_vendored/  vendor-verbatim web-app UI components (nav/, icons/, card/, disclosure/, modal/, empty-state/, switch/, icon-tile/, button/, range-tab/, page-foot/, home-head/, select-native/ + demo.html gallery)
src/
  config.py                 paths + env-driven settings
  logger.py                 the elegant logger
  notify/                   vendor-verbatim Telegram notifier (send_text + factory/config)
  doc_capture/              vendor-verbatim doc-capture screenshot engine (manifest-driven, fail-safe-masked, input-hash-idempotent + README tour regen)
  pipelines/                one run() per file
data/                       input / output / logs (gitignored)
launch_app.{bat,sh}
launch_server.{bat,sh}
tray.bat.template           canonical tray launcher (copy + adapt for tray apps)
```

See `CLAUDE.md` for the cross-project agent conventions.

## Conventions

### Import rules

- `app/app.py` prepends the project root to `sys.path`, so `from src.X import Y` works everywhere downstream.
- UI code in `app/` imports from `src/`, **never the other way around**.
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
3. In-memory ring buffer that Streamlit views can render live via the `src.stream_to_streamlit` helper (runs the work on a background thread and streams its logs into a live panel; see `app/views/pipeline_runner.py` for the canonical usage) or one-shot via `src.render_log_panel`.

Do not configure root logging elsewhere — it is set up once in `src/logger.py` and is idempotent.

### Config

Read settings from `src/config.py`, not from `os.environ` directly. Add new keys there with a sensible default so the app boots without a `.env` file.

## Testing

Two layers, both under `tests/`:

- **Unit** (`tests/test_*.py`) — one file per `src/` module, hermetic. Runs in well under a second.
- **Headless e2e** (`tests/e2e/`) — `pytest-playwright` against a real browser. The `streamlit_app` session fixture (`tests/e2e/conftest.py`) **force-restarts Streamlit against the current code on disk** via `tests/_streamlit_lifecycle.py`, so the suite can never pass against a stale process. One example smoke test ships; expand per the regression-suite rules in `CLAUDE.md` ("End-to-end UI testing"). `tests/e2e/test_tray_lifecycle_behavior.py` is the odd one out — no browser, Windows-only, `pytest.mark.slow` — it drives the real `tray.bat.template` + the canonical `tray_lifecycle.ps1` (project-scaffolding#153: the ONE shared, machine-local copy owned by `fleet-config`, resolved via `_tray_harness.py`'s `resolve_tray_lifecycle_path()`) against a dummy stdlib HTTP(S) app through a real cold-start/restart/verify cycle (`project-scaffolding#152`); see `tests/e2e/_tray_harness.py` for the shared plumbing. `tests/e2e/test_geometry_helper.py` proves the vendor-verbatim rendered-geometry helper (`_geometry.py`, #157) against its hermetic twin fixtures — every check passes on the compliant twin and fails on the violating twin at all eight 320-772px × light/dark matrix legs (two-engine run needs a one-time `playwright install webkit`).

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

**Force-restart the dev Streamlit yourself** — the same thing the e2e fixture does, handy when an edit isn't showing up in the browser:

```powershell
& .\.venv\Scripts\python.exe -c "from tests._streamlit_lifecycle import ensure_fresh_streamlit; ensure_fresh_streamlit()"
```

### Verification gate

`scripts/verify-before-ship.ps1` is the one pass/fail pre-ship gate — run it before declaring any change done:

```powershell
& .\scripts\verify-before-ship.ps1
```

It sequences, fail-fast: **byte-compile** → **ruff** (whole repo) → **mypy `--strict`** (vendor-verbatim primitives only) → **pytest** (unit + e2e). Strictness lives in `pyproject.toml` (`[tool.ruff.lint]` adds `UP` to ruff's defaults; `[tool.mypy]` sets `strict = true`); the script only sequences the tools.

The mypy stage gates **vendor-verbatim primitives** — modules like `app/tray/single_instance.py` that consumers copy byte-identical and run through *their* `ruff` + `mypy --strict` gates. Gating them here means a canonical primitive can never ship lint- or type-dirty and redden every consumer's CI. When you add a new vendored primitive, append it to `$VendoredModules` in the script.

## Extending the scaffold

- **New view** → create `app/views/<name>.py` with `render()`, append `st.Page(<module>.render, title=..., icon=...)` to `nav_pages` inside `app/app.py`.
- **New pipeline** → create `src/pipelines/<name>.py` with `run(...)`, log via `get_logger("<name>")`.
- **New shared helper** → put it under `src/` and re-export from `src/__init__.py` if it is part of the public surface.
- **New dependency** → add to `requirements.txt` (follow the existing version-specifier style), then re-run `pip install -r requirements.txt` in `.venv`.

## What NOT to do

- Don't sprinkle `print()` for progress — use the logger.
- Don't import Streamlit inside `src/pipelines/*` or at the top of `src/logger.py`'s public path (the logger imports it lazily inside the Streamlit-only helpers, which is intentional).
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
