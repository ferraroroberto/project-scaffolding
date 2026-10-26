"""Tests for the structure ratchet's near-limit band.

Files and functions at or above `near_limit_ratio` of their limit are counted per
repo; the count is shrink-only. Throwaway git repos at small limits (file 20, function
20, so the band is 18-20 lines and the split target 15), every mode, the upgrade of a
baseline written before the band existed, and this repo's own adoption.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import structure_ratchet as sr
from tests._git_repo import git, write

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG = "[structure_ratchet]\nenabled = true\nmax_file_lines = 20\nmax_function_lines = 20\n"


def lines(n: int) -> str:
    return "x = 1\n" * n


def py_function(name: str, n: int) -> str:
    return f"def {name}():\n" + "    x = 1\n" * (n - 1)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    git(tmp_path, "init", "-q")
    (tmp_path / ".fleet.toml").write_text(CONFIG, encoding="utf-8")
    write(tmp_path, "src/ok.py", "x = 1\n")
    return tmp_path


def run_mode(root: Path, *, init: bool = False, update: bool = False, allow: bool = False) -> int:
    return sr.run(root, init=init, update=update, allow_additions=allow)


def band(root: Path) -> dict[str, int] | None:
    return sr.read_baseline_file(root / sr.DEFAULT_BASELINE)[1]


# ------------------------------------------------------------------- config

def test_the_ratio_defaults_to_ninety_percent_and_is_configurable() -> None:
    cfg = sr.parse_config("[structure_ratchet]\nenabled = true\n")
    assert cfg is not None and cfg.near_limit_ratio == sr.DEFAULT_NEAR_LIMIT_RATIO == 0.9
    assert cfg.band_range("files") == (900, 1000)
    assert cfg.band_range("functions") == (90, 100), "0.9 * 100 rounds to 90, not 91"
    custom = sr.parse_config("[structure_ratchet]\nenabled = true\nnear_limit_ratio = 0.8\n")
    assert custom is not None and custom.band_range("files") == (800, 1000)


@pytest.mark.parametrize("value", ["0", "1", "1.5", "-0.1", "true", '"0.9"'])
def test_a_ratio_outside_zero_to_one_is_a_config_error(value: str) -> None:
    with pytest.raises(sr.ConfigError, match="near_limit_ratio"):
        sr.parse_config(f"[structure_ratchet]\nenabled = true\nnear_limit_ratio = {value}\n")


# ---------------------------------------------------------------- the band

def test_init_records_the_band_and_over_limit_code_is_not_in_it(repo: Path) -> None:
    write(repo, "src/near.py", lines(18))
    write(repo, "src/big.py", lines(25))
    write(repo, "src/f.py", py_function("work", 19))
    assert run_mode(repo, init=True) == sr.EXIT_PASS
    assert band(repo) == {"files": 2, "functions": 1}, "near.py and f.py; big.py is a size entry instead"
    assert run_mode(repo) == sr.EXIT_PASS


def test_a_new_file_in_the_band_fails_with_the_split_target(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "src/grown.py", lines(19))
    capsys.readouterr()
    assert run_mode(repo) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert "[near-limit file] 1 file(s) at 18-20 lines" in out
    assert "baseline 0" in out
    assert "- src/grown.py: 19 lines" in out
    assert "split it to about 15 lines" in out
    assert "docs/repo-layout.md#file-size" in out


def test_a_new_function_in_the_band_fails_by_qualname(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    run_mode(repo, init=True)
    write(repo, "src/m.py", "class Box:\n" + "".join("    " + ln + "\n" for ln in py_function("fill", 18).splitlines()))
    capsys.readouterr()
    assert run_mode(repo) == sr.EXIT_RISE
    out = capsys.readouterr().out
    assert "[near-limit function]" in out
    assert "- src/m.py: Box.fill() is 18 lines" in out
    assert "split it into named helpers of about 15 lines" in out


def test_a_split_that_lands_just_under_the_limit_still_fails(repo: Path) -> None:
    write(repo, "src/big.py", lines(30))
    run_mode(repo, init=True)
    write(repo, "src/big.py", lines(19))
    write(repo, "src/rest.py", lines(11))
    assert run_mode(repo) == sr.EXIT_RISE


def test_leaving_the_band_passes_and_update_shrinks_the_count(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "src/near.py", lines(19))
    run_mode(repo, init=True)
    write(repo, "src/near.py", lines(14))
    capsys.readouterr()
    assert run_mode(repo) == sr.EXIT_PASS
    assert "below the baseline" in capsys.readouterr().out
    assert run_mode(repo, update=True) == sr.EXIT_PASS
    assert band(repo) == {"files": 0, "functions": 0}


def test_one_entering_while_another_leaves_keeps_the_count(repo: Path) -> None:
    write(repo, "src/a.py", lines(19))
    run_mode(repo, init=True)
    write(repo, "src/a.py", lines(10))
    write(repo, "src/b.py", lines(18))
    assert run_mode(repo) == sr.EXIT_PASS


def test_update_never_raises_the_band_without_allow_additions(repo: Path) -> None:
    run_mode(repo, init=True)
    before = (repo / sr.DEFAULT_BASELINE).read_text(encoding="utf-8")
    write(repo, "src/near.py", lines(20))
    assert run_mode(repo, update=True) == sr.EXIT_RISE
    assert (repo / sr.DEFAULT_BASELINE).read_text(encoding="utf-8") == before
    assert run_mode(repo, update=True, allow=True) == sr.EXIT_PASS
    assert band(repo) == {"files": 1, "functions": 0}
    assert run_mode(repo) == sr.EXIT_PASS


# ------------------------------------------------- upgrading an old baseline

OLD_BASELINE = '{\n  "version": 1,\n  "entries": [\n    {"key": "size:src/big.py", "lines": 25}\n  ]\n}\n'


def test_a_baseline_from_before_the_band_passes_then_update_records_it(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "src/big.py", lines(25))
    write(repo, "src/near.py", lines(19))
    (repo / sr.DEFAULT_BASELINE).write_text(OLD_BASELINE, encoding="utf-8")
    assert sr.read_baseline(repo / sr.DEFAULT_BASELINE) == {"size:src/big.py": 25}
    assert band(repo) is None
    capsys.readouterr()
    assert run_mode(repo) == sr.EXIT_PASS, "re-vendoring never fails an adopter on the band"
    assert "not recorded" in capsys.readouterr().out
    assert run_mode(repo, update=True) == sr.EXIT_PASS, "recording the band is not an addition"
    assert band(repo) == {"files": 1, "functions": 0}
    write(repo, "src/next.py", lines(18))
    assert run_mode(repo) == sr.EXIT_RISE, "once recorded, the band is ratcheted"


@pytest.mark.parametrize("value", ['{"files": 1}', '{"files": -1, "functions": 0}', '{"files": true, "functions": 0}',
                                   "[1, 2]", '{"files": 1, "functions": 0, "dirs": 0}'])
def test_a_malformed_band_is_a_baseline_error(repo: Path, value: str) -> None:
    (repo / sr.DEFAULT_BASELINE).write_text(f'{{"version": 1, "band": {value}, "entries": []}}', encoding="utf-8")
    assert run_mode(repo) == sr.EXIT_CONFIG


# ------------------------------------------------------------ self-adoption

def test_the_scaffold_records_its_band() -> None:
    cfg, _ = sr.load_config(REPO_ROOT)
    assert cfg is not None
    data = json.loads((REPO_ROOT / cfg.baseline).read_text(encoding="utf-8"))
    assert set(data["band"]) == set(sr.BANDS), "the scaffold's own baseline ratchets the band"


def test_the_doc_states_the_band_knob_and_split_target() -> None:
    text = (REPO_ROOT / "docs" / "structure-ratchet.md").read_text(encoding="utf-8")
    assert f"near_limit_ratio   = {sr.DEFAULT_NEAR_LIMIT_RATIO}" in text
    assert f"{sr.SPLIT_TARGET_RATIO:.0%}" in text
