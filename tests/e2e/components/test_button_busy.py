"""The button busy state and `runBusy`, one case each on a freshly loaded gallery.

Cases rather than tests: each opens its own browser context and the suite stays
inside its node budget (`_cases.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from playwright.sync_api import Page

from tests.e2e._cases import cases
from tests.e2e.components import _busy_checks


def test_button_busy_contract(new_gallery: Callable[[], AbstractContextManager[Page]]) -> None:
    with cases() as c:
        with c.case("busy_state_both_themes"), new_gallery() as gallery:
            _busy_checks.check_busy_state_both_themes(gallery=gallery)
        with c.case("busy_state_on_a_phone"), new_gallery() as gallery:
            _busy_checks.check_busy_state_on_a_phone(gallery=gallery)
        with c.case("busy_spinner_stops_under_reduced_motion"), new_gallery() as gallery:
            _busy_checks.check_busy_spinner_stops_under_reduced_motion(gallery=gallery)
        with c.case("run_busy_flow"), new_gallery() as gallery:
            _busy_checks.check_run_busy_flow(gallery=gallery)
