"""Responsive image variants: widths, hashed names, the social copy, and the grey-paper swap."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from scripts import site_images
from scripts.site_images import PAPER, ImageSet, paper_swap, slug


def make(path: Path, size: tuple[int, int], mode: str = "RGB", color: tuple[int, ...] = (10, 120, 200)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, color).save(path)


def test_variants_never_upscale_and_carry_a_content_hash(tmp_path: Path) -> None:
    make(tmp_path / "src" / "photo one.png", (1000, 500))
    images = ImageSet(tmp_path / "src", tmp_path / "out", write=True)
    variants = images.variants("photo one.png")
    assert [w for _, w in variants] == [480, 800, 1000]
    stem = images.stem("photo one.png")
    assert stem.startswith("photo-one-") and len(stem) == len("photo-one-") + 8
    assert variants[0][0] == f"/img/{stem}-480.webp"
    with Image.open(tmp_path / "out" / f"{stem}-480.webp") as im:
        assert im.size == (480, 240)
    assert images.social("photo one.png") == f"/img/{stem}-og.jpg"
    assert images.variants("absent.png") == [] and images.social("absent.png") is None


def test_a_dry_run_lists_what_is_missing_and_writes_nothing(tmp_path: Path) -> None:
    make(tmp_path / "src" / "a.png", (300, 300))
    images = ImageSet(tmp_path / "src", tmp_path / "out", write=False)
    assert len(images.variants("a.png")) == 1
    assert images.missing and not (tmp_path / "out").exists()


def test_cutouts_and_drawings_are_told_apart(tmp_path: Path) -> None:
    make(tmp_path / "cut.png", (40, 40), "RGBA", (0, 0, 0, 0))
    make(tmp_path / "paper.png", (40, 40), "RGB", PAPER)
    make(tmp_path / "photo.png", (40, 40))
    images = ImageSet(tmp_path, tmp_path / "out", write=True)
    assert images.is_cutout("cut.png") and not images.is_cutout("photo.png") and not images.is_cutout("absent.png")
    assert images.has_paper("paper.png") and not images.has_paper("photo.png")
    assert images.stem("paper.png") != images.stem("photo.png")


def test_the_paper_swap_turns_paper_white_and_white_panels_grey() -> None:
    im = Image.new("RGB", (3, 1))
    im.putpixel((0, 0), PAPER)
    im.putpixel((1, 0), (255, 255, 255))
    im.putpixel((2, 0), (200, 30, 30))
    out = paper_swap(im)
    assert [out.getpixel((x, 0)) for x in range(3)] == [(255, 255, 255), (242, 242, 242), (200, 30, 30)]


def test_slug_and_the_jpeg_flatten() -> None:
    assert slug("a b/c?.png") == "a-b-c-.png" and slug("???") == "image"
    flat = site_images._flatten(Image.new("RGBA", (2, 2), (0, 0, 0, 0)))
    assert flat.mode == "RGB" and flat.getpixel((0, 0)) == (255, 255, 255)
