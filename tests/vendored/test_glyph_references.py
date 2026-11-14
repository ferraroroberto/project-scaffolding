"""Every `#i-<name>` a vendored script or stylesheet carries is a real glyph in the sprite.

Adopters scan their served JS and CSS for `#i-<name>` references and fail when a
name has no `<symbol>` in their sprite, so a placeholder such as `#i-NAME` in a
vendored file's comment breaks every adopter's gate the moment it is vendored.
`icons/icons.js` documents the placeholder on purpose and is the one exception,
as it is in the adopters' scans. Component demo `.html` files are not served
and are not scanned.
"""

from __future__ import annotations

import re
from pathlib import Path

_VENDORED = Path(__file__).resolve().parents[2] / "app" / "webapp" / "static" / "_vendored"
_SPRITE = _VENDORED / "icons" / "icons-sprite.html"
_EXCLUDED = {_VENDORED / "icons" / "icons.js"}
_REFERENCE = re.compile(r"#i-([\w-]+)")
_SYMBOL = re.compile(r'<symbol\s+id="i-([\w-]+)"')


def test_vendored_glyph_references_resolve_to_sprite_symbols() -> None:
    symbols = set(_SYMBOL.findall(_SPRITE.read_text("utf-8")))
    unresolved = [
        f"{path.relative_to(_VENDORED).as_posix()}: #i-{name}"
        for path in sorted([*_VENDORED.rglob("*.js"), *_VENDORED.rglob("*.css")])
        if path not in _EXCLUDED
        for name in _REFERENCE.findall(path.read_text("utf-8"))
        if name not in symbols
    ]
    assert not unresolved, "glyph references with no sprite symbol: " + ", ".join(unresolved)
