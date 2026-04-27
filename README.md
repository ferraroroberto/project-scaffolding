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
- `CLAUDE.md` so AI coding agents (Claude Code, Cursor, Codex, etc.) can extend the project safely. `AGENTS.md` is a one-line pointer to it for non-Claude tools.
- `docs/agents/` — the master AGENTS/CLAUDE templates, the adapt prompt, the rollout runbook, and the standalone `print()`→`logging` migration prompt. Single source of truth for agent instructions across all my repos.

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
src/
  config.py                 paths + env-driven settings
  logger.py                 the elegant logger
  pipelines/                one run() per file
data/                       input / output / logs (gitignored)
launch_app.{bat,sh}
launch_server.{bat,sh}
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
3. In-memory ring buffer that Streamlit views can render live (see `app/views/pipeline_runner.py` for the threaded refresh pattern, and `src.stream_to_streamlit` / `src.render_log_panel` helpers).

Do not configure root logging elsewhere — it is set up once in `src/logger.py` and is idempotent.

### Config

Read settings from `src/config.py`, not from `os.environ` directly. Add new keys there with a sensible default so the app boots without a `.env` file.

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
