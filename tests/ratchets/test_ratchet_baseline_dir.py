"""Every ratchet keeps its baseline in `.ratchets/<name>.json` and moves an old root copy there once.

The move lives in the shared sibling `scripts/ratchet_baseline.py`; these tests drive it directly
(the move, the refusal when both copies exist, a custom path left alone) and through a real ratchet
run, and check that every ratchet loads it.
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import ratchet_baseline as rb
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[2]
NAMES = ("static", "comment", "docs", "structure", "instruction", "doc_refs", "dead_code", "conventions",
         "runtime_write", "usage_track", "ux_surface", "request_budget", "windows_only", "port_host",
         "install_standard", "clean_tree", "test_value")


@pytest.mark.parametrize("name", NAMES)
def test_every_ratchet_defaults_into_the_folder_through_the_sibling(name: str) -> None:
    mod = importlib.import_module(f"scripts.{name}_ratchet")
    hyphenated = name.replace("_", "-")
    assert mod.DEFAULT_BASELINE == f".ratchets/{hyphenated}.json"
    assert rb.legacy_of(mod.DEFAULT_BASELINE) == f".{hyphenated}-ratchet-baseline.json"
    assert mod._baseline is rb


def test_old_default_value_means_the_new_one() -> None:
    assert rb.configured(".docs-ratchet-baseline.json", ".ratchets/docs.json") == ".ratchets/docs.json"
    assert rb.configured("custom.json", ".ratchets/docs.json") == "custom.json"


def test_legacy_root_copy_moves_once(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".docs-ratchet-baseline.json").write_text('{"old": true}\n', encoding="utf-8")
    path = rb.resolve(tmp_path, ".ratchets/docs.json", ".ratchets/docs.json", "docs ratchet")
    assert path == tmp_path / ".ratchets/docs.json"
    assert path.read_text(encoding="utf-8") == '{"old": true}\n'
    assert not (tmp_path / ".docs-ratchet-baseline.json").exists(), "never two copies"
    assert "docs ratchet: moved .docs-ratchet-baseline.json to .ratchets/docs.json" in capsys.readouterr().out
    assert rb.resolve(tmp_path, ".ratchets/docs.json", ".ratchets/docs.json", "docs ratchet") == path
    assert "moved" not in capsys.readouterr().out, "a second run has nothing to move"


def test_both_copies_refuse_and_touch_neither(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / ".docs-ratchet-baseline.json").write_text("old\n", encoding="utf-8")
    (tmp_path / ".ratchets").mkdir()
    (tmp_path / ".ratchets/docs.json").write_text("new\n", encoding="utf-8")
    assert rb.resolve(tmp_path, ".ratchets/docs.json", ".ratchets/docs.json", "docs ratchet") is None
    assert "CONFIG ERROR: both .docs-ratchet-baseline.json and .ratchets/docs.json exist" in capsys.readouterr().out
    assert (tmp_path / ".docs-ratchet-baseline.json").read_text(encoding="utf-8") == "old\n"
    assert (tmp_path / ".ratchets/docs.json").read_text(encoding="utf-8") == "new\n"


def test_fresh_repo_gets_the_folder_for_init(tmp_path: Path) -> None:
    path = rb.resolve(tmp_path, ".ratchets/docs.json", ".ratchets/docs.json", "docs ratchet")
    assert path is not None and path.parent.is_dir() and not path.exists()


def test_custom_path_is_left_alone(tmp_path: Path) -> None:
    (tmp_path / ".docs-ratchet-baseline.json").write_text("old\n", encoding="utf-8")
    assert rb.resolve(tmp_path, "custom.json", ".ratchets/docs.json", "docs ratchet") == tmp_path / "custom.json"
    assert (tmp_path / ".docs-ratchet-baseline.json").is_file()
    assert not (tmp_path / ".ratchets").exists()


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "docs_ratchet.py"), "--root", str(root), *args],
                          cwd=root, capture_output=True, text=True, creationflags=NO_WINDOW, timeout=120, check=False)


def test_a_real_run_moves_the_baseline_an_adopter_named_by_the_old_default(tmp_path: Path) -> None:
    """Adopters wrote the old default into `.fleet.toml`; the vendored script must still find and move it."""
    (tmp_path / ".fleet.toml").write_text(
        '[docs_ratchet]\nenabled = true\nbaseline = ".docs-ratchet-baseline.json"\n', encoding="utf-8")
    (tmp_path / "README.md").write_text("# x\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True, creationflags=NO_WINDOW, timeout=60)
    init = _run(tmp_path, "--init")
    assert init.returncode == 0, init.stdout + init.stderr
    (tmp_path / ".ratchets/docs.json").replace(tmp_path / ".docs-ratchet-baseline.json")
    check = _run(tmp_path)
    assert check.returncode == 0, check.stdout + check.stderr
    assert "moved .docs-ratchet-baseline.json to .ratchets/docs.json" in check.stdout
    assert not (tmp_path / ".docs-ratchet-baseline.json").exists()
    (tmp_path / ".docs-ratchet-baseline.json").write_text("{}\n", encoding="utf-8")
    assert _run(tmp_path).returncode == 2, "two copies are a configuration error"


def test_test_value_reads_a_merge_base_from_before_the_move(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mod = importlib.import_module("scripts.test_value_ratchet")
    calls: list[str] = []

    def fake_git(root: Path, args: list[str]) -> str | None:
        if args[0] == "merge-base":
            return "abc\n"
        calls.append(args[1])
        return '{"units": {"old_unit": 1}}' if args[1].endswith(".test-value-ratchet-baseline.json") else None

    monkeypatch.setattr(mod, "_git", fake_git)
    units = mod.base_baseline_units(tmp_path, mod.Config(), {"units": {"old_unit": 1, "new_unit": 1}})
    assert units == {"old_unit"}, "the old root path at the merge base, not every current unit"
    assert calls == ["abc:.ratchets/test-value.json", "abc:.test-value-ratchet-baseline.json"]
