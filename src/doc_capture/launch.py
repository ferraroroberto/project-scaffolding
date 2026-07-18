"""Browser launch options for the doc-capture engine.

Deliberately NOT a stealth profile: doc capture drives the project's own
localhost app, so there is nothing to hide from — what matters is determinism
(identical pixels for identical inputs) and isolation (never touch a logged-in
scraping profile). The global "never re-inline launch args" rule protects the
*stealth* profile, which this deliberately is not (reasoning recorded in
content-management#110), so these values live here and the vendored component
stays self-contained. A project that already centralizes launch kwargs in a
``chrome_launch.py`` may re-export these instead of importing them directly.
"""

from __future__ import annotations

from typing import Any

# Injected into the page before every capture: kill animations, transitions
# and the text caret so two captures of the same state are byte-comparable.
DOC_CAPTURE_SETTLE_CSS = """
*, *::before, *::after {
    transition: none !important;
    animation: none !important;
    caret-color: transparent !important;
}
html { scroll-behavior: auto !important; }
"""


def doc_capture_launch_kwargs(*, headless: bool = True) -> dict[str, Any]:
    """Build the kwargs dict for ``pw.chromium.launch(**kwargs)``.

    Clean, **non-persistent** launch (no ``user_data_dir``): pair with
    ``browser.new_context(**doc_capture_context_kwargs())``. Real Chrome
    (``channel="chrome"``) so the rendering matches what the user sees;
    ``--force-color-profile=srgb`` + ``--hide-scrollbars`` remove the two
    remaining sources of pixel drift between machines/runs.
    """
    return {
        "channel": "chrome",
        "headless": headless,
        "args": [
            "--force-color-profile=srgb",
            "--hide-scrollbars",
            "--disable-features=Translate",
            "--no-default-browser-check",
            "--no-first-run",
            "--lang=en-US",
        ],
    }


def doc_capture_context_kwargs() -> dict[str, Any]:
    """Context options for the doc-capture browser: one fixed wide desktop
    viewport, fixed scale factor, forced light scheme + reduced motion,
    pinned locale/timezone."""
    return {
        "viewport": {"width": 1600, "height": 1000},
        "device_scale_factor": 1,
        "reduced_motion": "reduce",
        "color_scheme": "light",
        "locale": "en-US",
        "timezone_id": "UTC",
    }
