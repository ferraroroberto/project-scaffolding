from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.tools.brand_gen import _glyph_paths, _render_tile

ROOT = Path(__file__).resolve().parent.parent
BRAND_DIR = ROOT / "brand"
CATALOG = json.loads((BRAND_DIR / "catalog.json").read_text(encoding="utf-8"))
ICONS = CATALOG["icons"]


def test_catalog_covers_every_master() -> None:
    catalog_files = {icon["file"] for icon in ICONS}
    master_files = {path.name for path in BRAND_DIR.glob("*.svg")}
    assert catalog_files == master_files


def test_catalog_is_stable_and_specific() -> None:
    assert CATALOG["source"] == {
        "package": "lucide-static",
        "version": "1.23.0",
        "license": "ISC",
    }
    assert len(ICONS) == 23
    assert all(icon["consumers"] for icon in ICONS)
    assert len({icon["glyph"] for icon in ICONS}) == len(ICONS)


@pytest.mark.parametrize("icon", ICONS, ids=lambda icon: icon["file"])
def test_master_retains_lucide_contract_and_renders(icon: dict[str, object]) -> None:
    path = BRAND_DIR / str(icon["file"])
    text = path.read_text(encoding="utf-8")
    glyph = str(icon["glyph"])
    version = CATALOG["source"]["version"]

    assert text.startswith(f"<!-- @license lucide-static v{version} - ISC -->")

    root = ET.fromstring(text)
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["width"] == "24"
    assert root.attrib["height"] == "24"
    assert root.attrib["viewBox"] == "0 0 24 24"
    assert f"lucide-{glyph}" in root.attrib["class"]

    image = _render_tile(_glyph_paths(text), 32, 0.12)
    assert image.mode == "RGB"
    assert image.size == (32, 32)


def test_doc_snippet_import_path_holds_the_generator() -> None:
    # Adopters copy the thin-caller snippet; its sys.path entry must still hold brand_gen.py.
    doc = (ROOT / "docs" / "brand-icons.md").read_text(encoding="utf-8")
    match = re.search(
        r'sys\.path\.insert\(0, r"E:\\automation\\project-scaffolding\\([^"]+)"\)', doc
    )
    assert match, "docs/brand-icons.md lost its thin-caller sys.path line"
    assert (ROOT / Path(match.group(1).replace("\\", "/")) / "brand_gen.py").is_file()
