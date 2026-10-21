"""Fixture e2e tests: only the `surface()` calls matter to the generator."""

from tests.e2e._surface import surface


def test_jobs_list(page):
    surface(page, "jobs.list")


def test_jobs_empty_or_error(page, broken):
    surface(page, "jobs.error" if broken else "jobs.empty")


class TestFilters:
    def test_open_sheet(self, page):
        surface(page, "filters.sheet")


def test_dynamic_name(page, name):
    surface(page, name)


def _open_hidden(page):
    surface(page, "jobs.hidden")
