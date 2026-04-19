# AGENTS.md

Guidance for AI coding agents (Claude Code, Cursor, etc.) working in
this repository.  Humans, see `README.md`.

## What this repo is

A **starter template** to clone when bootstrapping a new internal tool
that needs:

- a Streamlit UI (multi-page, sidebar navigation),
- one or more **Python pipelines** (ETL / scraping / analysis / batch
  jobs),
- consistent logging across UI and CLI runs,
- one-click local launch and a one-click "share via tunnel" launch.

It is intentionally minimal.  Add only what the new project needs.

## Layout

```
app/                    UI-only code (Streamlit)
  .streamlit/
    config.toml         theme + server defaults (dark theme by default)
  app.py                Streamlit entry point: page config,
                        st.navigation + light/dark toggle in sidebar
  views/                Each module exposes render() -> None
    welcome.py          Landing view — what this scaffold gives you
    pipeline_runner.py  Reference view: drives a pipeline + live log

src/                    All non-UI Python code lives here
  __init__.py           Re-exports the public logger API
  config.py             Paths + env-driven settings (single source of truth)
  logger.py             The elegant logger (terminal + file + Streamlit live)
  pipelines/
    example_pipeline.py Each pipeline exposes run(**kwargs) -> dict

data/
  input/  output/  logs/    Working directory; contents gitignored

launch_app.bat / .sh        Local launch (browser opens automatically)
launch_server.bat / .sh     Local + Cloudflare Tunnel for public sharing
requirements.txt
```

## Import rules

- `app/app.py` prepends the project root to `sys.path` so `from src.X
  import Y` works everywhere downstream.
- UI code (`app/`) imports from `src/`, never the other way around.
- Views can import siblings as top-level modules (`from views import
  welcome`) because Streamlit puts `app/` on `sys.path` when it runs
  `app/app.py`.
- The directory is named `views/` (not `pages/`) on purpose: Streamlit
  auto-discovers any subdirectory called `pages/` and adds it to the
  sidebar, which would duplicate the navigation built in `app.py`.
- Pipelines run standalone with `python -m src.pipelines.<name>` —
  they must not import from `app/`.

## Conventions

### Views

- File per view in `app/views/`.  Always export `def render() -> None`.
- Register the view in `app/app.py` by appending an `st.Page` entry
  to the `nav_pages` list (Streamlit's native multipage navigation
  renders the sidebar entries automatically).
- `app/app.py` itself only configures the page, renders the sidebar
  (light/dark toggle) and hands off to `st.navigation` — it does not
  draw view content directly.  The landing view is
  `app/views/welcome.py` (registered with `default=True`).
- A view should orchestrate; **business logic lives in `src/`** so it
  can be reused from the CLI or tests.

### Pipelines

- File per pipeline in `src/pipelines/`.  Always export
  `def run(**kwargs)`.
- Pipelines must **never** call `print()` or `st.*`.  They emit
  progress through the logger so they work the same way from the UI,
  the CLI, and tests.
- Return a small JSON-serialisable summary dict (counts, timings,
  output paths).  The UI / caller decides how to display it.

### Logging

```python
from src import get_logger

log = get_logger("my_pipeline")
log.info("Loading %d rows", len(rows))
log.warning("Skipping malformed row id=%s", row.id)
log.error("Upload failed", exc_info=True)
```

One call → three sinks:

1. Colored terminal output (level-tinted, timestamped).
2. Rotating file at `data/logs/app.log` (1 MB × 3 backups).
3. In-memory ring buffer that Streamlit views can render live (see
   `app/views/pipeline_runner.py` for the threaded refresh pattern,
   and `src.stream_to_streamlit` / `src.render_log_panel` helpers).

Do not configure root logging elsewhere — it is set up once in
`src/logger.py` and is idempotent.

### Config

Read settings from `src/config.py`, not from `os.environ` directly.
Add new keys there with a sensible default so the app boots without a
`.env` file.

### Streamlit theme

Two themes, two mechanisms — this split is intentional, see
README → *Theming* for the full rationale.

- **Dark (default)** lives in `app/.streamlit/config.toml` — Streamlit's
  native theme mechanism. Tweak the palette there. Read once at
  startup, so it can't be toggled at runtime.
- **Light (toggle)** lives in `app/styles/light.css` — a plain
  stylesheet injected at runtime by `_inject_css("light.css")` in
  `app/app.py` when the sidebar toggle is on. Edit the file directly
  with full CSS editor support.
- **Do not** inline CSS strings inside `app.py`. Drop new `.css` files
  in `app/styles/` and call `_inject_css(filename)`.
- Selectors rely on Streamlit's `data-testid` and BaseWeb's
  `data-baseweb` attributes — stable in practice but not a public API.
  Re-verify after major Streamlit upgrades.

## When extending the scaffold

- New view → create `app/views/<name>.py` with `render()`, append an
  `st.Page(<module>.render, title=..., icon=...)` to `nav_pages`
  inside `app/app.py`.
- New pipeline → create `src/pipelines/<name>.py` with `run(...)`,
  log via `get_logger("<name>")`.
- New shared helper → put it under `src/` and re-export from
  `src/__init__.py` if it is part of the public surface.
- New dependency → pin in `requirements.txt`, then re-run
  `pip install -r requirements.txt` in `.venv`.

## What NOT to do

- Don't sprinkle `print()` for progress — use the logger.
- Don't import Streamlit inside `src/pipelines/*` or at the top of
  `src/logger.py`'s public path (the logger imports it lazily inside
  the Streamlit-only helpers, which is intentional).
- Don't hardcode paths.  Build them off `src.config.ROOT_DIR`,
  `INPUT_DIR`, `OUTPUT_DIR`, `LOG_DIR`.
- Don't add per-project files to this scaffold itself.  Clone it,
  rename, and customise downstream.

## Running

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt

# Local app (browser opens):
launch_app.bat                  # Windows
./launch_app.sh                 # macOS / Linux

# Share via Cloudflare Tunnel:
launch_server.bat               # Windows
./launch_server.sh              # macOS / Linux
```

Pipelines can also be run standalone:

```bash
python -m src.pipelines.example_pipeline
```
