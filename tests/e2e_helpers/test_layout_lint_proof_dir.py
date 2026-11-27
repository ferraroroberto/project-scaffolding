"""The layout lint's files: proof images stay outside the checkout, and the manifest is never lost.

Pure file checks on `proof_dir()` and the manifest merge, so they run in the unit
stage; the lint's browser behaviour is pinned by `tests/e2e/test_harness_helpers.py`.
"""

from __future__ import annotations

import codecs
import json
from pathlib import Path

import pytest

from tests.e2e._layout_lint import CaptureEntry, _write_manifest, proof_dir

_FIXTURES = Path(__file__).resolve().parents[1] / "e2e" / "fixtures" / "layout"


def test_proof_dir_defaults_outside_the_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UI_PROOF_DIR", raising=False)
    assert not proof_dir().resolve().is_relative_to(_FIXTURES.parents[3])
    monkeypatch.setenv("UI_PROOF_DIR", str(_FIXTURES))
    with pytest.raises(ValueError, match="never go in a checkout"):
        proof_dir()


def _leg(state: str) -> CaptureEntry:
    return CaptureEntry(state=state, viewport="phone", theme="light", screenshot=f"{state}.png", ms=1, findings=())


@pytest.mark.parametrize("bom", [b"", codecs.BOM_UTF8])
def test_manifest_merge_keeps_the_earlier_legs_with_or_without_a_bom(tmp_path: Path, bom: bytes) -> None:
    path = tmp_path / "manifest.json"
    _write_manifest(path, [_leg("first")])
    path.write_bytes(bom + path.read_bytes())
    _write_manifest(path, [_leg("second")])
    assert [e["state"] for e in json.loads(path.read_text(encoding="utf-8"))["entries"]] == ["first", "second"]


@pytest.mark.parametrize("content", [b"{not json", b"[]", b'{"other": 1}'])
def test_a_manifest_that_does_not_parse_is_reported_and_left_untouched(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, content: bytes
) -> None:
    path = tmp_path / "manifest.json"
    path.write_bytes(content)
    with pytest.raises(ValueError, match="left untouched"):
        _write_manifest(path, [_leg("second")])
    assert path.read_bytes() == content
    assert "manifest.json" in caplog.text
