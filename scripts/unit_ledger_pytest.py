"""pytest plugin: report each test module to the unit ledger as one unit.

A unit is a whole test module, named by its path from the rootdir (`tests/test_x.py`). For each module
the plugin publishes the unit name in `FLEET_GATE_UNIT` (so the spawn probe attributes process spawns to
it), hands the probe's covered lines to it when the module ends, and, when the gate asked for a unit
report (`FLEET_GATE_UNIT_REPORT`, set by `unit_ledger.py run`), writes one row: `fail` if any phase of
any test failed (with the failure text, bounded), `skip` if every test skipped, else `pass`. With
`FLEET_GATE_ONLY` set, modules not named in it are deselected, which is how the test-value ratchet takes
a red-before-fix record or a coverage run of only the new units. With none of those variables set it
changes nothing.

Turn it on with `-p scripts.unit_ledger_pytest` on the gate's pytest command line (the repo root on
`sys.path`, as `pythonpath = .` in pytest.ini gives).

Contract and adoption: docs/test-value-ratchet.md in project-scaffolding.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import time
from collections.abc import Generator
from pathlib import Path
from types import ModuleType

import pytest


def _load_sibling(name: str) -> ModuleType:
    """The sibling module, as a package member when imported as one, else by path."""
    if __package__:
        return importlib.import_module(f"{__package__}.{name}")
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(f"{name}.py"))
    assert spec is not None and spec.loader is not None
    module = sys.modules[spec.name] = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ledger = _load_sibling("unit_ledger")


def unit_of(nodeid: str) -> str:
    """The unit a test belongs to: its module path, the nodeid before the first `::`."""
    return nodeid.split("::", 1)[0]


class _Unit:
    """The module being run: its name, start time and what its tests reported."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.started = time.perf_counter()
        self.passed = 0
        self.skipped = 0
        self.failures: list[str] = []

    def status(self) -> str:
        if self.failures:
            return str(ledger.FAIL)
        return str(ledger.SKIP) if self.skipped and not self.passed else str(ledger.PASS)


_current: _Unit | None = None


def _finish() -> None:
    global _current
    if _current is not None:
        unit, _current = _current, None
        ledger.end_unit(unit.name, unit.status(), time.perf_counter() - unit.started, "\n".join(unit.failures))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    keep = [item for item in items if ledger.selected(unit_of(item.nodeid))]
    if len(keep) != len(items):
        config.hook.pytest_deselected(items=[item for item in items if item not in keep])
        items[:] = keep


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item: pytest.Item, nextitem: pytest.Item | None) -> Generator[None, None, None]:
    global _current
    name = unit_of(item.nodeid)
    if _current is None or _current.name != name:
        _finish()
        ledger.begin_unit(name)
        _current = _Unit(name)
    yield


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if _current is None or unit_of(report.nodeid) != _current.name:
        return
    if report.failed:
        _current.failures.append(f"{report.nodeid} ({report.when})\n{report.longreprtext}")
    elif report.skipped and report.when in ("setup", "call"):
        _current.skipped += 1
    elif report.passed and report.when == "call":
        _current.passed += 1


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    _finish()
