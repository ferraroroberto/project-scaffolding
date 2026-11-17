"""The `browser-per-iteration` rule: a browser or context opened inside a loop body.

A fresh context per capture starts with an empty HTTP cache and re-fetches every asset, so a
screenshot walk leaves hundreds of sockets in TIME_WAIT on the one port it targets. The rule fails
the walk written that way and passes the one that opens a single context before the loop.
"""

from __future__ import annotations

import pytest

from scripts import conventions_ratchet as cr

RULE = "browser-per-iteration"
CFG = cr.Config(cr.DEFAULT_BASELINE, (RULE,))


def hits(src: str, path: str = "scripts/walk.py") -> list[str]:
    return [f"{h.rule}:{h.line}" for h in cr.scan_source(src, path, cr.rules_for(path, CFG))]


def test_the_rule_is_known_and_opt_in() -> None:
    assert RULE in cr.RULES
    cfg = cr.parse_config(f'[conventions_ratchet]\nenabled = true\nrules = ["{RULE}"]\n')
    assert cfg is not None and cfg.rules == (RULE,)
    assert cr.rules_for("scripts/walk.py", cr.Config(cr.DEFAULT_BASELINE, ("no-window",))) == {"no-window"}


@pytest.mark.parametrize(
    "call",
    [
        pytest.param("browser.new_context()", id="new-context"),
        pytest.param("browser.new_context(viewport={'width': 390, 'height': 844})", id="new-context-kwargs"),
        pytest.param("browser.new_page()", id="browser-new-page"),
        pytest.param("p.chromium.launch(headless=True)", id="launch"),
        pytest.param("p.webkit.launch_persistent_context('d')", id="launch-persistent"),
        pytest.param("browser_type.launch()", id="browser-type-fixture"),
    ],
)
def test_a_browser_or_context_opened_per_iteration_fails(call: str) -> None:
    for header in ("for url in urls:", "while todo:", "async for url in urls:"):
        src = f"def walk(p, browser, browser_type, urls, todo):\n    {header}\n        x = {call}\n        x.close()\n"
        assert hits(src) == [f"{RULE}:3"], header


def test_the_same_calls_before_the_loop_pass() -> None:
    src = ("def walk(browser, urls):\n    context = browser.new_context()\n    page = context.new_page()\n"
           "    for url in urls:\n        page.goto(url)\n        page.screenshot(path='a.png')\n")
    assert hits(src) == []


def test_a_context_per_iteration_in_a_comprehension_fails() -> None:
    src = "def walk(browser, urls):\n    return [browser.new_context() for _ in urls]\n"
    assert hits(src) == [f"{RULE}:2"]


def test_a_nested_loop_inside_a_function_still_fails() -> None:
    src = "def walk(browser, grid):\n    for row in grid:\n        for cell in row:\n            browser.new_context()\n"
    assert hits(src) == [f"{RULE}:4"]


def test_a_page_opened_on_a_context_per_iteration_is_not_the_rule() -> None:
    src = "def walk(context, urls):\n    for url in urls:\n        page = context.new_page()\n        page.goto(url)\n"
    assert hits(src) == []


def test_a_function_defined_in_a_loop_is_not_run_per_iteration() -> None:
    src = ("def walk(browser, names):\n    for name in names:\n        def make():\n"
           "            return browser.new_context()\n        register(name, make)\n")
    assert hits(src) == []


def test_an_unrelated_launch_is_not_a_browser() -> None:
    assert hits("def go(jobs):\n    for job in jobs:\n        job.launch()\n        rocket.launch(job)\n") == []


def test_the_iterable_and_the_else_branch_run_once() -> None:
    src = ("def walk(browser):\n    for url in browser.new_context().pages:\n        pass\n"
           "    else:\n        browser.new_context()\n")
    assert hits(src) == []


def test_test_modules_and_scripts_are_both_held_to_it() -> None:
    src = "def test_walk(browser, urls):\n    for url in urls:\n        browser.new_context()\n"
    for path in ("tests/e2e/test_walk.py", "tests/conftest.py", "scripts/walk.py", "src/walk.py"):
        assert hits(src, path) == [f"{RULE}:3"], path


def test_the_exempt_marker_needs_the_rule_and_a_reason() -> None:
    call = "browser.new_context()"
    head = "def walk(browser, urls):\n    for url in urls:\n"
    assert hits(f"{head}        {call}  # {RULE}-exempt: each case needs a clean cache\n") == []
    assert hits(f"{head}        # {RULE}-exempt: isolation is the point\n        {call}\n") == []
    assert hits(f"{head}        {call}  # {RULE}-exempt\n") == [f"{RULE}:3"]
    assert hits(f"{head}        {call}  # no-window-exempt: wrong rule\n") == [f"{RULE}:3"]
