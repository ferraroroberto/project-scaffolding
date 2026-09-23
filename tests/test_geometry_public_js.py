"""The effective-rect JS is importable under its public name (#269).

fleet-config's /design-review (`skills/_lib/design_review/walk.py`) loads
`tests/e2e/_geometry.py` from this checkout and reads `EFFECTIVE_RECT_JS`,
falling back to the private `_EFFECTIVE_RECT_JS`. If both names disappear,
every design-review run reports its hit-target metrics as `GEOMETRY_MISSING`
instead of failing here.
"""

from __future__ import annotations

from tests.e2e import _geometry


def test_effective_rect_js_is_public_and_the_private_name_aliases_it() -> None:
    assert isinstance(_geometry.EFFECTIVE_RECT_JS, str)
    assert _geometry.EFFECTIVE_RECT_JS.startswith("el =>")
    assert _geometry._EFFECTIVE_RECT_JS is _geometry.EFFECTIVE_RECT_JS
