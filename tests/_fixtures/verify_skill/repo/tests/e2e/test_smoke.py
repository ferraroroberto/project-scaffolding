"""Fixture smoke test."""

from tests.e2e._surface import surface


def test_settings_pane(page):
    surface(page, "settings.pane")
    surface(page, "jobs.list")
