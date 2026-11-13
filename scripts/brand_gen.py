"""Compatibility entry point for fleet icon generators that predate the move of
``brand_gen`` into ``scripts/tools/``.

Every adopter's ``scripts/gen_icons.py`` does ``sys.path.insert(0, <scaffold>/scripts)``
then ``from brand_gen import render_set``; this module keeps that import working by
loading the real generator by path, so no adopter has to change in lockstep.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_IMPL = Path(__file__).resolve().parent / "tools" / "brand_gen.py"
_SPEC = importlib.util.spec_from_file_location("_fleet_brand_gen_impl", _IMPL)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"cannot load the icon generator at {_IMPL}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

render_set = _MODULE.render_set

__all__ = ["render_set"]
