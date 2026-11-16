"""``src/subject_text.py`` strips reply prefixes and leaves ordinary words alone."""

from __future__ import annotations

import re

import pytest

from src.subject_text import RE_REPLY_PREFIX, clean_subject

# The regex both private copies shipped before the colon became mandatory.
_OLD_OPTIONAL_COLON = re.compile(r"^\s*(re|rv|fwd?)\s*:?\s*", re.IGNORECASE)

# Words that merely start with a prefix: they must come back unchanged.
_ORDINARY_WORDS = [
    "Recibo de pago",
    "Reserva confirmada",
    "Revisión anual",
    "Report for May",
    "Review of the contract",
    "Fwd2 not a prefix",
    "Fwhatever",
]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("RE: Recibo", "Recibo"),
        ("re: Recibo", "Recibo"),
        ("Rv: Revisión anual", "Revisión anual"),
        ("RV: Reserva", "Reserva"),
        ("FW: Report", "Report"),
        ("Fw: Report", "Report"),
        ("Fwd: Review", "Review"),
        ("FWD: Review", "Review"),
        ("RE： Recibo", "Recibo"),
        ("Rv：Revisión", "Revisión"),
        ("RE: RV: Fwd: Recibo de pago", "Recibo de pago"),
        ("re:fw：Fwd: Report", "Report"),
        ("  RE :  Recibo  ", "Recibo"),
        ("Recibo RE: pago", "Recibo RE: pago"),
    ],
)
def test_prefixes_are_stripped(raw: str, expected: str) -> None:
    assert clean_subject(raw) == expected


@pytest.mark.parametrize("raw", _ORDINARY_WORDS)
def test_ordinary_words_are_untouched(raw: str) -> None:
    assert clean_subject(raw) == raw
    assert RE_REPLY_PREFIX.match(raw) is None


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_empty_input_gives_empty_string(raw: str | None) -> None:
    assert clean_subject(raw) == ""


def test_prefix_only_subject_gives_empty_string() -> None:
    assert clean_subject("RE: FW:") == ""


def test_old_optional_colon_regex_mangles_the_words() -> None:
    """Pins the bug: the pre-fix pattern ate the first letters of these words."""
    assert _OLD_OPTIONAL_COLON.sub("", "Recibo de pago") == "cibo de pago"
    assert _OLD_OPTIONAL_COLON.sub("", "Revisión anual") == "visión anual"
