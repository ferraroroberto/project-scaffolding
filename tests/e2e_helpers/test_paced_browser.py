"""Unit coverage for the paced-browser helper: reuse, the page cap and the TIME_WAIT pause.

Everything runs against fakes (a context, a page, a scripted TIME_WAIT counter and a
fake clock), so it needs no browser and opens no socket. A real-browser case would
itself be a walk and would add to the pool the helper exists to protect.
"""

from __future__ import annotations

import pytest

from tests.e2e import _paced_browser
from tests.e2e._paced_browser import (
    HARD_MAX_PARALLEL,
    PacedWalk,
    ParallelCapExceeded,
    PortPoolBusy,
    PortPoolUnknown,
    count_time_wait,
)


class FakePage:
    def __init__(self) -> None:
        self.visited: list[str] = []
        self.idle_waits = 0

    def goto(self, url: str, **_: object) -> None:
        self.visited.append(url)

    def wait_for_load_state(self, state: str, timeout: int) -> None:
        assert state == "networkidle"
        self.idle_waits += 1


class FakeContext:
    def __init__(self) -> None:
        self.pages: list[FakePage] = []
        self.closed = False

    def new_page(self) -> FakePage:
        self.pages.append(FakePage())
        return self.pages[-1]

    def close(self) -> None:
        self.closed = True


class FakeBrowser:
    def __init__(self) -> None:
        self.contexts: list[FakeContext] = []

    def new_context(self, **_: object) -> FakeContext:
        self.contexts.append(FakeContext())
        return self.contexts[-1]


