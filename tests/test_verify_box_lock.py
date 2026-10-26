"""The pre-ship gate holds fleet-config's shared box load lock for its whole run.

A CPU-burn proof takes the lock exclusively, so a gate that skipped it could be
starved into browser timeouts by a burn that started mid-run. The behaviour
needs the fleet-config helper and a PowerShell host, which a clone or CI runner
may lack, so this pins the wrapper's shape in the script text the way
`test_vendored_catalog.py` pins the catalog derivation.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify-before-ship.ps1"


def _script() -> str:
    return VERIFY_SCRIPT.read_text(encoding="utf-8")


def test_gate_reruns_itself_under_the_shared_box_lock() -> None:
    text = _script()
    assert "box_lock.py" in text, "verify-before-ship.ps1 no longer reaches the box load lock helper"
    assert "run --mode shared" in text, "the gate must take the lock in shared mode, never exclusive"
    assert "-File $PSCommandPath" in text, "the wrapper must re-run this same script under the lock"
    assert 'VERIFY_BOX_LOCK_HELD -ne "1"' in text, "the inner run needs a guard or it re-wraps forever"


def test_missing_helper_warns_and_runs_unlocked() -> None:
    text = _script()
    assert "Test-Path $boxLock" in text, "the wrapper must check the helper exists before using it"
    assert "[WARN] box_lock.py not found" in text, "a missing helper must be a loud warning, not silent"


def test_lock_is_taken_before_any_stage_runs() -> None:
    """A stage that ran before the wrapper would sit outside the lock."""
    text = _script()
    wrapper = text.index("& $py $boxLock run --mode shared")
    assert wrapper < text.index("function Invoke-Stage"), "the lock wrapper must precede every stage"
