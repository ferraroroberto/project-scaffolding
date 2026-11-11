"""`scripts/ci/nightly_matrix.py`: the nightly Mac run's matrix, selection, legs and READY.

The point of the suite is the decisions the runner makes alone at night: which
adopters run (changed since the last green night, all of them on Sunday or on
`full`), which tables are refused (anything outside the allowed characters
never reaches a command), how a leg reads (pass, flaky on a passing retry, fail
on a second failure, unknown when nothing ran) and when the last green SHA
moves (only on a green night).
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "ci"))

import nightly_matrix as nm  # noqa: E402 -- needs the sys.path line above

SHA_A = "a" * 40
SHA_B = "b" * 40

TABLE = """
[ci.nightly]
python       = "3.14"
requirements = ["requirements.txt", "requirements-dev.txt"]
samples      = "config"
unit         = ["tests", "--ignore=tests/e2e"]
e2e          = ["tests/e2e", "--e2e-autoboot"]
views        = ["/"]
"""

_NO_HOOKS = Path(tempfile.gettempdir()) / "nightly-matrix-no-hooks"


# ------------------------------------------------------------------ table
def test_a_full_table_parses_with_the_default_exclusion() -> None:
    entry = nm.parse_table(TABLE)
    assert entry["python"] == "3.14"
    assert entry["unit"] == ["tests", "--ignore=tests/e2e"]
    assert entry["exclude_marker"] == "not windows_only"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (None, "no .fleet.toml"),
        ("[e2e]\nx = 1\n", "no [ci.nightly]"),
        ("not = = toml", "does not parse"),
        (TABLE + 'surprise = "x"\n', "unknown [ci.nightly] keys"),
        (TABLE.replace('"3.14"', '"3.14; rm -rf ~"'), "`python`"),
        (TABLE.replace('"tests", "--ignore', '"tests; curl x", "--ignore'), "`unit`"),
        (TABLE.replace('["/"]', '["/$(id)"]'), "`views`"),
        (TABLE.replace('"config"', '"config dir"'), "`samples`"),
        (TABLE.replace('requirements = ["requirements.txt", "requirements-dev.txt"]', "requirements = []"), "`requirements`"),
        (TABLE + 'exclude_marker = "not `x`"\n', "`exclude_marker`"),
        ('[ci.nightly]\npython = "3.14"\nrequirements = ["r.txt"]\n', "at least one of"),
        ('[ci.nightly]\npython = "3.14"\nrequirements = ["r.txt"]\nunit = ["tests"]\nviews = ["/"]\n', "`views` needs `e2e`"),
    ],
)
def test_an_unusable_table_is_refused(text: str | None, message: str) -> None:
    with pytest.raises(ValueError, match=None) as caught:
        nm.parse_table(text)
    assert message in str(caught.value)


def test_an_opt_out_needs_only_its_reason() -> None:
    entry = nm.parse_table('[ci.nightly]\nskip_reason = "no tests | yet `x`"\n')
    assert entry == {"skip_reason": "no tests  yet x"}


def test_the_adopter_list_ignores_comments_and_rejects_odd_names(tmp_path: Path) -> None:
    good = tmp_path / "a.txt"
    good.write_text("# header\nhome-automation\n\nother  # note\nhome-automation\n", encoding="utf-8")
    assert nm.read_adopters(good) == ["home-automation", "other"]
    bad = tmp_path / "b.txt"
    bad.write_text("../escape repo\n", encoding="utf-8")
    with pytest.raises(ValueError):
        nm.read_adopters(bad)


# ------------------------------------------------------------------ selection
def _fake_fetch(repos: dict[str, tuple[str | None, str | None, str]]) -> nm.Fetcher:
    def fetch(url: str, work: Path) -> tuple[str | None, str | None, str]:
        return repos[url.rsplit("/", 1)[1].removesuffix(".git")]
    return fetch


def _green(state_root: Path, repo: str, sha: str) -> None:
    nm.record_green(state_root / repo / "state.json", sha, "1")


def test_a_weekday_skips_an_unchanged_repo_and_runs_a_changed_one(tmp_path: Path) -> None:
    _green(tmp_path, "same", SHA_A)
    _green(tmp_path, "moved", SHA_A)
    fetch = _fake_fetch({"same": (SHA_A, TABLE, ""), "moved": (SHA_B, TABLE, "")})
    rows, decisions = nm.build(["same", "moved"], "https://x/", tmp_path, tmp_path / "w", False, fetch)
    assert [r["repo"] for r in rows] == ["moved"]
    assert rows[0]["sha"] == SHA_B and rows[0]["status"] == "run"
    assert rows[0]["unit"] == "tests --ignore=tests/e2e"
    assert ("same", "skip", "main unchanged since the last green night") in decisions


def test_a_full_night_runs_an_unchanged_repo(tmp_path: Path) -> None:
    _green(tmp_path, "same", SHA_A)
    fetch = _fake_fetch({"same": (SHA_A, TABLE, "")})
    rows, _ = nm.build(["same"], "https://x/", tmp_path, tmp_path / "w", True, fetch)
    assert [r["repo"] for r in rows] == ["same"]


def test_sunday_is_a_full_night() -> None:
    assert nm.is_full_night(False, dt.date(2026, 11, 8))  # a Sunday
    assert not nm.is_full_night(False, dt.date(2026, 11, 9))
    assert nm.is_full_night(True, dt.date(2026, 11, 9))


def test_a_repo_with_no_green_night_yet_runs(tmp_path: Path) -> None:
    rows, _ = nm.build(["new"], "https://x/", tmp_path, tmp_path / "w", False, _fake_fetch({"new": (SHA_A, TABLE, "")}))
    assert [r["repo"] for r in rows] == ["new"]


def test_a_red_repo_runs_again_the_next_night(tmp_path: Path) -> None:
    results = tmp_path / "run"
    rc = nm.main([
        "ready", "--results", str(results), "--state", str(tmp_path / "red" / "state.json"), "--run", "7",
        "--repo", "red", "--sha", SHA_A, "--status", "run", "--declared", "unit", "--unit", "fail",
    ])
    assert rc == 1
    assert nm.last_green(tmp_path / "red" / "state.json") is None
    rows, _ = nm.build(["red"], "https://x/", tmp_path, tmp_path / "w", False, _fake_fetch({"red": (SHA_A, TABLE, "")}))
    assert [r["repo"] for r in rows] == ["red"]


def test_unreadable_repos_stay_in_the_matrix_as_unknown(tmp_path: Path) -> None:
    fetch = _fake_fetch({"gone": (None, None, "git fetch failed"), "bare": (SHA_A, None, ""), "out": (SHA_A, '[ci.nightly]\nskip_reason = "no tests"\n', "")})
    rows, decisions = nm.build(["gone", "bare", "out"], "https://x/", tmp_path, tmp_path / "w", True, fetch)
    assert [(r["repo"], r["status"]) for r in rows] == [("gone", "unknown"), ("bare", "unknown")]
    assert rows[1]["reason"] == "no .fleet.toml on main"
    assert ("out", "skip", "opted out: no tests") in decisions


def test_build_writes_the_matrix_and_an_empty_night_is_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    adopters = tmp_path / "adopters.txt"
    adopters.write_text("same\n", encoding="utf-8")
    _green(tmp_path / "state", "same", SHA_A)
    monkeypatch.setattr(nm, "fetch_main", _fake_fetch({"same": (SHA_A, TABLE, "")}))
    out, summary = tmp_path / "out", tmp_path / "summary.md"
    argv = ["build", "--adopters", str(adopters), "--url-base", "https://x/", "--state-root", str(tmp_path / "state"),
            "--today", "2026-11-09", "--github-output", str(out), "--summary-file", str(summary)]
    assert nm.main(argv) == 0
    lines = dict(line.split("=", 1) for line in out.read_text(encoding="utf-8").splitlines())
    assert json.loads(lines["matrix"]) == {"include": []} and lines["count"] == "0"
    assert "Nothing changed" in summary.read_text(encoding="utf-8")


def test_fetch_main_reads_sha_and_table_from_one_shallow_fetch(tmp_path: Path) -> None:
    origin = tmp_path / "origin"
    origin.mkdir()

    def git(*args: str) -> str:
        out = subprocess.run(
            ["git", "-C", str(origin), "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false",
             "-c", f"core.hooksPath={_NO_HOOKS}", *args],
            capture_output=True, text=True, check=True, timeout=60, creationflags=nm.NO_WINDOW,
        )
        return out.stdout.strip()

    git("init", "-q", "-b", "main")
    (origin / ".fleet.toml").write_text(TABLE, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    head = git("rev-parse", "HEAD")
    sha, text, error = nm.fetch_main(origin.as_uri(), tmp_path / "work")
    assert (sha, error) == (head, "")
    assert text is not None and nm.parse_table(text)["python"] == "3.14"
    sha, text, error = nm.fetch_main((tmp_path / "missing").as_uri(), tmp_path / "work2")
    assert sha is None and error == "git fetch failed"


# ------------------------------------------------------------------ legs
def _junit(path: Path, failed: list[str], passed: list[str]) -> None:
    cases = [f'<testcase classname="m" name="{n}"><failure message="x"/></testcase>' for n in failed]
    cases += [f'<testcase classname="m" name="{n}"/>' for n in passed]
    path.write_text(f"<testsuites><testsuite>{''.join(cases)}</testsuite></testsuites>", encoding="utf-8")


def _runner(codes: list[int | None], junits: list[tuple[list[str], list[str]]]) -> Callable[..., int | None]:
    calls: list[list[str]] = []

    def run(python: str, cwd: Path, args: list[str]) -> int | None:
        index = len(calls)
        calls.append(args)
        if index < len(junits):
            _junit(Path(args[args.index("--junitxml") + 1]), *junits[index])
        return codes[index]

    run.calls = calls  # type: ignore[attr-defined]
    return run


def _leg(tmp_path: Path, runner: Callable[..., int | None]) -> tuple[str, int, str]:
    return nm.run_leg("py", tmp_path, ["tests"], ["--output", "retry"], tmp_path / "j.xml", tmp_path / "r.xml",
                      tmp_path / "flaky.txt", runner=runner)


def test_a_passing_leg_runs_once(tmp_path: Path) -> None:
    runner = _runner([0], [([], ["a"])])
    assert _leg(tmp_path, runner) == ("pass", 0, "")
    assert len(runner.calls) == 1  # type: ignore[attr-defined]


def test_a_pass_on_retry_is_flaky_and_names_the_tests(tmp_path: Path) -> None:
    runner = _runner([1, 0], [(["a", "b"], ["c"]), ([], ["a", "b"])])
    assert _leg(tmp_path, runner) == ("flaky", 2, "passed on retry")
    retry = runner.calls[1]  # type: ignore[attr-defined]
    assert "--last-failed" in retry and retry[-1] == str(tmp_path / "r.xml") and "retry" in retry
    assert (tmp_path / "flaky.txt").read_text(encoding="utf-8") == "m::a\nm::b\n"


def test_fail_twice_is_red(tmp_path: Path) -> None:
    runner = _runner([1, 1], [(["a"], []), (["a"], [])])
    assert _leg(tmp_path, runner) == ("fail", 0, "failed twice")
    assert not (tmp_path / "flaky.txt").exists()


def test_a_hang_is_red_without_a_second_hour(tmp_path: Path) -> None:
    runner = _runner([None], [])
    assert _leg(tmp_path, runner) == ("fail", 0, "timed out")
    assert len(runner.calls) == 1  # type: ignore[attr-defined]


def test_nothing_collected_is_unknown(tmp_path: Path) -> None:
    assert _leg(tmp_path, _runner([5], []))[0] == "unknown"


def test_the_leg_cli_refuses_unsafe_arguments_and_adds_the_marker(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    base = ["leg", "--name", "unit", "--python", "py", "--cwd", str(tmp_path), "--junit", "j", "--retry-junit", "r",
            "--flaky-out", "f"]
    assert nm.main([*base, "--args", "tests;id"]) == 3
    assert nm.main([*base, "--args", "tests", "--marker", "not `x`"]) == 3
    assert "result=unknown" in capsys.readouterr().out


def test_a_real_flaky_test_is_caught_by_the_retry(tmp_path: Path) -> None:
    """Drives real pytest: --last-failed re-runs only the failure, which passes the second time."""
    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_x.py").write_text(
        "import pathlib\n\n"
        "def test_steady():\n    assert True\n\n"
        "def test_flaky():\n"
        "    mark = pathlib.Path(__file__).with_name('seen')\n"
        "    first = not mark.exists()\n"
        "    mark.write_text('1')\n"
        "    assert not first\n\n"
        "def test_windows():\n    assert False\n",
        encoding="utf-8",
    )
    (project / "pytest.ini").write_text("[pytest]\nmarkers =\n    windows_only: needs Windows\n", encoding="utf-8")
    text = (project / "test_x.py").read_text(encoding="utf-8")
    (project / "test_x.py").write_text(
        "import pytest\n" + text.replace("def test_windows", "@pytest.mark.windows_only\ndef test_windows"), encoding="utf-8",
    )
    result = nm.run_leg(
        sys.executable, project, ["-q", "-m", "not windows_only"], [], tmp_path / "j.xml",
        tmp_path / "r.xml", tmp_path / "flaky.txt",
    )
    assert result == ("flaky", 1, "passed on retry")
    assert (tmp_path / "flaky.txt").read_text(encoding="utf-8") == "test_x::test_flaky\n"


# ------------------------------------------------------------------ READY
@pytest.mark.parametrize(
    ("status", "legs", "declared", "expected"),
    [
        ("run", {"unit": "pass", "e2e": "pass", "smoke": "pass"}, {"unit", "e2e", "smoke"}, "green"),
        ("run", {"unit": "flaky", "e2e": "pass", "smoke": "not-run"}, {"unit", "e2e"}, "green"),
        ("run", {"unit": "pass", "e2e": "fail", "smoke": "pass"}, {"unit", "e2e", "smoke"}, "red"),
        ("run", {"unit": "not-run", "e2e": "not-run", "smoke": "not-run"}, {"unit", "e2e"}, "red"),
        ("run", {"unit": "pass", "e2e": "pass", "smoke": "unknown"}, {"unit", "e2e", "smoke"}, "unknown"),
        ("unknown", {"unit": "not-run", "e2e": "not-run", "smoke": "not-run"}, set(), "unknown"),
    ],
)
def test_night_result(status: str, legs: dict[str, str], declared: set[str], expected: str) -> None:
    assert nm.night_result(status, legs, declared) == expected


def test_leg_from_prefers_the_legs_own_result() -> None:
    assert nm.leg_from("flaky", "success") == "flaky"
    assert nm.leg_from("", "failure") == "fail"
    assert nm.leg_from("", "skipped") == "not-run"
    assert nm.leg_from("unknown", "failure") == "unknown"
    assert nm.leg_from("", "weird") == "unknown"


def test_a_green_night_writes_ready_and_records_the_sha(tmp_path: Path) -> None:
    results, state = tmp_path / "run", tmp_path / "state.json"
    results.mkdir()
    (results / "e2e-flaky.txt").write_text("m::a\nm::b\n", encoding="utf-8")
    rc = nm.main([
        "ready", "--results", str(results), "--state", str(state), "--run", "42", "--repo", "home-automation",
        "--sha", SHA_B, "--status", "run", "--declared", ",unit,e2e,smoke",
        "--unit", "pass", "--e2e", "flaky", "--smoke", "pass", "--smoke-step", "success", "--audit", "clean",
    ])
    assert rc == 0
    ready = dict(line.split("=", 1) for line in (results / "READY").read_text(encoding="utf-8").splitlines())
    assert ready == {
        "run": "42", "repo": "home-automation", "sha": SHA_B, "result": "green",
        "unit": "pass", "e2e": "flaky", "smoke": "pass", "flaky": "2", "audit": "clean",
    }
    assert all(" " not in v for v in ready.values()), "the puller reads READY values as single tokens"
    assert not (results / "READY.tmp").exists()
    assert nm.last_green(state) == SHA_B


def test_an_unknown_night_keeps_the_last_green_sha(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    nm.record_green(state, SHA_A, "1")
    rc = nm.main(["ready", "--results", str(tmp_path / "run"), "--state", str(state), "--run", "2", "--repo", "r",
                  "--sha", SHA_B, "--status", "unknown"])
    assert rc == 1
    assert "result=unknown" in (tmp_path / "run" / "READY").read_text(encoding="utf-8")
    assert nm.last_green(state) == SHA_A


def test_an_unusable_state_file_means_no_green_night(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text("{not json", encoding="utf-8")
    assert nm.last_green(state) is None
    state.write_text(json.dumps({"last_green_sha": "zz"}), encoding="utf-8")
    assert nm.last_green(state) is None
