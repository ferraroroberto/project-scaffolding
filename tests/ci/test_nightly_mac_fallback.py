"""`scripts/nightly_mac_fallback.py`: dispatch, skip and failure are three different outcomes.

``gh`` is always a fake here: nothing in this file can dispatch the real workflow.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import nightly_mac_fallback as fb  # noqa: E402 -- needs the sys.path line above

NOW = dt.datetime(2026, 11, 10, 0, 23, tzinfo=dt.UTC)
REPO = "owner/repo"


def _done(stdout: str = "", returncode: int = 0, stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


class FakeGh:
    """Records every call; ``list_replies`` are served to successive ``run list`` calls."""

    def __init__(self, list_replies: list[subprocess.CompletedProcess[str]], dispatch=None) -> None:
        self.calls: list[list[str]] = []
        self._list = list_replies
        self._dispatch = dispatch or _done()

    def __call__(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        if args[0] == "workflow":
            return self._dispatch
        return self._list.pop(0) if len(self._list) > 1 else self._list[0]

    @property
    def dispatches(self) -> list[list[str]]:
        return [c for c in self.calls if c[0] == "workflow"]


def _runs(*created: str) -> subprocess.CompletedProcess[str]:
    rows = [{"databaseId": 100 + i, "event": "schedule", "createdAt": c} for i, c in enumerate(created)]
    return _done(json.dumps(rows))


def _run(gh: FakeGh) -> int:
    return fb.run(REPO, gh=gh, now=lambda: NOW, sleep=lambda _s: None)


def test_no_run_today_dispatches_and_confirms(caplog: pytest.LogCaptureFixture) -> None:
    gh = FakeGh([_runs("2026-11-09T01:23:40Z"), _runs("2026-11-10T00:23:50Z")])
    with caplog.at_level(logging.INFO):
        assert _run(gh) == fb.EXIT_OK
    assert gh.dispatches == [["workflow", "run", "nightly-mac.yml", "--repo", REPO, "--ref", "main"]]
    assert "dispatched" in caplog.text


def test_a_run_already_created_today_skips_without_dispatching(caplog: pytest.LogCaptureFixture) -> None:
    gh = FakeGh([_runs("2026-11-10T00:10:00Z", "2026-11-09T01:23:40Z")])
    with caplog.at_level(logging.INFO):
        assert _run(gh) == fb.EXIT_OK
    assert gh.dispatches == []
    assert "skipped" in caplog.text
    assert "dispatched" not in caplog.text


def test_yesterdays_run_does_not_count_as_today() -> None:
    gh = FakeGh([_runs("2026-11-09T23:59:59Z"), _runs("2026-11-10T00:24:00Z")])
    assert _run(gh) == fb.EXIT_OK
    assert len(gh.dispatches) == 1


def test_a_failing_gh_list_exits_non_zero_and_does_not_dispatch(caplog: pytest.LogCaptureFixture) -> None:
    gh = FakeGh([_done(returncode=4, stderr="gh auth login required")])
    with caplog.at_level(logging.INFO):
        assert _run(gh) == fb.EXIT_GH_FAILED
    assert gh.dispatches == []
    assert "gh failed" in caplog.text and "gh auth login required" in caplog.text


def test_a_refused_dispatch_exits_non_zero(caplog: pytest.LogCaptureFixture) -> None:
    gh = FakeGh([_runs()], dispatch=_done(returncode=1, stderr="HTTP 403"))
    with caplog.at_level(logging.INFO):
        assert _run(gh) == fb.EXIT_GH_FAILED
    assert "HTTP 403" in caplog.text


def test_a_dispatch_whose_run_never_appears_is_not_confirmed(caplog: pytest.LogCaptureFixture) -> None:
    gh = FakeGh([_runs()])
    with caplog.at_level(logging.INFO):
        assert _run(gh) == fb.EXIT_NOT_CONFIRMED
    assert len(gh.dispatches) == 1
    assert "not confirmed" in caplog.text and "dispatched:" not in caplog.text


def test_the_three_failure_exits_are_distinct_and_non_zero() -> None:
    assert len({fb.EXIT_OK, fb.EXIT_GH_FAILED, fb.EXIT_NOT_CONFIRMED}) == 3
    assert fb.EXIT_OK == 0


def test_unreadable_gh_output_is_a_failure_not_a_skip() -> None:
    gh = FakeGh([_done("not json")])
    assert _run(gh) == fb.EXIT_GH_FAILED
    assert gh.dispatches == []
