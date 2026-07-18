"""Unit tests for the doc-capture engine's browserless logic (#171).

Covers the contract guarantees that travel with the vendored component:
* fail-safe masking — an entry without mask selectors is refused, never captured;
* input-hash idempotency — unchanged sources skip, changed sources recapture;
* README regeneration — deterministic block between markers, no-op on rerun;
* reach-adapter dispatch — manifest ``app.kind`` selects the adapter, unknown
  kinds fail loud, and the ``url`` adapter honors the reach/wait contract.

Run: & .\\.venv\\Scripts\\python.exe -m pytest tests/test_doc_capture.py -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.doc_capture import adapters, engine


def _manifest(features: dict[str, Any]) -> dict[str, Any]:
    return {"app": {"base_url": "http://localhost:8501"}, "features": features}


def _entry(**overrides: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "title": "📊 Reporting",
        "description": "Daily numbers pipeline.",
        "source_globs": ["app/tab_reporting.py"],
        "reach": {"label": "📊 reporting"},
        "wait": {"text": "daily numbers"},
        "mask": ['[data-testid="stCode"]'],
        "input_hash": None,
        "captured_at": None,
        "files": [],
    }
    entry.update(overrides)
    return entry


class PlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "app").mkdir()
        (self.root / "app" / "tab_reporting.py").write_text("print('v1')\n", encoding="utf-8")

    def _plan(self, manifest: dict[str, Any], **kwargs: Any) -> list[engine.PlanItem]:
        return engine.plan_features(manifest, repo_root=self.root, **kwargs)

    def test_missing_mask_is_refused(self) -> None:
        entry = _entry()
        del entry["mask"]
        with self.assertLogs(engine.logger, level="WARNING"):
            items = self._plan(_manifest({"reporting": entry}))
        self.assertEqual(items[0].action, engine.ACTION_SKIP_UNMASKED)

    def test_empty_mask_is_refused(self) -> None:
        with self.assertLogs(engine.logger, level="WARNING"):
            items = self._plan(_manifest({"reporting": _entry(mask=[])}))
        self.assertEqual(items[0].action, engine.ACTION_SKIP_UNMASKED)

    def test_unmasked_is_refused_even_with_force(self) -> None:
        with self.assertLogs(engine.logger, level="WARNING"):
            items = self._plan(_manifest({"reporting": _entry(mask=[])}), force=True)
        self.assertEqual(items[0].action, engine.ACTION_SKIP_UNMASKED)

    def test_never_captured_gets_captured(self) -> None:
        items = self._plan(_manifest({"reporting": _entry()}))
        self.assertEqual(items[0].action, engine.ACTION_CAPTURE)
        self.assertIsNotNone(items[0].new_hash)

    def test_unchanged_input_skips(self) -> None:
        entry = _entry()
        entry["input_hash"] = engine.compute_input_hash(entry, self.root)
        out = engine.screenshot_path("reporting", self.root)
        out.parent.mkdir(parents=True)
        out.write_bytes(b"png")
        items = self._plan(_manifest({"reporting": entry}))
        self.assertEqual(items[0].action, engine.ACTION_SKIP_UNCHANGED)

    def test_changed_source_recaptures(self) -> None:
        entry = _entry()
        entry["input_hash"] = engine.compute_input_hash(entry, self.root)
        out = engine.screenshot_path("reporting", self.root)
        out.parent.mkdir(parents=True)
        out.write_bytes(b"png")
        (self.root / "app" / "tab_reporting.py").write_text("print('v2')\n", encoding="utf-8")
        items = self._plan(_manifest({"reporting": entry}))
        self.assertEqual(items[0].action, engine.ACTION_CAPTURE)

    def test_missing_png_recaptures_despite_matching_hash(self) -> None:
        entry = _entry()
        entry["input_hash"] = engine.compute_input_hash(entry, self.root)
        items = self._plan(_manifest({"reporting": entry}))
        self.assertEqual(items[0].action, engine.ACTION_CAPTURE)

    def test_force_recaptures_unchanged(self) -> None:
        entry = _entry()
        entry["input_hash"] = engine.compute_input_hash(entry, self.root)
        out = engine.screenshot_path("reporting", self.root)
        out.parent.mkdir(parents=True)
        out.write_bytes(b"png")
        items = self._plan(_manifest({"reporting": entry}), force=True)
        self.assertEqual(items[0].action, engine.ACTION_CAPTURE)

    def test_mask_change_recaptures(self) -> None:
        entry = _entry()
        entry["input_hash"] = engine.compute_input_hash(entry, self.root)
        out = engine.screenshot_path("reporting", self.root)
        out.parent.mkdir(parents=True)
        out.write_bytes(b"png")
        entry["mask"] = ['[data-testid="stCode"]', '[data-testid="stMetric"]']
        items = self._plan(_manifest({"reporting": entry}))
        self.assertEqual(items[0].action, engine.ACTION_CAPTURE)

    def test_only_filters_features(self) -> None:
        manifest = _manifest({"reporting": _entry(), "planning": _entry(source_globs=[])})
        items = self._plan(manifest, only=["planning"])
        self.assertEqual([i.name for i in items], ["planning"])

    def test_capture_features_never_shoots_unmasked(self) -> None:
        # Belt and suspenders: even a hand-built unmasked "capture" list can't
        # reach a browser, because capture_features only acts on plan items.
        with self.assertLogs(engine.logger, level="WARNING"):
            items = self._plan(_manifest({"reporting": _entry(mask=[])}))
        captured = engine.capture_features(
            _manifest({"reporting": _entry(mask=[])}), items, repo_root=self.root
        )
        self.assertEqual(captured, 0)


class ReadmeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.readme = Path(self._tmp.name) / "README.md"
        self.readme.write_text(
            "# Title\n\nintro\n\n<!-- docs-shots:start -->\nstale\n<!-- docs-shots:end -->\n\ntail\n",
            encoding="utf-8",
        )

    def test_regenerates_between_markers_and_is_idempotent(self) -> None:
        entry = _entry(files=["docs/screenshots/reporting-desktop.png"])
        manifest = _manifest({"reporting": entry})
        self.assertTrue(engine.regenerate_readme(manifest, self.readme))
        text = self.readme.read_text(encoding="utf-8")
        self.assertIn("### 📊 Reporting", text)
        self.assertIn("Daily numbers pipeline.", text)
        self.assertIn("![📊 Reporting screenshot](docs/screenshots/reporting-desktop.png)", text)
        self.assertNotIn("stale", text)
        self.assertTrue(text.startswith("# Title\n\nintro\n\n"))
        self.assertTrue(text.endswith("<!-- docs-shots:end -->\n\ntail\n"))
        # Rerun with the same manifest → no-op.
        self.assertFalse(engine.regenerate_readme(manifest, self.readme))

    def test_uncaptured_feature_is_omitted(self) -> None:
        manifest = _manifest({"reporting": _entry(files=[])})
        with self.assertLogs(engine.logger, level="WARNING"):
            engine.regenerate_readme(manifest, self.readme)
        self.assertNotIn("### 📊 Reporting", self.readme.read_text(encoding="utf-8"))

    def test_missing_markers_fails_loud(self) -> None:
        self.readme.write_text("# no markers\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            engine.regenerate_readme(_manifest({"reporting": _entry()}), self.readme)


class _FakeLocator:
    @property
    def first(self) -> _FakeLocator:
        return self

    def wait_for(self, **kwargs: Any) -> None:
        pass


class _FakePage:
    """Records the url adapter's page choreography — no browser involved."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []

    def goto(self, url: str, **kwargs: Any) -> None:
        self.calls.append(("goto", url))

    def add_style_tag(self, content: str = "") -> None:
        self.calls.append(("style", None))

    def wait_for_selector(self, selector: str, **kwargs: Any) -> None:
        self.calls.append(("wait_selector", selector))

    def get_by_text(self, text: str) -> _FakeLocator:
        self.calls.append(("wait_text", text))
        return _FakeLocator()

    def wait_for_load_state(self, state: str, **kwargs: Any) -> None:
        self.calls.append(("load_state", state))

    def wait_for_timeout(self, ms: int) -> None:
        pass


