"""The e2e case runner reports every failed case, runs the rest, and never passes empty."""

from __future__ import annotations

import pytest

from tests.e2e._cases import cases


def test_every_failed_case_is_named_and_the_rest_still_run() -> None:
    ran: list[str] = []
    with pytest.raises(pytest.fail.Exception) as failure:
        with cases() as c:
            with c.case("first"):
                ran.append("first")
                raise AssertionError("first broke")
            with c.case("second"):
                ran.append("second")
            with c.case("third"):
                ran.append("third")
                pytest.fail("third broke")
    assert ran == ["first", "second", "third"]
    message = str(failure.value)
    assert "2 of 3 cases failed: first, third" in message
    assert "first broke" in message and "third broke" in message


def test_a_setup_error_inside_the_case_is_that_cases_failure() -> None:
    with pytest.raises(pytest.fail.Exception, match="1 of 1 cases failed: boots"):
        with cases() as c:
            with c.case("boots"):
                raise RuntimeError("the page never loaded")


def test_a_skipped_case_does_not_skip_the_others(capsys: pytest.CaptureFixture[str]) -> None:
    with cases() as c:
        with c.case("engine-only"):
            pytest.skip("webkit only")
        with c.case("everywhere"):
            pass
    assert "case engine-only skipped: webkit only" in capsys.readouterr().out


def test_all_cases_skipped_skips_the_test() -> None:
    with pytest.raises(pytest.skip.Exception, match="engine-only: webkit only"):
        with cases() as c:
            with c.case("engine-only"):
                pytest.skip("webkit only")


def test_an_empty_case_list_fails_rather_than_passing() -> None:
    with pytest.raises(pytest.fail.Exception, match="no case ran"):
        with cases():
            pass
