"""Unit coverage for the request-budget probe's verdicts: the budget key and the problem rules.

No browser: the browser half runs in tests/e2e/budget/test_vendored_poll.py. These
cases pin that a budget the probe cannot read is its own unknown state, never a
pass and never a silent default.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from tests.e2e.budget._request_budget import (
    BudgetReading,
    RequestBudgetUnknown,
    request_budget_problems,
    visible_budget,
)

UNKNOWN_FLEET_TOMLS = {
    "no table": "[other]\nkey = 1\n",
    "no key": "[request_budget]\nother = 1\n",
    "not a table": "request_budget = 3\n",
    "a string": '[request_budget]\nvisible_requests_per_minute = "30"\n',
    "a float": "[request_budget]\nvisible_requests_per_minute = 30.0\n",
    "a bool": "[request_budget]\nvisible_requests_per_minute = true\n",
    "negative": "[request_budget]\nvisible_requests_per_minute = -1\n",
    "bad toml": "[request_budget\n",
}


@pytest.mark.parametrize("body", UNKNOWN_FLEET_TOMLS.values(), ids=UNKNOWN_FLEET_TOMLS.keys())
def test_an_unusable_budget_is_unknown(tmp_path: Path, body: str) -> None:
    (tmp_path / ".fleet.toml").write_text(body, encoding="utf-8")
    with pytest.raises(RequestBudgetUnknown, match="NOT CONFIRMED"):
        visible_budget(tmp_path)


def test_a_missing_fleet_toml_is_unknown(tmp_path: Path) -> None:
    with pytest.raises(RequestBudgetUnknown, match="NOT CONFIRMED"):
        visible_budget(tmp_path)


def test_unknown_is_not_an_assertion_failure() -> None:
    # pytest reports a non-assertion exception as an error, apart from a broken budget's failure.
    assert not issubclass(RequestBudgetUnknown, AssertionError)


@pytest.mark.parametrize("value", [0, 30])
def test_a_whole_number_budget_is_read(tmp_path: Path, value: int) -> None:
    (tmp_path / ".fleet.toml").write_text(
        f"[request_budget]\nvisible_requests_per_minute = {value}\n", encoding="utf-8"
    )
    assert visible_budget(tmp_path) == value


def test_problems_name_each_breach() -> None:
    reading = BudgetReading(
        visible=Counter({"/api/board": 30}),
        hidden=Counter({"/api/board": 30}),
        catch_up=Counter({"/api/board": 2}),
    )
    problems = request_budget_problems(reading, visible_max=12)
    assert len(problems) == 3
    assert "30 requests in a visible minute, budget 12" in problems[0]
    assert "while hidden" in problems[1]
    assert "catch-up" in problems[2]


def test_a_pausing_poll_has_no_problems() -> None:
    reading = BudgetReading(
        visible=Counter({"/api/board": 12}), catch_up=Counter({"/api/board": 1})
    )
    assert request_budget_problems(reading, visible_max=12) == []