class AdapterTests(unittest.TestCase):
    def test_default_kind_is_streamlit(self) -> None:
        self.assertIsInstance(
            adapters.resolve_adapter({"features": {}}), adapters.StreamlitAdapter
        )

    def test_kind_url_resolves_url_adapter(self) -> None:
        manifest = {"app": {"kind": "url"}, "features": {}}
        self.assertIsInstance(adapters.resolve_adapter(manifest), adapters.UrlAdapter)

    def test_unknown_kind_fails_loud(self) -> None:
        with self.assertRaises(SystemExit):
            adapters.resolve_adapter({"app": {"kind": "electron"}, "features": {}})

    def test_url_adapter_navigates_to_reach_path(self) -> None:
        page = _FakePage()
        entry = _entry(reach={"path": "/settings"}, wait={"selector": "main.app"})
        adapters.UrlAdapter().open(page, "http://localhost:8000/", "settings", entry)
        self.assertIn(("goto", "http://localhost:8000/settings"), page.calls)
        self.assertIn(("wait_selector", "main.app"), page.calls)

    def test_url_adapter_defaults_to_root_and_normalizes_path(self) -> None:
        page = _FakePage()
        adapters.UrlAdapter().open(page, "http://localhost:8000", "home", _entry(reach={}))
        self.assertIn(("goto", "http://localhost:8000/"), page.calls)
        page2 = _FakePage()
        adapters.UrlAdapter().open(
            page2, "http://localhost:8000", "home", _entry(reach={"path": "settings"})
        )
        self.assertIn(("goto", "http://localhost:8000/settings"), page2.calls)

    def test_url_adapter_honors_wait_text(self) -> None:
        page = _FakePage()
        entry = _entry(reach={"path": "/"}, wait={"text": "Build:"})
        adapters.UrlAdapter().open(page, "http://localhost:8000", "home", entry)
        self.assertIn(("wait_text", "Build:"), page.calls)


if __name__ == "__main__":
    unittest.main()
