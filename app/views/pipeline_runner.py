"""
Pipeline Runner page
====================
Demonstrates the elegant logger: trigger a pipeline from the UI and
watch its output stream live into a panel while it also prints to the
terminal and is appended to ``data/logs/app.log``.
"""

from __future__ import annotations

import streamlit as st

from src import clear_log_buffer, get_logger, stream_to_streamlit
from src.pipelines import example_pipeline

log = get_logger("ui.pipeline_runner")


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

        # The helper runs the pipeline on a background thread and streams its
        # log output into a live panel — one canonical live-panel implementation.
        try:
            stream_to_streamlit(
                lambda: example_pipeline.run(steps=steps, fail_chance=fail_pct / 100)
            )
        except Exception:
            log.exception("Pipeline crashed")
            st.error("Pipeline crashed — see the log panel above.")
        else:
            st.success("Pipeline finished")

    with st.expander("How the logger works"):
        st.markdown(
            """
            - `from src import get_logger` returns a stdlib `logging.Logger`
              wired to three handlers: colored terminal, rotating file,
              and an in-memory ring buffer.
            - `stream_to_streamlit(...)` runs the pipeline on a background
              thread and polls that ring buffer ~4×/s to refresh the panel.
            - For console-only scripts, just call `get_logger(...)` and
              log normally — no Streamlit dependency triggered.
            """
        )
