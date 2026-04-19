"""
Pipeline Runner page
====================
Demonstrates the elegant logger: trigger a pipeline from the UI and
watch its output stream live into a panel while it also prints to the
terminal and is appended to ``data/logs/app.log``.
"""

from __future__ import annotations

import threading
import time

import streamlit as st

from src import clear_log_buffer, get_log_buffer, get_logger
from src.pipelines import example_pipeline

log = get_logger("ui.pipeline_runner")


def _run_in_thread(steps: int, fail_chance: float, done: threading.Event) -> None:
    try:
        example_pipeline.run(steps=steps, fail_chance=fail_chance)
    except Exception:
        log.exception("Pipeline crashed")
    finally:
        done.set()


def render() -> None:
    st.header("Pipeline Runner")
    st.caption(
        "Runs a sample pipeline.  Logs appear here, in your terminal, and in "
        "`data/logs/app.log` — all from a single `log.info(...)` call."
    )

    col1, col2 = st.columns(2)
    with col1:
        steps = st.slider("Steps", 5, 40, 12)
    with col2:
        fail_pct = st.slider("Warning probability (%)", 0, 50, 10)

    if st.button("Run pipeline", type="primary"):
        clear_log_buffer()
        log.info("UI: triggering pipeline (steps=%d, warn%%=%d)", steps, fail_pct)

        placeholder = st.empty()
        done = threading.Event()
        start = len(get_log_buffer())

        thread = threading.Thread(
            target=_run_in_thread,
            args=(steps, fail_pct / 100, done),
            daemon=True,
        )
        thread.start()

        # Live refresh loop — repaint the panel until the pipeline ends.
        while not done.is_set():
            lines = get_log_buffer()[start:]
            with placeholder.container():
                st.markdown("**Live log**")
                st.code("\n".join(lines) if lines else "(starting...)", language="log")
            time.sleep(0.25)

        lines = get_log_buffer()[start:]
        with placeholder.container():
            st.markdown("**Live log**")
            st.code("\n".join(lines) if lines else "(no output)", language="log")

        st.success("Pipeline finished")

    with st.expander("How the logger works"):
        st.markdown(
            """
            - `from src import get_logger` returns a stdlib `logging.Logger`
              wired to three handlers: colored terminal, rotating file,
              and an in-memory ring buffer.
            - The page polls that ring buffer ~4×/s while the pipeline
              runs in a background thread.
            - For console-only scripts, just call `get_logger(...)` and
              log normally — no Streamlit dependency triggered.
            """
        )
