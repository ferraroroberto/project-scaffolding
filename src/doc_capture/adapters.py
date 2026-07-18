"""Reach adapters — the app-shape-specific half of the doc-capture engine.

The engine core (manifest, hashing, planning, README regen) is app-shape
agnostic; everything that knows *how to drive a page to a feature* lives here,
behind one small interface. Two shapes ship:

* ``streamlit`` (default) — the pilot's proven adapter
  (content-management#110): Streamlit-aware settle, sidebar collapse verified
  by visibility at shot time (falls back to masking the whole sidebar),
  segmented-control section clicks via ``reach.label``, ``reach.expand`` for
  collapsed expanders (hidden expander content keeps DOM boxes, so its masks
  would paint over unrelated visible UI).
* ``url`` — the FastAPI + static-PWA shape: navigate to ``reach.path``
  relative to the base URL, then honor the same ``wait`` contract.

The app declares its shape once in the manifest (``app.kind``); per-feature
``reach``/``wait`` fields are adapter-specific and documented in this
package's README.
"""

from __future__ import annotations

import logging
from typing import Any

from .launch import DOC_CAPTURE_SETTLE_CSS

logger = logging.getLogger(__name__)


class ReachAdapter:
    """Drives a fresh page to one feature's capturable state.

    ``open`` owns the whole page choreography — navigate, wait for readiness,
    inject the settle CSS, honor the entry's ``reach``/``wait`` config — and
    returns any *extra* mask selectors the adapter wants painted over
    (fail-safe fallbacks, e.g. a sidebar that would not collapse). The engine
    owns everything around it: preflight, browser lifecycle, masking,
    screenshotting, manifest metadata.
    """

    def open(self, page: Any, base_url: str, name: str, entry: dict[str, Any]) -> list[str]:
        raise NotImplementedError


def _wait_common(page: Any, entry: dict[str, Any]) -> None:
    """The adapter-independent half of the ``wait`` contract."""
    wait = entry.get("wait") or {}
    if wait.get("selector"):
        page.wait_for_selector(wait["selector"], timeout=30_000)
    if wait.get("text"):
        page.get_by_text(wait["text"]).first.wait_for(timeout=30_000)


class UrlAdapter(ReachAdapter):
    """Route-addressed apps (FastAPI + static PWA): every feature is a URL."""

    def open(self, page: Any, base_url: str, name: str, entry: dict[str, Any]) -> list[str]:
        reach = entry.get("reach") or {}
        path = reach.get("path") or "/"
        if not path.startswith("/"):
            path = "/" + path
        page.goto(base_url.rstrip("/") + path, wait_until="load", timeout=60_000)
        page.add_style_tag(content=DOC_CAPTURE_SETTLE_CSS)
        _wait_common(page, entry)
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: BLE001 — a polling page keeps the wire warm
            pass
        page.wait_for_timeout(1_200)
        return []


# Streamlit shell readiness — present in every Streamlit app regardless of its
# navigation style, unlike the segmented-control router below.
_APP_SHELL = '[data-testid="stAppViewContainer"]'

# Streamlit 1.57 renders st.segmented_control as a stButtonGroup of
# stBaseButton-segmented_control[Active] buttons — there is no
# "stSegmentedControl" testid.
_SECTION_ROUTER = '[data-testid="stButtonGroup"]'
_SECTION_BUTTON = 'button[data-testid^="stBaseButton-segmented_control"]'


