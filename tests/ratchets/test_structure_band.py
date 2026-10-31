"""Tests for the structure ratchet's warning band (`scripts/structure_band.py`).

Every check lists the files, functions and directories at or above `near_limit_ratio` of their
limit, and the listing never changes the exit code. Throwaway git repos at small limits (file 20,
function 20, directory 10, so the bands are 18-20 lines and 9-10 modules).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import structure_band as sb
from scripts import structure_ratchet as sr
from tests._git_repo import git, write

CONFIG = ("[structure_ratchet]\nenabled = true\nmax_file_lines = 20\nmax_function_lines = 20\n"
          "max_dir_modules = 10\n")


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


def check(root: Path, capsys: pytest.CaptureFixture[str], **mode: bool) -> tuple[int, str]:
    capsys.readouterr()
    code = sr.run(root, init=mode.get("init", False), update=mode.get("update", False),
                  allow_additions=mode.get("allow", False))
    return code, capsys.readouterr().out


def fill_dir(root: Path, folder: str, n: int) -> None:
    for i in range(n):
        write(root, f"{folder}/m{i}.py", "x = 1\n")


# ------------------------------------------------------------------ the band

def test_the_directory_band_starts_at_ninety_percent_of_its_limit() -> None:
    cfg = sr.parse_config("[structure_ratchet]\nenabled = true\n")
    assert cfg is not None and cfg.band_range("dirs") == (36, 40)
    assert cfg.band_range("files") == (900, 1000)
    assert sb.band_low(100, 0.9) == 90, "0.9 * 100 rounds to 90, not 91"


def test_a_pass_lists_every_file_function_and_directory_in_the_band(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "src/near.py", lines(19))
    write(repo, "src/f.py", py_function("work", 18))
    fill_dir(repo, "pkg", 9)
    assert check(repo, capsys, init=True)[0] == sr.EXIT_PASS
    code, out = check(repo, capsys)
    assert code == sr.EXIT_PASS
    assert "warning band (90% of a limit; reported, never failed): 2 file(s), 1 function(s), 1 directory(s)" in out
    assert "  [warning] src/near.py: 19 lines" in out
    assert "  [warning] src/f.py: 18 lines" in out, "the function's own file is in the band too"
    assert "  [warning] src/f.py: work() is 18 lines" in out
    assert "  [warning] pkg/: 9 modules" in out
    assert out.index("warning band") < out.index("PASS"), "warnings come before the verdict"


def test_over_limit_code_and_code_under_the_band_are_not_warned(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "src/big.py", lines(25))
    write(repo, "src/small.py", lines(17))
    fill_dir(repo, "pkg", 8)
    check(repo, capsys, init=True)
    code, out = check(repo, capsys)
    assert code == sr.EXIT_PASS
    assert "0 file(s), 0 function(s), 0 directory(s)" in out
    assert "[warning]" not in out


def test_a_clear_band_still_prints_its_summary(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    check(repo, capsys, init=True)
    code, out = check(repo, capsys)
    assert code == sr.EXIT_PASS
    assert "warning band (90% of a limit; reported, never failed): 0 file(s), 0 function(s), 0 directory(s)" in out


# -------------------------------------------------------- exit code unchanged

def test_a_directory_entering_the_band_warns_but_never_fails(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fill_dir(repo, "pkg", 8)
    check(repo, capsys, init=True)
    write(repo, "pkg/m8.py", "x = 1\n")
    write(repo, "pkg/m9.py", "x = 1\n")
    code, out = check(repo, capsys)
    assert code == sr.EXIT_PASS, "the directory band is listed, not ratcheted"
    assert "  [warning] pkg/: 10 modules" in out


def test_a_failing_run_keeps_its_exit_code_and_still_lists_the_band(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    check(repo, capsys, init=True)
    write(repo, "src/grown.py", lines(19))
    code, out = check(repo, capsys)
    assert code == sr.EXIT_RISE, "the near-limit count rose, so the ratchet still fails"
    assert "  [warning] src/grown.py: 19 lines" in out
    assert "[near-limit file]" in out


def test_the_band_is_listed_only_by_the_check(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write(repo, "src/near.py", lines(19))
    assert "warning band" not in check(repo, capsys, init=True)[1]
    assert "warning band" not in check(repo, capsys, update=True)[1]


# ------------------------------------------------------------------- unknown

def test_an_unmeasured_function_makes_its_files_band_unknown(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write(repo, "web/a.js", "function open() {\n  return 1;\n")
    check(repo, capsys, init=True)
    code, out = check(repo, capsys)
    assert code == sr.EXIT_PASS, "the unmeasured entry is baselined; the warning never fails"
    assert "function band UNKNOWN in 1 file(s)" in out
    assert "  [unknown] web/a.js: the end of a function was not found, so its band is unknown" in out


def test_a_tree_that_cannot_be_measured_reports_the_band_unknown(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    check(repo, capsys, init=True)
    write(repo, "src/broken.py", "def broken(:\n")
    code, out = check(repo, capsys)
    assert code == sr.EXIT_NOT_CONFIRMED
    assert "the warning band is unknown" in out
    assert "reported, never failed" not in out


def test_warning_lines_sort_members_within_each_kind() -> None:
    members = sb.empty_members()
    members["files"] += ["b.py: 19 lines", "a.py: 18 lines"]
    members["dirs"] += ["pkg/: 9 modules"]
    out = sb.warning_lines(members, 0.9)
    assert out[1:] == ["  [warning] a.py: 18 lines", "  [warning] b.py: 19 lines", "  [warning] pkg/: 9 modules"]
