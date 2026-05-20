"""Unit tests for src/pipelines/example_pipeline.py — the run() contract.

`fail_chance` is pinned to 0.0 / 1.0 so the result is deterministic despite
the pipeline's internal `random` use.
"""

from __future__ import annotations

from src.pipelines.example_pipeline import run


def test_run_with_no_failures_reports_zero_warnings() -> None:
    assert run(steps=3, fail_chance=0.0) == {"steps": 3, "warnings": 0}


def test_run_with_certain_failure_warns_every_step() -> None:
    assert run(steps=3, fail_chance=1.0) == {"steps": 3, "warnings": 3}
