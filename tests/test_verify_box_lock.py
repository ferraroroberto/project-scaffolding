"""The pre-ship gate holds fleet-config's shared box load lock for its whole run.

A CPU-burn proof takes the lock exclusively, so a gate that skipped it could be
starved into browser timeouts by a burn that started mid-run. The lock block is
the vendor-verbatim component `scripts/box_lock_gate.ps1`, which the gate
dot-sources. The behaviour needs the fleet-config helper and a PowerShell host,
which a clone or CI runner may lack, so this pins the component's shape in its
text the way `test_vendored_catalog.py` pins the catalog derivation.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify-before-ship.ps1"
COMPONENT = REPO_ROOT / "scripts" / "box_lock_gate.ps1"
DOT_SOURCE = '. (Join-Path $PSScriptRoot "box_lock_gate.ps1"); Enter-BoxLockGate'


def _gate() -> str:
    return VERIFY_SCRIPT.read_text(encoding="utf-8")


def _component() -> str:
    return COMPONENT.read_text(encoding="utf-8")


def test_component_reruns_the_gate_under_the_shared_box_lock() -> None:
    text = _component()
    assert "box_lock.py" in text, "the component no longer reaches the box load lock helper"
    assert "run --mode shared" in text, "the gate must take the lock in shared mode, never exclusive"
    assert "-File $gate" in text, "the wrapper must re-run the gate script under the lock"
    assert "$MyInvocation.PSCommandPath" in text, "the gate script path must come from the dot-sourcing caller"
    assert 'VERIFY_BOX_LOCK_HELD -eq "1"' in text, "the inner run needs a guard or it re-wraps forever"
    assert "exit $lockExit" in text, "the gate must exit with the locked run's code"


def test_exit_lives_in_a_function_not_top_level_of_the_dot_sourced_file() -> None:
    """`exit` at the top of a dot-sourced file ends only that file, so the gate would run twice."""
    text = _component()
    assert "function Enter-BoxLockGate" in text
    assert text.index("function Enter-BoxLockGate") < text.index("exit $lockExit")


def test_missing_helper_warns_not_confirmed_and_runs_unlocked() -> None:
    text = _component()
    assert "Test-Path $helper" in text, "the wrapper must check the helper exists before using it"
    assert "[WARN] box load lock NOT CONFIRMED" in text, "a missing helper must be a loud warning, not silent"
    assert "box_lock.py not found" in text, "the warning must name the missing helper"


def test_lock_timeout_is_reported_as_its_own_failure() -> None:
    assert "$lockExit -eq 3" in _component(), "exit 3 (a burn held the lock) must not read as a gate failure"


def test_gate_dot_sources_the_component_before_any_stage_runs() -> None:
    """A stage that ran before the lock would sit outside it."""
    text = _gate()
    assert DOT_SOURCE in text, "the gate must dot-source scripts/box_lock_gate.ps1"
    assert text.index(DOT_SOURCE) < text.index("function Invoke-Stage"), "the lock must precede every stage"


def test_gate_no_longer_carries_its_own_lock_block() -> None:
    """One definition: a second inline copy is how the component and the gate drift."""
    text = _gate()
    assert "VERIFY_BOX_LOCK_HELD" not in text, "the gate must reach the lock only through the component"
    assert "Get-Process -Id $PID" not in text, "the gate must not re-run itself; the component does"