class StreamlitAdapter(ReachAdapter):
    """The pilot's proven Streamlit adapter (content-management#110)."""

    def open(self, page: Any, base_url: str, name: str, entry: dict[str, Any]) -> list[str]:
        page.goto(base_url, wait_until="load", timeout=60_000)
        page.wait_for_selector(_APP_SHELL, timeout=30_000)
        page.add_style_tag(content=DOC_CAPTURE_SETTLE_CSS)
        # Settle BEFORE touching the sidebar: mid-hydration the sidebar can
        # transiently report collapsed (aria-expanded="false") and then expand,
        # which would silently skip both the collapse and the fail-safe mask.
        self._wait_settled(page)
        self._collapse_sidebar(page)
        self._reach_feature(page, entry)
        # Verify at shot time, by visibility — the only signal the screenshot
        # itself honors. Still visible (collapse failed, control missing, or a
        # rerun re-expanded it) → mask the whole sidebar. Fail-safe either way.
        if self._sidebar_visible(page):
            logger.warning(
                "⚠️ %s: sidebar still visible at capture time — masking the whole sidebar",
                name,
            )
            return ['section[data-testid="stSidebar"]']
        return []

    @staticmethod
    def _wait_settled(page: Any) -> None:
        """Wait for Streamlit to finish its rerun: the status widget
        ("Running…") goes away, the wire goes quiet, plus a settle beat."""
        try:
            page.locator('[data-testid="stStatusWidget"]').first.wait_for(state="hidden", timeout=15_000)
        except Exception:  # noqa: BLE001 — widget may never have appeared; that's settled too
            pass
        try:
            page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:  # noqa: BLE001 — an autorefreshing log panel keeps the wire warm
            pass
        page.wait_for_timeout(1_200)

    @staticmethod
    def _sidebar_visible(page: Any) -> bool:
        """Visibility, not aria-expanded, is the truth here — the attribute can
        lie mid-hydration, but the screenshot shows exactly what is visible.
        Any uncertainty reads as visible, which routes to masking (fail-safe)."""
        try:
            sidebar = page.locator('section[data-testid="stSidebar"]')
            return bool(sidebar.count() > 0 and sidebar.first.is_visible())
        except Exception:  # noqa: BLE001
            return True

    def _collapse_sidebar(self, page: Any) -> bool:
        """Collapse the sidebar (typically live status — all volatile).
        Returns False when it could not be confirmed collapsed; ``open``
        re-verifies visibility at shot time regardless."""
        try:
            # Already collapsed (Streamlit remembers the state per browser
            # session, so pages after the first start collapsed) — nothing to do.
            if not self._sidebar_visible(page):
                return True
            btn = page.locator('[data-testid="stSidebarCollapseButton"] button')
            if btn.count() == 0:
                return False
            # The control is hover-revealed; a forced click on the hidden button
            # dispatches but doesn't collapse. Hover first, click for real.
            page.locator('[data-testid="stSidebarHeader"]').hover()
            btn.first.click()
            page.wait_for_timeout(600)
            return not self._sidebar_visible(page)
        except Exception:  # noqa: BLE001 — any uncertainty falls back to masking
            return False

    def _reach_feature(self, page: Any, entry: dict[str, Any]) -> None:
        reach = entry.get("reach") or {}
        label = reach.get("label")
        # click: false → the app's default section; clicking the already-selected
        # segmented-control option would deselect it (blank pill in the shot).
        if label and reach.get("click", True):
            page.wait_for_selector(_SECTION_ROUTER, timeout=30_000)
            # .first = the top-level section router (a tab may render its own
            # nested segmented control below it).
            page.locator(_SECTION_ROUTER).first.locator(_SECTION_BUTTON).filter(
                has_text=label
            ).click()
        _wait_common(page, entry)
        # Open any expanders named in reach.expand: content hidden in a collapsed
        # expander still occupies DOM boxes, so its masks would paint gray blocks
        # over unrelated visible UI. Expanding renders (and masks) it in place.
        for exp_label in reach.get("expand", []):
            page.locator('[data-testid="stExpander"]').filter(has_text=exp_label).first.locator(
                "summary"
            ).click()
            page.wait_for_timeout(800)
        self._wait_settled(page)


ADAPTERS: dict[str, type[ReachAdapter]] = {
    "streamlit": StreamlitAdapter,
    "url": UrlAdapter,
}


def resolve_adapter(manifest: dict[str, Any]) -> ReachAdapter:
    """Instantiate the adapter the manifest's ``app.kind`` names.

    Defaults to ``streamlit`` (the pilot shape) so a pre-``kind`` manifest
    keeps working unchanged. An unknown kind fails loud before any browser
    starts.
    """
    kind = (manifest.get("app") or {}).get("kind") or "streamlit"
    adapter_cls = ADAPTERS.get(kind)
    if adapter_cls is None:
        raise SystemExit(
            f"❌ unknown app.kind {kind!r} in the manifest — known kinds: "
            f"{', '.join(sorted(ADAPTERS))}"
        )
    return adapter_cls()
