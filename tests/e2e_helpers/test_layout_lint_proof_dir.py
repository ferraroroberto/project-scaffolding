"""The layout lint writes its proof images outside the checkout, never inside it.

A pure path check on `proof_dir()`, so it runs in the unit stage; the lint's
browser behaviour is pinned by `tests/e2e/test_layout_lint.py`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.e2e._layout_lint import proof_dir

_FIXTURES = Path(__file__).resolve().parents[1] / "e2e" / "fixtures" / "layout"


def test_proof_dir_defaults_outside_the_checkout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UI_PROOF_DIR", raising=False)
    assert not proof_dir().resolve().is_relative_to(_FIXTURES.parents[3])
    monkeypatch.setenv("UI_PROOF_DIR", str(_FIXTURES))
    with pytest.raises(ValueError, match="never go in a checkout"):
        proof_dir()
