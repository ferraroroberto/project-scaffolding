"""Responsive image variants for the build.

Every `<img src="/images/<file>">` in the content points at a source file in
`content/images/`. The build replaces it with WebP variants at a few widths (never wider
than the source) and a `srcset`/`sizes` pair, so a phone downloads a file sized for its
screen instead of the full original. Social-card images get one 1200 px JPEG, the format
every network accepts.

A drawing exported on the old grey paper (`#f2f2f2` corners and at least 40% of the image
that grey) is put on white paper while its variants are made: near-neutral light pixels
are reflected around the midpoint of grey and white, so the grey paper turns white and the
white panels and pills inside the drawing turn the soft grey, keeping their shapes.

A variant's file name carries a hash of its source (`<name>-<hash>-<width>.webp`), and of
the paper swap when it applies, so an existing file is always current: a rebuild after a
text edit re-encodes nothing, a changed image gets new names (and browsers never see a stale
cached copy), and freshness never depends on file timestamps, which a git checkout resets.

Vendor-verbatim (manifest key `site_images`); needs Pillow. The build calls it: `ImageSet`
gives each image its variants, its social-card copy and its class (`cutout`, `drawing`).
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from PIL import Image, ImageChops

log = logging.getLogger("build")

WIDTHS = (480, 800, 1200, 1600, 2400)
WEBP_QUALITY = 80
OG_WIDTH = 1200
PAPER = (242, 242, 242)  # the grey paper the older drawings were exported on
PAPER_SHARE = 0.4  # below this share of paper a grey-cornered image is a photo, not a drawing
# Bumped when the swap changes, so every swapped image gets new variant names.
PAPER_SWAP_TAG = b"paper-swap-1"


def slug(name: str) -> str:
    """A URL-safe file stem."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "image"


class ImageSet:
    """Source images in `content/images/`, rendered to variants under `site/img/`."""

    def __init__(self, source_dir: Path, out_dir: Path, write: bool) -> None:
        self.source_dir = source_dir
        self.out_dir = out_dir
        self.write = write
        self.sizes: dict[str, tuple[int, int]] = {}
        self.digests: dict[str, str] = {}
        self.papers: dict[str, bool] = {}
        self.cutouts: dict[str, bool] = {}
        self.outputs: set[Path] = set()
        self.missing: list[str] = []

    def size(self, name: str) -> tuple[int, int] | None:
        """(width, height) of a source image, or None when it does not exist."""
        if name not in self.sizes:
            path = self.source_dir / name
            if not path.is_file():
                return None
            with Image.open(path) as im:
                self.sizes[name] = im.size
        return self.sizes[name]

    def has_paper(self, name: str) -> bool:
        """True for a drawing on the grey paper: all four corners exactly `PAPER` and at
        least `PAPER_SHARE` of the image within 3 of it."""
        if name not in self.papers:
            with Image.open(self.source_dir / name) as im:
                self.papers[name] = im.mode == "RGB" and _paper_share(im) >= PAPER_SHARE
        return self.papers[name]

    def is_cutout(self, name: str) -> bool:
        """True for an image whose top-left corner is transparent: a cut-out with its own shape."""
        if name not in self.cutouts:
            path = self.source_dir / name
            if not path.is_file():
                return False
            with Image.open(path) as im:
                corner = im.convert("RGBA").getpixel((0, 0)) if im.mode in ("RGBA", "LA", "P") else None
                self.cutouts[name] = isinstance(corner, tuple) and corner[3] == 0
        return self.cutouts[name]

    def stem(self, name: str) -> str:
        """The variant file stem: the source name plus a hash of its bytes (and of the paper swap)."""
        if name not in self.digests:
            digest = hashlib.sha256((self.source_dir / name).read_bytes())
            if self.has_paper(name):
                digest.update(PAPER_SWAP_TAG)
            self.digests[name] = digest.hexdigest()[:8]
        return f"{slug(name.rsplit('.', 1)[0])}-{self.digests[name]}"

    def _render(self, name: str, target: Path, width: int, fmt: str) -> None:
        self.outputs.add(target)
        source = self.source_dir / name
        if target.exists():
            return
        if not self.write:
            self.missing.append(target.name)
            return
        target.parent.mkdir(parents=True, exist_ok=True)  # runtime-write-exempt: the build writes variants into the publish folder its caller names
        with Image.open(source) as opened:
            opened.load()
            im: Image.Image = opened
            if im.width > width:
                im = im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS)
            if self.has_paper(name):
                im = paper_swap(im)
            if fmt == "JPEG":
                im = _flatten(im.convert("RGBA")) if im.mode in ("RGBA", "LA", "P") else im.convert("RGB")
                im.save(target, "JPEG", quality=85, optimize=True, progressive=True)
            else:
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA")
                im.save(target, "WEBP", quality=WEBP_QUALITY, method=6)
        log.info("🖼️ %s", target.name)

    def variants(self, name: str) -> list[tuple[str, int]]:
        """[(url, width)] of the WebP variants of a source image."""
        dims = self.size(name)
        if dims is None:
            return []
        width = dims[0]
        steps = [w for w in WIDTHS if w < width] + [min(width, WIDTHS[-1])]
        stem = self.stem(name)
        out = []
        for w in steps:
            file = f"{stem}-{w}.webp"
            self._render(name, self.out_dir / file, w, "WEBP")
            out.append((f"/img/{file}", w))
        return out

    def social(self, name: str) -> str | None:
        """Root-relative URL of a 1200 px JPEG for social cards."""
        dims = self.size(name)
        if dims is None:
            return None
        file = f"{self.stem(name)}-og.jpg"
        self._render(name, self.out_dir / file, min(OG_WIDTH, dims[0]), "JPEG")
        return f"/img/{file}"


