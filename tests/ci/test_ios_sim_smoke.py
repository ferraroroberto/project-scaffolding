"""`scripts/ci/ios_sim_smoke.py`: device choice, view names and the adopter contract.

The simulator itself only exists on the Mac, so these cover the parts that
decide what runs there: which iPhone is picked, what a missing prerequisite
reports (unknown, exit 3, never a pass), and how the adopter's throwaway
instance is found.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import ios_sim_smoke as smoke  # noqa: E402 -- needs the sys.path line above

_RT = "com.apple.CoreSimulator.SimRuntime."


def _dev(name: str, udid: str, state: str = "Shutdown", available: bool = True) -> dict:
    return {"name": name, "udid": udid, "state": state, "isAvailable": available}


def test_picks_an_iphone_on_the_newest_runtime() -> None:
    listing = {"devices": {
        _RT + "iOS-17-5": [_dev("iPhone 15", "old")],
        _RT + "iOS-18-2": [_dev("iPad Air", "ipad"), _dev("iPhone 16", "new")],
        _RT + "watchOS-11-0": [_dev("Apple Watch", "watch")],
    }}
    assert smoke.pick_device(listing) == ("new", "iPhone 16")


def test_a_booted_iphone_on_the_newest_runtime_is_reused() -> None:
    listing = {"devices": {_RT + "iOS-18-2": [
        _dev("iPhone 16", "cold"), _dev("iPhone 16 Pro", "warm", state="Booted"),
    ]}}
    assert smoke.pick_device(listing) == ("warm", "iPhone 16 Pro")


def test_minor_versions_compare_numerically() -> None:
    listing = {"devices": {
        _RT + "iOS-18-10": [_dev("iPhone 16", "ten")],
        _RT + "iOS-18-9": [_dev("iPhone 16", "nine")],
    }}
    assert smoke.pick_device(listing) == ("ten", "iPhone 16")


def test_no_available_iphone_is_none() -> None:
    listing = {"devices": {_RT + "iOS-18-2": [_dev("iPhone 16", "x", available=False)]}}
    assert smoke.pick_device(listing) is None
    assert smoke.pick_device({}) is None


@pytest.mark.parametrize(("view", "slug"), [("/", "home"), ("", "home"), ("/settings", "settings"),
                                            ("/a/B c", "a-b-c"), ("/#energy", "energy")])
def test_view_slug(view: str, slug: str) -> None:
    assert smoke.view_slug(view) == slug


def test_synthetic_command_is_read_from_the_adopter(tmp_path: Path) -> None:
    (tmp_path / ".fleet.toml").write_text(
        '[design.review.synthetic]\ncommand = ["scripts/synth.py"]\nstartup_timeout_s = 45\n',
        encoding="utf-8",
    )
    assert smoke.synthetic_command(tmp_path) == (["scripts/synth.py"], 45.0)


@pytest.mark.parametrize("toml", [None, "[design.review]\nx = 1\n", '[design.review.synthetic]\ncommand = []\n'])
def test_missing_synthetic_command_is_unknown(tmp_path: Path, toml: str) -> None:
    if toml is not None:
        (tmp_path / ".fleet.toml").write_text(toml, encoding="utf-8")
    with pytest.raises(smoke.SmokeUnknown):
        smoke.synthetic_command(tmp_path)


def test_run_reports_unknown_without_a_synthetic_command(tmp_path: Path) -> None:
    code, line = smoke.run(tmp_path, sys.executable, ["/"], tmp_path / "out", 0.0)
    assert code == 3
    assert line.startswith("SMOKE=unknown reason=")


class _FakeSimctl:
    """A `_simctl` stand-in: `openurl` answers from `openurl_codes` in order, a screenshot writes a real-sized file."""

    def __init__(self, openurl_codes: list[int]) -> None:
        self.openurl_codes = list(openurl_codes)
        self.openurl_calls: list[str] = []

    def __call__(self, *args: str, timeout: float = 0.0) -> subprocess.CompletedProcess[str]:
        if args[0] == "openurl":
            self.openurl_calls.append(args[2])
            code = self.openurl_codes.pop(0)
            return subprocess.CompletedProcess(args, code, "", "Operation timed out" if code else "")
        if args[0] == "io" and args[2] == "screenshot":
            Path(args[3]).write_bytes(b"x" * smoke.MIN_SHOT_BYTES)
        return subprocess.CompletedProcess(args, 0, "", "")


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(smoke.time, "sleep", recorded.append)
    return recorded


def test_one_openurl_failure_then_success_is_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float],
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = _FakeSimctl([60, 0])
    monkeypatch.setattr(smoke, "_simctl", fake)
    with caplog.at_level(logging.INFO, logger="ios_sim_smoke"):
        missing = smoke._shoot("udid", "http://127.0.0.1:1", ["/"], tmp_path, settle_s=0.0)
    assert missing == []
    assert fake.openurl_calls == ["http://127.0.0.1:1/"] * 2
    assert smoke.OPENURL_RETRY_DELAY_S in sleeps
    assert "attempt 1/2" in caplog.text
    assert "attempt 2/2" in caplog.text


def test_two_openurl_failures_name_the_view(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float],
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = _FakeSimctl([60, 60, 0])
    monkeypatch.setattr(smoke, "_simctl", fake)
    with caplog.at_level(logging.INFO, logger="ios_sim_smoke"):
        missing = smoke._shoot("udid", "http://127.0.0.1:1", ["/settings"], tmp_path, settle_s=0.0)
    assert missing == ["/settings"]
    assert len(fake.openurl_calls) == 2
    assert "attempt 1/2" in caplog.text
    assert "attempt 2/2" in caplog.text


def test_a_failed_first_view_does_not_spare_the_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sleeps: list[float],
) -> None:
    monkeypatch.setattr(smoke, "_simctl", _FakeSimctl([60, 60, 0]))
    missing = smoke._shoot("udid", "http://127.0.0.1:1", ["/", "/settings"], tmp_path, settle_s=0.0)
    assert missing == ["/"]


@pytest.mark.skipif(sys.platform == "darwin", reason="checks the off-macOS refusal")
def test_off_macos_is_unknown_not_pass(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = smoke.main(["--repo", str(tmp_path), "--python", sys.executable, "--out", str(tmp_path)])
    assert code == 3
    assert capsys.readouterr().out.strip().startswith("SMOKE=unknown")
