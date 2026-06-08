"""Session fixtures for the headless e2e regression suite.

`streamlit_app` force-restarts Streamlit against the current code on disk
(see `tests/_streamlit_lifecycle.py`) so the suite can never pass against a
stale process. `pytest-playwright` supplies the `page` fixture.

The webapp uses no TLS locally, so no `browser_context_args` override is
needed — unlike a self-signed-cert project, which would add
`ignore_https_errors` here.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from tests._streamlit_lifecycle import (
    STREAMLIT_E2E_PORT,
    ensure_fresh_streamlit,
    kill_streamlit_on_port,
)


@pytest.fixture(scope="session")
def streamlit_app() -> Iterator[str]:
    """Boot a fresh Streamlit for the whole pytest session; kill it after."""
    base_url = ensure_fresh_streamlit(STREAMLIT_E2E_PORT)
    try:
        yield base_url
    finally:
        kill_streamlit_on_port(STREAMLIT_E2E_PORT)