def _paper_share(im: Image.Image) -> float:
    """The share of an RGB image within 3 of `PAPER`, or 0 when a corner is not exactly `PAPER`."""
    w, h = im.size
    if any(im.getpixel(p) != PAPER for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))):
        return 0.0
    small = im.reduce(4)  # the share, not single pixels, matters: a quarter-size copy is enough
    near = [band.point(lambda v: 255 if abs(v - PAPER[0]) <= 3 else 0) for band in small.split()]
    mask = ImageChops.multiply(ImageChops.multiply(near[0], near[1]), near[2])
    return mask.histogram()[255] / (small.width * small.height)


def paper_swap(im: Image.Image) -> Image.Image:
    """Grey paper to white, white panels to grey: v -> 497 - v on near-neutral pixels of 242 and up.

    Near-neutral means the channels differ by 6 at most, so coloured ink is never touched.
    The 236-241 band, where ink strokes fade into the paper, moves up by 13 so stroke edges
    meet the new white without a grey seam.
    """
    r, g, b = im.convert("RGB").split()
    low = ImageChops.darker(ImageChops.darker(r, g), b)
    high = ImageChops.lighter(ImageChops.lighter(r, g), b)
    neutral = ImageChops.subtract(high, low).point(lambda v: 255 if v <= 6 else 0)
    light = ImageChops.multiply(low.point(lambda v: 255 if v >= 242 else 0), neutral)
    edge = ImageChops.multiply(low.point(lambda v: 255 if 236 <= v < 242 else 0), neutral)
    rgb = im.convert("RGB")
    out = Image.composite(rgb.point(lambda v: 497 - v if v >= 242 else v), rgb, light)
    return Image.composite(rgb.point(lambda v: min(255, v + 13)), out, edge)


def _flatten(im: Image.Image) -> Image.Image:
    """An RGBA image on white, for JPEG."""
    bg = Image.new("RGB", im.size, (255, 255, 255))
    bg.paste(im, mask=im.getchannel("A"))
    return bg
