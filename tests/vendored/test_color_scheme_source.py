"""`base.css` carries the `color-scheme` rules of `color-scheme/color-scheme.css` byte for byte.

`color-scheme/` is the one source an app without `base` vendors; `base.css`
repeats the same three rules so an app that vendors `base` needs no second
link. This keeps the two from drifting: change one, change the other.
"""

from __future__ import annotations

import re
from pathlib import Path

_VENDORED = Path(__file__).resolve().parents[2] / "app/webapp/static/_vendored"
_SOURCE = _VENDORED / "color-scheme/color-scheme.css"
_BASE = _VENDORED / "base/base.css"

_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _rules(css: str) -> str:
    """The stylesheet's rules with comments and blank lines removed."""
    lines = (line.rstrip() for line in _COMMENT.sub("", css).splitlines())
    return "\n".join(line for line in lines if line.strip())


def test_source_is_the_three_theme_rules() -> None:
    assert _rules(_SOURCE.read_text(encoding="utf-8")) == (
        ":root { color-scheme: light dark; }\n"
        ':root[data-theme="light"] { color-scheme: light; }\n'
        ':root[data-theme="dark"] { color-scheme: dark; }'
    )


def test_base_carries_the_source_rules_verbatim() -> None:
    source = _rules(_SOURCE.read_text(encoding="utf-8"))
    base = _BASE.read_text(encoding="utf-8")
    assert source in base, f"{_BASE.name} must contain {_SOURCE.name}'s rules verbatim:\n{source}"
    # No other color-scheme declaration in base can override or dilute them.
    assert len(re.findall(r"color-scheme\s*:", _COMMENT.sub("", base))) == 3
