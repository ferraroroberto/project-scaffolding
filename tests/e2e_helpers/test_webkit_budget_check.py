"""The WebKit request-budget stage reports every outcome as its own state, never folding "not run" into a pass."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.tools import webkit_budget_check as wbc


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _last_line(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out.strip().splitlines()[-1]


def test_discovery_finds_the_test_that_measures_and_not_the_probe_helper(tmp_path: Path) -> None:
    _write(tmp_path, "tests/e2e/budget/_request_budget.py", "def measure_request_budget(page): ...\n")
    _write(tmp_path, "tests/e2e/budget/test_main.py", "reading = measure_request_budget(page, url)\n")
    _write(tmp_path, "tests/e2e/test_other.py", "def test_x(): ...\n")
    _write(tmp_path, ".venv/lib/test_vendored.py", "measure_request_budget(page)\n")
    assert wbc.discover_targets(tmp_path) == ["tests/e2e/budget/test_main.py"]


def test_declared_targets_override_discovery_and_must_be_a_list_of_paths(tmp_path: Path) -> None:
    assert wbc.declared_targets(tmp_path) is None
    _write(tmp_path, ".fleet.toml", '[request_budget]\nwebkit_targets = ["tests/e2e/test_request_budget.py"]\n')
    assert wbc.declared_targets(tmp_path) == ["tests/e2e/test_request_budget.py"]
    _write(tmp_path, ".fleet.toml", "[request_budget]\nwebkit_targets = 3\n")
    with pytest.raises(ValueError):
        wbc.declared_targets(tmp_path)


def test_no_budget_test_is_its_own_state(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert wbc.run(tmp_path, "python") == wbc.EXIT_NO_TESTS
    assert _last_line(capsys) == "WEBKIT_BUDGET=no-tests"


def test_a_missing_webkit_build_is_not_run_never_a_pass(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "tests/e2e/test_budget.py", "measure_request_budget(page, url)\n")
    monkeypatch.setattr(wbc, "webkit_installed", lambda: False)
    ran: list[object] = []
    monkeypatch.setattr(wbc.subprocess, "run", lambda *a, **k: ran.append(a))
    assert wbc.run(tmp_path, "python") == wbc.EXIT_NOT_INSTALLED
    assert _last_line(capsys) == "WEBKIT_BUDGET=not-installed"
    assert not ran


def test_playwright_that_cannot_answer_is_unknown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "tests/e2e/test_budget.py", "measure_request_budget(page, url)\n")
    monkeypatch.setattr(wbc, "webkit_installed", lambda: None)
    assert wbc.run(tmp_path, "python") == wbc.EXIT_UNKNOWN
    assert _last_line(capsys) == "WEBKIT_BUDGET=unknown"


def test_a_declared_target_that_is_missing_is_unknown(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _write(tmp_path, ".fleet.toml", '[request_budget]\nwebkit_targets = ["tests/nope.py"]\n')
    assert wbc.run(tmp_path, "python") == wbc.EXIT_UNKNOWN
    assert _last_line(capsys) == "WEBKIT_BUDGET=unknown"


@pytest.mark.parametrize(
    ("pytest_exit", "expected_exit", "word"),
    [(0, wbc.EXIT_PASS, "pass"), (1, wbc.EXIT_FAIL, "fail"), (5, wbc.EXIT_UNKNOWN, "unknown"), (2, wbc.EXIT_UNKNOWN, "unknown")],
)
def test_pytest_outcome_maps_to_one_verdict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
    pytest_exit: int, expected_exit: int, word: str,
) -> None:
    _write(tmp_path, "tests/e2e/test_budget.py", "measure_request_budget(page, url)\n")
    monkeypatch.setattr(wbc, "webkit_installed", lambda: True)
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **_: object) -> SimpleNamespace:
        calls.append(argv)
        return SimpleNamespace(returncode=pytest_exit)

    monkeypatch.setattr(wbc.subprocess, "run", fake_run)
    code = wbc.run(tmp_path, "python")
    assert code == expected_exit
    assert _last_line(capsys) == f"WEBKIT_BUDGET={word}"
    assert calls == [["python", "-m", "pytest", "tests/e2e/test_budget.py", "--browser", "webkit"]]
