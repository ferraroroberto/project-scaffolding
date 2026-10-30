"""Resource soak: drive a booted webapp's own poll routes, fail on a thread or handle leak.

The gate never runs an app long enough to see a leak, and a webapp that starts
one thread per request looks healthy until the machine runs out of threads. This
samples the app's thread, handle and RSS counts (``src.resource_probe``), drives
``cycles`` rounds of the routes its static UI polls, samples again, and fails
when threads or handles grew by more than a small per-cycle budget. RSS is
reported, not gated: it is too noisy for a fixed budget over a short run.

Booting the app stays the caller's job, as with ``_e2e_live_guard.py``: the
caller passes the pid it booted (descendants are counted, so a Windows venv
launcher is fine) and its base URL.

Exit codes (``python -m tests.soak._resource_soak``): 0 within budget, 1 leak,
3 NOT CONFIRMED. A sample it cannot take, a dead process, an unreachable app or
a route that does not answer 2xx is exit 3 in every case, never a pass.

Vendor-verbatim alongside ``src/resource_probe.py``, which it imports.
"""

from __future__ import annotations

import argparse
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass

from src.resource_probe import ResourceSample, SampleUnavailable, sample_process

EXIT_PASS = 0
EXIT_LEAK = 1
EXIT_NOT_CONFIRMED = 3

# Sampling takes the smallest of a few readings after a pause, so a request still
# in flight or a socket mid-close cannot read as growth; a real leak never shrinks.
SETTLE_SECONDS = 0.2
SETTLE_READINGS = 3


class SoakNotConfirmed(Exception):
    """The soak could not establish a verdict; the reason is the message."""


@dataclass(frozen=True)
class SoakBudget:
    # A thread pool filling lazily is absorbed by the warm-up; anything still
    # growing after it is a leak. A tenth of a thread per cycle would hide a leak
    # of one per ten polls, so the default sits at a twentieth.
    threads_per_cycle: float = 0.05
    handles_per_cycle: float = 0.25


@dataclass(frozen=True)
class SoakReport:
    cycles: int
    before: ResourceSample
    after: ResourceSample
    budget: SoakBudget

    @property
    def thread_growth(self) -> int:
        return self.after.threads - self.before.threads

    @property
    def handle_growth(self) -> int:
        return self.after.handles - self.before.handles

    @property
    def leaks(self) -> list[str]:
        found = []
        if self.thread_growth > self.budget.threads_per_cycle * self.cycles:
            found.append("threads")
        if self.handle_growth > self.budget.handles_per_cycle * self.cycles:
            found.append("handles")
        return found


def drive_routes(base_url: str, routes: Sequence[str], *, timeout: float = 5.0) -> None:
    """GET each route once; anything but a 2xx answer is NOT CONFIRMED."""
    for route in routes:
        url = base_url.rstrip("/") + "/" + route.lstrip("/")
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - caller-supplied loopback URL
                response.read()
        except urllib.error.HTTPError as exc:
            raise SoakNotConfirmed(f"{url} answered {exc.code}, not 2xx") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise SoakNotConfirmed(f"{url} unreachable: {exc}") from exc


def settled_sample(pid: int) -> ResourceSample:
    """The smallest of a few readings per count, taken after a short pause."""
    readings = []
    for _ in range(SETTLE_READINGS):
        time.sleep(SETTLE_SECONDS)
        try:
            readings.append(sample_process(pid))
        except SampleUnavailable as exc:
            raise SoakNotConfirmed(f"cannot sample process {pid}: {exc}") from exc
    return ResourceSample(
        threads=min(r.threads for r in readings),
        handles=min(r.handles for r in readings),
        rss_bytes=min(r.rss_bytes for r in readings),
        processes=readings[-1].processes,
    )


def run_soak(
    pid: int,
    base_url: str,
    routes: Sequence[str],
    *,
    warmup: int = 10,
    cycles: int = 40,
    budget: SoakBudget = SoakBudget(),
) -> SoakReport:
    """Warm up, sample, drive ``cycles`` rounds of ``routes``, sample again."""
    if not routes or cycles < 1:
        raise SoakNotConfirmed("no routes or no cycles to drive")
    for _ in range(warmup):
        drive_routes(base_url, routes)
    before = settled_sample(pid)
    for _ in range(cycles):
        drive_routes(base_url, routes)
    return SoakReport(cycles, before, settled_sample(pid), budget)


def format_report(report: SoakReport) -> str:
    b, a, n = report.before, report.after, report.cycles
    return (
        f"SOAK cycles={n} processes={a.processes}\n"
        f"SOAK threads {b.threads} -> {a.threads} ({report.thread_growth:+d}, "
        f"budget +{report.budget.threads_per_cycle * n:g})\n"
        f"SOAK handles {b.handles} -> {a.handles} ({report.handle_growth:+d}, "
        f"budget +{report.budget.handles_per_cycle * n:g})\n"
        f"SOAK rss {b.rss_bytes / 1048576:.1f}MB -> {a.rss_bytes / 1048576:.1f}MB (reported, not gated)"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fail a booted webapp that leaks threads or handles.")
    parser.add_argument("--pid", type=int, required=True, help="pid the caller booted (descendants are counted)")
    parser.add_argument("--base-url", required=True, help="e.g. http://127.0.0.1:8080")
    parser.add_argument("--route", action="append", required=True, help="a route the UI polls; repeat for several")
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--cycles", type=int, default=40)
    parser.add_argument("--max-threads-per-cycle", type=float, default=SoakBudget.threads_per_cycle)
    parser.add_argument("--max-handles-per-cycle", type=float, default=SoakBudget.handles_per_cycle)
    args = parser.parse_args(argv)
    budget = SoakBudget(args.max_threads_per_cycle, args.max_handles_per_cycle)
    try:
        report = run_soak(
            args.pid, args.base_url, args.route, warmup=args.warmup, cycles=args.cycles, budget=budget
        )
    except SoakNotConfirmed as exc:
        print(f"NOT CONFIRMED: {exc}")
        print("SOAK_RESULT=not_confirmed")
        return EXIT_NOT_CONFIRMED
    print(format_report(report))
    if report.leaks:
        print(f"LEAK: {' and '.join(report.leaks)} grew past the per-cycle budget")
        print("SOAK_RESULT=leak")
        return EXIT_LEAK
    print("SOAK_RESULT=pass")
    return EXIT_PASS


if __name__ == "__main__":
    raise SystemExit(main())
