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
- `AGENTS.md` so AI coding agents can extend the project safely.

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

See `AGENTS.md` for the full conventions.

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
