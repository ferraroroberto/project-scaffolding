"""Unit tests for ``src/resource_probe.py``: the counts and the runtime breadcrumb."""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from src import resource_probe
from src.no_window import NO_WINDOW
from src.resource_probe import SampleUnavailable, sample_process, start_breadcrumb

BREADCRUMB = re.compile(r"resources threads=\d+ handles=\d+ rss=\d+\.\dMB")


def test_sample_counts_this_process() -> None:
    sample = sample_process(include_children=False)
    assert sample.threads >= 1 and sample.handles >= 1 and sample.rss_bytes > 0 and sample.processes == 1


def test_sample_sees_a_new_thread() -> None:
    before = sample_process(include_children=False).threads
    park = threading.Event()
    thread = threading.Thread(target=park.wait, daemon=True)
    thread.start()
    try:
        assert sample_process(include_children=False).threads == before + 1
    finally:
        park.set()
        thread.join()


def test_children_are_counted_by_default() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], creationflags=NO_WINDOW)
    try:
        assert sample_process().processes >= 2
        assert sample_process(include_children=False).processes == 1
    finally:
        child.kill()
        child.wait(timeout=10)


def test_missing_process_is_unavailable_not_zero() -> None:
    child = subprocess.Popen([sys.executable, "-c", "pass"], creationflags=NO_WINDOW)
    child.wait(timeout=10)
    with pytest.raises(SampleUnavailable):
        sample_process(child.pid)


def test_linux_sampler_reads_a_proc_tree(tmp_path: Path) -> None:
    def proc(pid: int, ppid: int, threads: int, fds: int, rss_kb: int) -> None:
        root = tmp_path / str(pid)
        (root / "fd").mkdir(parents=True)
        for n in range(fds):
            (root / "fd" / str(n)).touch()
        (root / "stat").write_text(f"{pid} (my app) S {ppid} 0 0\n", encoding="utf-8")
        (root / "status").write_text(f"Threads:\t{threads}\nVmRSS:\t{rss_kb} kB\n", encoding="utf-8")

    proc(10, 1, 4, 6, 1000)
    proc(11, 10, 3, 5, 2000)
    proc(12, 1, 99, 99, 99)  # a sibling, not a descendant
    sample = resource_probe._sample_linux(10, True, tmp_path)
    assert (sample.threads, sample.handles, sample.rss_bytes, sample.processes) == (7, 11, 3000 * 1024, 2)
    assert resource_probe._sample_linux(10, False, tmp_path).processes == 1
    with pytest.raises(SampleUnavailable):
        resource_probe._sample_linux(404, True, tmp_path)


def test_breadcrumb_logs_the_counts_on_an_interval(caplog: pytest.LogCaptureFixture) -> None:
    logger = logging.getLogger("test_resource_breadcrumb")
    with caplog.at_level(logging.INFO, logger=logger.name):
        stop = start_breadcrumb(logger, interval_seconds=0.05)
        try:
            deadline = threading.Event()
            while sum(1 for r in caplog.records if BREADCRUMB.search(r.getMessage())) < 2:
                assert not deadline.wait(0.05) and len(caplog.records) < 200, "breadcrumb never repeated"
        finally:
            stop.set()


def test_breadcrumb_unreadable_sample_warns_once_and_stops(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def unreadable(pid: int | None = None, *, include_children: bool = True) -> None:
        raise SampleUnavailable("no sampler here")

    monkeypatch.setattr(resource_probe, "sample_process", unreadable)
    logger = logging.getLogger("test_resource_breadcrumb_unreadable")
    with caplog.at_level(logging.INFO, logger=logger.name):
        stop = start_breadcrumb(logger, interval_seconds=0.01)
        for thread in threading.enumerate():
            if thread.name == "resource-breadcrumb":
                thread.join(timeout=5)
        stop.set()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1 and "no sampler here" in warnings[0].getMessage()
