"""The resource soak fails a leaking fixture app and passes the fixed one.

Each case boots ``tests/_fixtures/soak_app.py`` as a real subprocess, so the
counts are those of a live process serving real requests.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.no_window import NO_WINDOW
from src.resource_probe import SampleUnavailable
from tests.soak import _resource_soak as soak

FIXTURE = Path(__file__).parent.parent / "_fixtures" / "soak_app.py"
ROUTES = ["/api/poll", "/api/status"]


@contextmanager
def booted(mode: str) -> Iterator[tuple[int, str]]:
    proc = subprocess.Popen(
        [sys.executable, str(FIXTURE), mode],
        stdout=subprocess.PIPE,
        text=True,
        creationflags=NO_WINDOW,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        assert line.startswith("PORT="), f"fixture app did not start: {line!r}"
        yield proc.pid, f"http://127.0.0.1:{line.removeprefix('PORT=')}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def run_main(pid: int, base: str, routes: list[str] = ROUTES) -> int:
    args = ["--pid", str(pid), "--base-url", base]
    for route in routes:
        args += ["--route", route]
    return soak.main(args)


def test_fixed_app_passes(capsys: pytest.CaptureFixture[str]) -> None:
    with booted("clean") as (pid, base):
        assert run_main(pid, base) == soak.EXIT_PASS
    out = capsys.readouterr().out
    assert "SOAK_RESULT=pass" in out
    assert "SOAK threads" in out and "SOAK handles" in out and "SOAK rss" in out, "numbers, never a bare pass"


@pytest.mark.parametrize(("mode", "grew"), [("threads", "threads"), ("handles", "handles")])
def test_leaking_app_fails_naming_the_count(mode: str, grew: str, capsys: pytest.CaptureFixture[str]) -> None:
    with booted(mode) as (pid, base):
        assert run_main(pid, base) == soak.EXIT_LEAK
    out = capsys.readouterr().out
    assert "SOAK_RESULT=leak" in out
    assert f"LEAK: {grew}" in out


def test_report_carries_the_growth_numbers() -> None:
    with booted("threads") as (pid, base):
        report = soak.run_soak(pid, base, ROUTES, warmup=2, cycles=10)
    assert report.thread_growth >= 10, "one parked thread per request, ten cycles"
    assert "threads" in report.leaks


def test_dead_process_is_not_confirmed(capsys: pytest.CaptureFixture[str]) -> None:
    with booted("clean") as (pid, base):
        pass
    assert run_main(pid, base) == soak.EXIT_NOT_CONFIRMED
    assert "NOT CONFIRMED" in capsys.readouterr().out


def test_unreachable_app_is_not_confirmed() -> None:
    with booted("clean") as (pid, _base):
        assert run_main(pid, "http://127.0.0.1:1") == soak.EXIT_NOT_CONFIRMED


def test_route_that_is_not_2xx_is_not_confirmed(capsys: pytest.CaptureFixture[str]) -> None:
    with booted("clean") as (pid, base):
        assert run_main(pid, base, ["/api/poll", "/missing"]) == soak.EXIT_NOT_CONFIRMED
    assert "answered 404" in capsys.readouterr().out


def test_unreadable_sample_is_not_confirmed(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def unreadable(pid: int, *, include_children: bool = True) -> None:
        raise SampleUnavailable("no sampler here")

    monkeypatch.setattr(soak, "sample_process", unreadable)
    with booted("clean") as (pid, base):
        assert run_main(pid, base) == soak.EXIT_NOT_CONFIRMED
    assert "no sampler here" in capsys.readouterr().out
