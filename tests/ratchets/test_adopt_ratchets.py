"""scripts/adopt_ratchets.py and scripts/run_ratchets.py: the kit for a repo outside the fleet.

The sibling table and the stage order are cross-checked against the scripts and
the scaffold's own gate, so a new sibling or stage cannot go unlisted; the
adopt and run paths run for real against throwaway git repos.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from scripts import adopt_ratchets as ar
from scripts import run_ratchets as rr
from src.no_window import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[2]


def git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True, timeout=60, creationflags=NO_WINDOW)
    (path / "src").mkdir()
    (path / "src" / "core.py").write_text('def f() -> int:\n    """One."""\n    return 1\n', encoding="utf-8")
    return path


# ------------------------------------------------------------- anti-drift

def test_every_ratchet_lists_exactly_the_siblings_its_script_loads() -> None:
    for r in ar.RATCHETS:
        text = (REPO_ROOT / "scripts" / f"{r.table}.py").read_text(encoding="utf-8")
        loaded = set(re.findall(r'_load_sibling\("(\w+)"\)', text))
        assert loaded == set(r.siblings), r.name


def test_every_ratchet_script_is_in_the_scaffold_catalog() -> None:
    components = tomllib.loads((REPO_ROOT / ".fleet.toml").read_text(encoding="utf-8"))["components"]
    sources = {v["src"] for v in components.values()}
    for r in ar.RATCHETS:
        assert {f"scripts/{f}" for f in r.files} <= sources, r.name
    on_disk = {p.stem.removesuffix("_ratchet") for p in (REPO_ROOT / "scripts").glob("*_ratchet.py")}
    assert on_disk == set(ar.BY_NAME)


def test_stage_order_matches_the_runner_and_the_scaffold_gate() -> None:
    assert tuple(r.name for r in ar.RATCHETS) == rr.STAGES
    gate = (REPO_ROOT / "scripts" / "verify-before-ship.ps1").read_text(encoding="utf-8")
    order = re.findall(r'Invoke-Stage "([a-z ]+) ratchet"', gate)
    assert tuple(s.replace(" ", "_") for s in order) == rr.STAGES


def test_recommended_set_needs_no_tool_and_no_choice() -> None:
    for name in ar.RECOMMENDED:
        assert ar.BY_NAME[name].needs == "-" and not ar.BY_NAME[name].starter, name


# --------------------------------------------------------------- toml merge

def test_merge_into_an_empty_file_has_no_leading_blank_line() -> None:
    out = ar.merge_toml("", ["[comment_ratchet]\nenabled = true\n"], ['a = { dest = "scripts/a.py" }\n'])
    assert out.startswith("[vendored]\n")
    assert tomllib.loads(out) == {"vendored": {"a": {"dest": "scripts/a.py"}}, "comment_ratchet": {"enabled": True}}


def test_merge_into_an_existing_vendored_table_keeps_one_header() -> None:
    text = 'layer = "x"\n\n[vendored]\nold = { dest = "o" }\n\n[other]\nk = 1\n'
    out = ar.merge_toml(text, [], ['new = { dest = "n" }\n'])
    assert out.count("[vendored]") == 1
    assert set(tomllib.loads(out)["vendored"]) == {"old", "new"}
    assert tomllib.loads(out)["other"] == {"k": 1}


def test_parse_names_orders_by_stage_and_rejects_unknowns() -> None:
    assert [r.name for r in ar.parse_names("runtime_write,comment_ratchet")] == ["comment", "runtime_write"]
    assert [r.name for r in ar.parse_names(None)] == list(ar.RECOMMENDED)
    assert len(ar.parse_names("all")) == len(ar.RATCHETS)
    with pytest.raises(ValueError, match="nope"):
        ar.parse_names("comment,nope")


# ------------------------------------------------------------ adopt, real

def test_adopt_copies_declares_inits_and_is_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = git_repo(tmp_path / "t")
    assert ar.main([str(target), "--ratchets", "comment,structure,runtime_write"]) == ar.EXIT_OK
    for name in ("comment_ratchet", "structure_ratchet", "structure_layout", "structure_band",
                 "runtime_write_ratchet", "runtime_write_resolve", "run_ratchets"):
        assert (target / "scripts" / f"{name}.py").read_bytes() == (REPO_ROOT / "scripts" / f"{name}.py").read_bytes()
    data = tomllib.loads((target / ".fleet.toml").read_text(encoding="utf-8"))
    assert data["structure_ratchet"] == {"enabled": True}
    assert data["vendored"]["structure_band"]["dest"] == "scripts/structure_band.py"
    for b in ("comment", "structure", "runtime-write"):
        assert (target / f".{b}-ratchet-baseline.json").is_file()
    before = (target / ".fleet.toml").read_bytes()
    assert ar.main([str(target), "--ratchets", "comment,structure,runtime_write"]) == ar.EXIT_OK
    assert (target / ".fleet.toml").read_bytes() == before
    assert "copied" not in capsys.readouterr().out.split("adopting", 2)[2]


def test_a_modified_copy_is_refused_not_overwritten(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = git_repo(tmp_path / "t")
    (target / "scripts").mkdir()
    (target / "scripts" / "comment_ratchet.py").write_text("# mine\n", encoding="utf-8")
    assert ar.main([str(target), "--ratchets", "comment"]) == ar.EXIT_FAILED
    assert (target / "scripts" / "comment_ratchet.py").read_text(encoding="utf-8") == "# mine\n"
    out = capsys.readouterr().out
    assert "comment: REFUSED" in out
    assert "comment_ratchet" not in tomllib.loads((target / ".fleet.toml").read_text(encoding="utf-8"))


def test_an_existing_disabled_table_is_kept_and_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = git_repo(tmp_path / "t")
    (target / ".fleet.toml").write_text("[docs_ratchet]\nenabled = false\n", encoding="utf-8")
    ar.main([str(target), "--ratchets", "docs"])
    assert tomllib.loads((target / ".fleet.toml").read_text(encoding="utf-8"))["docs_ratchet"] == {"enabled": False}
    assert "not enabled -- left as is" in capsys.readouterr().out


def test_static_without_npx_writes_the_opt_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = git_repo(tmp_path / "t")
    monkeypatch.setattr(ar, "has_npx", lambda: False)
    monkeypatch.setattr(ar, "has_ruff", lambda: True)
    monkeypatch.setattr(ar, "init_ratchet", lambda root, r: (0, "stubbed"))
    assert ar.main([str(target), "--ratchets", "static"]) == ar.EXIT_OK
    assert tomllib.loads((target / ".fleet.toml").read_text(encoding="utf-8"))["static_ratchet"]["duplicates"] is False


def test_static_without_ruff_is_not_adopted_and_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    target = git_repo(tmp_path / "t")
    monkeypatch.setattr(ar, "has_ruff", lambda: False)
    assert ar.main([str(target), "--ratchets", "static"]) == ar.EXIT_FAILED
    assert not (target / "scripts" / "static_ratchet.py").exists()


def test_a_target_that_is_not_a_git_repo_is_refused(tmp_path: Path) -> None:
    assert ar.main([str(tmp_path)]) == ar.EXIT_USAGE


# --------------------------------------------------------------- the runner

def runner_repo(tmp_path: Path, toml: str) -> Path:
    target = git_repo(tmp_path / "r")
    (target / ".fleet.toml").write_text(toml, encoding="utf-8")
    return target


def test_nothing_enabled_is_a_config_error_not_a_pass(tmp_path: Path) -> None:
    assert rr.run(runner_repo(tmp_path, 'layer = "x"\n'), None, 60) == rr.EXIT_CONFIG


def test_a_missing_script_is_not_confirmed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = runner_repo(tmp_path, "[comment_ratchet]\nenabled = true\n")
    assert rr.run(root, None, 60) == rr.EXIT_NOT_CONFIRMED
    assert "[NOT CONFIRMED] comment ratchet" in capsys.readouterr().out


@pytest.mark.parametrize(("codes", "expected"), [
    ([0, 0], 0), ([0, 3], 3), ([3, 2], 2), ([2, 1, 3], 1), ([0, 5], 1),
])
def test_worst_never_folds_an_unknown_into_a_pass(codes: list[int], expected: int) -> None:
    assert rr.worst(codes) == expected


def test_runner_brackets_the_tests_with_the_probe(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = git_repo(tmp_path / "t")
    assert ar.main([str(target), "--ratchets", "runtime_write"]) == ar.EXIT_OK
    leak = [sys.executable, "-c", "open('src/leak.txt', 'w').close()"]
    assert rr.run(target, leak, 120) == rr.EXIT_FAIL
    assert "FAIL          runtime write probe" in capsys.readouterr().out
    (target / "src" / "leak.txt").unlink()
    assert rr.run(target, [sys.executable, "-c", "pass"], 120) == rr.EXIT_PASS
    assert rr.run(target, None, 120) == rr.EXIT_PASS
    assert "[OFF] runtime write probe" in capsys.readouterr().out


def test_a_failing_test_command_fails_the_run(tmp_path: Path) -> None:
    target = git_repo(tmp_path / "t")
    assert ar.main([str(target), "--ratchets", "comment"]) == ar.EXIT_OK
    assert rr.run(target, [sys.executable, "-c", "raise SystemExit(4)"], 120) == rr.EXIT_FAIL