class Clock:
    """A clock the fake sleep advances, so a pause costs no wall time."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def scripted(*counts: int | None) -> tuple[list[int], object]:
    """A counter that returns *counts* in order, then repeats the last; the list records each call."""
    calls: list[int] = []

    def counter(port: int) -> int | None:
        calls.append(port)
        return counts[min(len(calls), len(counts)) - 1]

    return calls, counter


def make_walk(counter: object, clock: Clock | None = None, **kwargs: object) -> tuple[PacedWalk, FakeContext, Clock]:
    clock = clock or Clock()
    context = FakeContext()
    walk = PacedWalk(context, 8501, counter=counter, sleep=clock.sleep, clock=clock, **kwargs)  # type: ignore[arg-type]
    return walk, context, clock


def test_every_visit_reuses_one_page_and_waits_for_idle() -> None:
    _, counter = scripted(0)
    walk, context, _ = make_walk(counter)
    for n in range(5):
        walk.visit(f"http://127.0.0.1:8501/{n}")
    assert len(context.pages) == 1
    assert len(context.pages[0].visited) == 5
    assert context.pages[0].idle_waits == 5


def test_paced_walk_opens_exactly_one_context_from_the_browser() -> None:
    browser = FakeBrowser()
    _, counter = scripted(0)
    with _paced_browser.paced_walk(browser, 8501, counter=counter) as walk:  # type: ignore[arg-type]
        walk.visit("http://127.0.0.1:8501/a")
        walk.visit("http://127.0.0.1:8501/b")
    assert len(browser.contexts) == 1
    assert len(browser.contexts[0].pages) == 1
    assert browser.contexts[0].closed


def test_default_parallel_is_one_so_a_second_page_is_refused() -> None:
    _, counter = scripted(0)
    walk, context, _ = make_walk(counter)
    with pytest.raises(ParallelCapExceeded):
        walk.extra_page()
    assert len(context.pages) == 1


def test_extra_pages_are_allowed_up_to_max_parallel_and_no_further() -> None:
    _, counter = scripted(0)
    walk, context, _ = make_walk(counter, max_parallel=3)
    walk.extra_page()
    walk.extra_page()
    with pytest.raises(ParallelCapExceeded):
        walk.extra_page()
    assert len(context.pages) == 3


@pytest.mark.parametrize("value", [0, -1, HARD_MAX_PARALLEL + 1, 50])
def test_max_parallel_outside_the_hard_cap_is_rejected(value: int) -> None:
    _, counter = scripted(0)
    with pytest.raises(ValueError, match="max_parallel"):
        make_walk(counter, max_parallel=value)


def test_the_hard_cap_itself_is_accepted() -> None:
    _, counter = scripted(0)
    walk, _, _ = make_walk(counter, max_parallel=HARD_MAX_PARALLEL)
    assert walk.max_parallel == 4


def test_time_wait_above_the_budget_pauses_until_it_drains() -> None:
    calls, counter = scripted(41, 41, 40)
    walk, _, clock = make_walk(counter)
    walk.wait_for_budget()
    assert len(calls) == 3
    assert clock.sleeps == [2.0, 2.0]
    assert walk.pauses == 1
    assert walk.paused_s == 4.0
    assert walk.peak == 41


def test_a_count_at_the_budget_does_not_pause() -> None:
    _, counter = scripted(40)
    walk, _, clock = make_walk(counter)
    walk.wait_for_budget()
    assert clock.sleeps == []
    assert walk.pauses == 0


def test_a_port_that_never_drains_raises_a_named_error() -> None:
    _, counter = scripted(180)
    walk, _, _ = make_walk(counter, pause_timeout_s=10.0)
    with pytest.raises(PortPoolBusy, match="stayed above 40"):
        walk.wait_for_budget()
    assert walk.peak == 180


def test_the_budget_is_checked_after_every_settle_not_only_at_the_start() -> None:
    calls, counter = scripted(0)
    walk, _, _ = make_walk(counter)
    walk.visit("http://127.0.0.1:8501/a")
    assert len(calls) == 2  # before the load, and after the idle wait


def test_the_counter_is_asked_about_the_target_port() -> None:
    calls, counter = scripted(0)
    walk, _, _ = make_walk(counter)
    walk.wait_for_budget()
    assert calls == [8501]


def test_an_unreadable_count_is_reported_not_passed() -> None:
    _, counter = scripted(None)
    walk, _, _ = make_walk(counter)
    walk.wait_for_budget()
    assert walk.unknown_samples == 1
    assert "NOT CONFIRMED" in walk.report()


def test_a_strict_walk_refuses_to_walk_unmeasured() -> None:
    _, counter = scripted(None)
    walk, _, _ = make_walk(counter, strict=True)
    with pytest.raises(PortPoolUnknown):
        walk.wait_for_budget()


def test_the_report_states_the_peak_and_the_pauses() -> None:
    _, counter = scripted(55, 30)
    walk, _, _ = make_walk(counter)
    walk.wait_for_budget()
    text = walk.report()
    assert "peak TIME_WAIT on port 8501: 55" in text
    assert "1 pause(s)" in text


class _Completed:
    def __init__(self, stdout: bytes, returncode: int = 0) -> None:
        self.stdout = stdout
        self.returncode = returncode


def _netstat(monkeypatch: pytest.MonkeyPatch, lines: list[str], returncode: int = 0) -> None:
    body = "\n".join(lines).encode()
    monkeypatch.setattr(_paced_browser.subprocess, "run", lambda *a, **k: _Completed(body, returncode))


def test_count_time_wait_counts_lines_with_the_port_at_either_end(monkeypatch: pytest.MonkeyPatch) -> None:
    _netstat(monkeypatch, [
        "  TCP    127.0.0.1:50001        127.0.0.1:8501         TIME_WAIT",
        "  TCP    127.0.0.1:50002        127.0.0.1:8501         TIME_WAIT",
        "  TCP    127.0.0.1:8501         127.0.0.1:50003        TIME_WAIT",
        "  TCP    127.0.0.1:50004        127.0.0.1:8501         ESTABLISHED",
        "  TCP    127.0.0.1:50005        127.0.0.1:9999         TIME_WAIT",
        "  TCP    127.0.0.1:85011        127.0.0.1:18501        TIME_WAIT",
    ])
    assert count_time_wait(8501) == 3


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_count_time_wait_reads_the_unix_netstat_columns(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    # Recv-Q/Send-Q precede the endpoints on Linux and macOS; macOS separates the port with a dot.
    sep = ":" if platform == "linux" else "."
    proto = "tcp" if platform == "linux" else "tcp4"
    monkeypatch.setattr(_paced_browser.sys, "platform", platform)
    _netstat(monkeypatch, [
        f"{proto}        0      0 127.0.0.1{sep}50001      127.0.0.1{sep}8501       TIME_WAIT",
        f"{proto}        0      0 127.0.0.1{sep}8501       127.0.0.1{sep}50002      TIME_WAIT",
        f"{proto}        0      0 127.0.0.1{sep}50003      127.0.0.1{sep}8501       ESTABLISHED",
        f"{proto}        0      0 127.0.0.1{sep}50004      127.0.0.1{sep}9999       TIME_WAIT",
    ])
    assert count_time_wait(8501) == 2


def test_count_time_wait_is_none_when_netstat_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _netstat(monkeypatch, [], returncode=1)
    assert count_time_wait(8501) is None


def test_count_time_wait_is_none_when_netstat_cannot_start(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> None:
        raise FileNotFoundError("netstat")

    monkeypatch.setattr(_paced_browser.subprocess, "run", boom)
    assert count_time_wait(8501) is None
