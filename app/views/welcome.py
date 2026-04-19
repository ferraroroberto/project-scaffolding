"""Welcome / landing view."""

import streamlit as st

from src.config import APP_NAME


def render() -> None:
    st.title(f"👋 Welcome to {APP_NAME}")
    st.markdown(
        """
        Starter template for **Streamlit app + Python pipelines** projects.

        ### Layout
        - **`app/`** — Streamlit UI: entry point, views, theme.
        - **`src/`** — non-UI Python: logger, config, pipelines.
        - **`data/`** — working directory (`input/`, `output/`, `logs/`).

        ### Try it
        Open the **⚙ Pipeline Runner** view from the sidebar.  You'll
        see the elegant logger in action — the same lines stream
        simultaneously to:

        1. the **terminal** (color-coded by level),
        2. a **rotating file** at `data/logs/app.log`,
        3. a **live panel** right inside this UI.

        All from a single `log.info(...)` call in your pipeline code.

        ### Extend
        - New view → drop `app/views/<name>.py` with a `render()` function and register it in `app.py`'s `VIEWS` list.
        - New pipeline → drop `src/pipelines/<name>.py` with `run(**kwargs)`.
        - New shared helper → put it in `src/`.

        See `AGENTS.md` for the full conventions.
        """
    )
