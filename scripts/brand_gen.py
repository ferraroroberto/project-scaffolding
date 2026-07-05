"""Shared fleet icon generator — render one master Lucide SVG onto a dark tile
at every size the fleet's PWA / tray / Stream Deck outputs need.

The master art *is* the vendored Lucide glyph itself (see ``brand/*.svg`` in
this repo) — no bespoke filled-silhouette redraw per project. Rendering the
exact same vector already used for each app's in-app Lucide nav icons is what
keeps the fleet's icons provably one vocabulary instead of independently
drifting, hand-drawn shapes.

``resvg-py`` is a dev-only dependency (see ``requirements.txt``) — the
generated PNGs/ICOs are committed, so no project's runtime webapp ever
imports it.

Usage (from a downstream project's own ``scripts/gen_icons.py``):

    import sys
    sys.path.insert(0, r"E:\\automation\\project-scaffolding\\scripts")
    from brand_gen import render_set

    render_set(
        master=Path(r"E:\\automation\\project-scaffolding\\brand\\rocket.svg"),
        out_dir=STATIC_DIR,
        tray_out_dir=PROJECT_ROOT / "assets" / "tray",
        stream_deck_out_dir=PROJECT_ROOT / "assets" / "stream-deck",
        project_slug="app-launcher",
    )
"""
from __future__ import annotations

import io
import re
from pathlib import Path

import resvg_py
from PIL import Image

BG = "#0A0A0A"
STROKE = "#F0F0F0"
STROKE_WIDTH = 2.6

FULL_BLEED_PAD = 0.12   # padding around the 24x24 glyph for iOS / favicon / Stream Deck tiles
MASKABLE_PAD = 0.26     # extra safe-zone padding for the Android adaptive-icon variant


def _glyph_paths(master_svg_text: str) -> str:
    """Extract the inner path/shape elements from a vendored Lucide SVG."""
    match = re.search(r"<svg[^>]*>(.*)</svg>", master_svg_text, re.S)
    if match is None:
        raise ValueError("master SVG has no <svg> root element")
    return match.group(1).strip()


def _render_tile(glyph_paths: str, size: int, pad_ratio: float) -> Image.Image:
    """Rasterize the glyph centred on an opaque full-bleed dark tile at ``size``.

    Opaque RGB (no alpha) is required for the iOS apple-touch-icon: iOS
    composites any alpha against black, so a transparent-cornered icon would
    render as an invisible square on a dark home screen.
    """
    glyph_size = size * (1 - 2 * pad_ratio)
    offset = size * pad_ratio
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 {size} {size}">
  <rect width="{size}" height="{size}" fill="{BG}"/>
  <g transform="translate({offset},{offset}) scale({glyph_size / 24})"
     fill="none" stroke="{STROKE}" stroke-width="{STROKE_WIDTH}"
     stroke-linecap="round" stroke-linejoin="round">
    {glyph_paths}
  </g>
</svg>'''
    png_bytes = bytes(resvg_py.svg_to_bytes(svg_string=svg, width=size, height=size))
    return Image.open(io.BytesIO(png_bytes)).convert("RGB")


def render_set(
    master: Path,
    out_dir: Path,
    tray_out_dir: Path | None,
    stream_deck_out_dir: Path,
    project_slug: str,
    emit_tray: bool = True,
) -> None:
    """Emit the full icon set for one project from its master Lucide SVG.

    Writes into ``out_dir``: favicon.ico, icon-180.png, icon-192.png,
    icon-512.png, icon-512-maskable.png. Into ``stream_deck_out_dir``:
    ``<project_slug>-144.png``. Into ``tray_out_dir``: ``<project_slug>.ico``
    — unless ``emit_tray=False`` (a project whose tray renders its own live,
    state-tinted icon at runtime instead of loading a static file), in which
    case ``tray_out_dir`` is ignored and may be ``None``.
    """
    glyph_paths = _glyph_paths(master.read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    stream_deck_out_dir.mkdir(parents=True, exist_ok=True)
    if emit_tray:
        assert tray_out_dir is not None, "tray_out_dir is required when emit_tray=True"
        tray_out_dir.mkdir(parents=True, exist_ok=True)

    icon_512 = _render_tile(glyph_paths, 512, FULL_BLEED_PAD)
    icon_512.save(out_dir / "icon-512.png")

    maskable_512 = _render_tile(glyph_paths, 512, MASKABLE_PAD)
    maskable_512.save(out_dir / "icon-512-maskable.png")

    icon_512.resize((180, 180), Image.Resampling.LANCZOS).save(out_dir / "icon-180.png")
    icon_512.resize((192, 192), Image.Resampling.LANCZOS).save(out_dir / "icon-192.png")

    favicon_base = _render_tile(glyph_paths, 256, FULL_BLEED_PAD)
    favicon_base.save(
        out_dir / "favicon.ico",
        sizes=[(16, 16), (32, 32), (48, 48)],
    )

    stream_deck_tile = _render_tile(glyph_paths, 144, FULL_BLEED_PAD)
    stream_deck_tile.save(stream_deck_out_dir / f"{project_slug}-144.png")

    if emit_tray:
        assert tray_out_dir is not None
        tray_base = _render_tile(glyph_paths, 256, FULL_BLEED_PAD)
        tray_base.save(
            tray_out_dir / f"{project_slug}.ico",
            sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)],
        )
