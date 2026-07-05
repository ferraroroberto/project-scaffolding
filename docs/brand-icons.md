# Fleet icon brand — shared masters + generator

The fleet's six tray + PWA projects (`app-launcher`, `photo-ocr`, `voice-transcriber`,
`local-llm-hub`, `whatsapp-radar`, `home-automation`) share one icon family so they read as one
coherent set on the iPhone home screen, the Stream Deck, and the Windows tray. Canonical issue:
[`app-launcher#65`](https://github.com/ferraroroberto/app-launcher/issues/65).

## The rule

**The master art is the vendored Lucide SVG itself** — not a bespoke filled-silhouette redraw.
Rendering the exact same vector each project already uses for its in-app Lucide nav icons is what
keeps the family provably one vocabulary instead of independently drifting, hand-drawn shapes (the
problem this replaced: three fleet icons implemented as separate Pillow polygon-drawing scripts,
each redefining its own palette and inset math).

- **Palette:** `#0A0A0A` background, `#F0F0F0` stroke. No per-project accent tint.
- **Stroke weight:** 2.6px (thickened from Lucide's default 2px for legibility at favicon scale).
- **Padding:** 12% full-bleed (favicon / iOS / Stream Deck), 26% for the Android maskable safe zone.

## `brand/` — the masters

Six SVGs, vendored **verbatim** from [`lucide-static`](https://www.npmjs.com/package/lucide-static)
(keep the `@license` comment): `rocket.svg` (app-launcher), `camera.svg` (photo-ocr), `mic.svg`
(voice-transcriber), `hub.svg` (local-llm-hub — vendored from Lucide's `share-2`, renamed for
readability), `radar.svg` (whatsapp-radar), `house.svg` (home-automation).

**Never hand-edit these.** To change a project's shape, replace the file with a different
`lucide-static` glyph — same rule as the vendored `nav`/`icons` components ("copy byte-for-byte,
never edit per-app").

## `scripts/brand_gen.py` — the generator

`render_set(master, out_dir, tray_out_dir, stream_deck_out_dir, project_slug)` renders the master
onto a dark tile via [`resvg-py`](https://pypi.org/project/resvg-py/) at every size the fleet needs,
and writes:

| File | Size | Purpose |
| --- | --- | --- |
| `favicon.ico` | 16 + 32 + 48 | browser tab favicon |
| `icon-180.png` | 180×180 | `apple-touch-icon`, iPhone home screen |
| `icon-192.png` | 192×192 | Android home screen (manifest) |
| `icon-512.png` | 512×512 | manifest large, full-bleed |
| `icon-512-maskable.png` | 512×512 (26% safe inset) | Android adaptive icon |
| `<tray_out_dir>/<project_slug>.ico` | 16/32/48/64/256 | Windows tray icon |
| `<stream_deck_out_dir>/<project_slug>-144.png` | 144×144 | Elgato Stream Deck button |

A downstream project's own `scripts/gen_icons.py` becomes a thin caller:

```python
import sys
from pathlib import Path

sys.path.insert(0, r"E:\automation\project-scaffolding\scripts")
from brand_gen import render_set

PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = PROJECT_ROOT / "app" / "webapp" / "static"

render_set(
    master=Path(r"E:\automation\project-scaffolding\brand\rocket.svg"),
    out_dir=STATIC_DIR,
    tray_out_dir=PROJECT_ROOT / "assets" / "tray",
    stream_deck_out_dir=PROJECT_ROOT / "assets" / "stream-deck",
    project_slug="app-launcher",
)
```

Consumption is a known local path (`E:\automation\project-scaffolding\scripts\brand_gen.py`), not a
package install or git submodule — this is a single-machine fleet, so the simplest wiring is the
right one. If that ever stops being true (a second machine, CI), revisit packaging then.

## Why `resvg-py`, not `cairosvg`

`cairosvg` needs a system Cairo/Pango runtime, which is painful to install on Windows (no prebuilt
wheel ships the native libs; you'd need a GTK3 runtime install alongside it). `resvg-py` wraps the
Rust `resvg` crate and ships a prebuilt wheel for Windows — `pip install resvg-py` and nothing else.
Verified empirically before adopting it (a throwaway venv installed cleanly and rasterized a test
SVG correctly with no system dependencies).

## Adding a 7th project

1. Pick the Lucide glyph that matches the project's existing icon identity (or, if there's a real
   choice to make, render a few candidates as tiles and compare visually before locking one in).
2. Download it verbatim from `lucide-static` into `brand/<name>.svg`.
3. Add a thin `scripts/gen_icons.py` caller in the downstream project per the example above.
4. Regenerate and commit the outputs; wire the manifest / tray / Stream Deck loading as needed.
