"""Many isolated cases inside one e2e test, every failure reported.

The suite keeps one collected test per vendored component contract or user
flow (the fleet's small-suite target in `docs/playwright-ui-testing.md`), but a
contract still has several independent checks. Each check runs as a *case*:
the caller gives it its own fresh setup (a new browser context, a new tray
environment), and a case that fails or errors is recorded and the next case
still runs. The test then fails once, naming every failed case with its full
traceback, so one run shows the whole picture instead of stopping at the first
red.

    with cases() as c:
        for name, check in _CHECKS:
            with c.case(name), new_gallery() as page:
                check(page)

Put `c.case(name)` first in the `with` so a setup error in the fresh page is
caught as that case's failure too. A case that calls `pytest.skip` is recorded
as skipped and the rest still run; the test skips only when every case did.
"""

from __future__ import annotations

import traceback
from collections.abc import Iterator
from contextlib import contextmanager

import pytest


class Cases:
    """Collects each case's outcome; `cases()` turns them into one verdict."""

    def __init__(self) -> None:
        self.ran: list[str] = []
        self.failed: list[tuple[str, str]] = []
        self.skipped: list[tuple[str, str]] = []

    @contextmanager
    def case(self, name: str) -> Iterator[None]:
        """Run the enclosed block as case *name*, recording rather than raising its failure."""
        self.ran.append(name)
        try:
            yield
        except pytest.skip.Exception as exc:
            self.skipped.append((name, str(exc)))
        except (Exception, pytest.fail.Exception):
            self.failed.append((name, traceback.format_exc()))


@contextmanager
def cases() -> Iterator[Cases]:
    """Yield a `Cases` collector; on exit, fail once listing every failed case."""
    collector = Cases()
    yield collector
    if not collector.ran:
        pytest.fail("no case ran: the case list is empty, so this test asserted nothing", pytrace=False)
    if collector.failed:
        names = ", ".join(name for name, _ in collector.failed)
        details = "\n\n".join(f"--- case {name} ---\n{tb}" for name, tb in collector.failed)
        pytest.fail(
            f"{len(collector.failed)} of {len(collector.ran)} cases failed: {names}\n\n{details}",
            pytrace=False,
        )
    if len(collector.skipped) == len(collector.ran):
        pytest.skip("; ".join(f"{name}: {why}" for name, why in collector.skipped))
    print(f"{len(collector.ran)} cases ran, {len(collector.skipped)} skipped")
    for name, why in collector.skipped:
        print(f"case {name} skipped: {why}")
