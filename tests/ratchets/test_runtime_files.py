"""The guarded writer for caller-named paths: it writes anywhere outside the code folders and refuses the rest."""

from __future__ import annotations

from pathlib import Path

import pytest

from src import runtime_files
from src.runtime_files import CODE_FOLDERS, REPO_ROOT, RuntimeWriteRefused


def test_a_path_outside_the_checkout_is_written(tmp_path: Path) -> None:
    target = tmp_path / "run" / "out.txt"
    runtime_files.make_dirs(target.parent)
    runtime_files.save_text(target, "one\n")
    runtime_files.append_text(target, "two\n")
    assert target.read_text(encoding="utf-8") == "one\ntwo\n"


def test_bytes_and_copies_land_byte_for_byte(tmp_path: Path) -> None:
    source, copy = tmp_path / "a.bin", tmp_path / "b.bin"
    runtime_files.save_bytes(source, b"\x00\xffabc")
    runtime_files.copy_file(source, copy)
    assert copy.read_bytes() == b"\x00\xffabc"


def test_newline_is_passed_through(tmp_path: Path) -> None:
    runtime_files.save_text(tmp_path / "x.toml", "a\nb\n", newline="\n")
    assert (tmp_path / "x.toml").read_bytes() == b"a\nb\n"


@pytest.mark.parametrize("folder", CODE_FOLDERS)
def test_every_code_folder_is_refused_for_each_write(folder: str) -> None:
    target = REPO_ROOT / folder / "nested" / "leak.txt"
    for call in (
        lambda: runtime_files.make_dirs(target.parent),
        lambda: runtime_files.save_text(target, "x"),
        lambda: runtime_files.save_bytes(target, b"x"),
        lambda: runtime_files.append_text(target, "x"),
        lambda: runtime_files.copy_file(REPO_ROOT / "README.md", target),
    ):
        with pytest.raises(RuntimeWriteRefused):
            call()
    assert not (REPO_ROOT / folder / "nested").exists()


def test_a_dotdot_path_into_a_code_folder_is_refused(tmp_path: Path) -> None:
    sneaky = REPO_ROOT / "docs" / ".." / "src" / "leak.txt"
    with pytest.raises(RuntimeWriteRefused):
        runtime_files.save_text(sneaky, "x")


def test_a_gitignored_folder_of_the_checkout_is_allowed() -> None:
    assert runtime_files.checked(REPO_ROOT / "data" / "run.log") == (REPO_ROOT / "data" / "run.log").resolve()


def test_the_code_folders_match_the_ratchet_default() -> None:
    from scripts import runtime_write_ratchet

    assert CODE_FOLDERS == tuple(runtime_write_ratchet.DEFAULT_CODE_FOLDERS)
