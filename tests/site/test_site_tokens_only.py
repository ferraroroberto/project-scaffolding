"""No vendored static-site component holds a literal colour: every colour is a token.

`site-tokens.css` is where colour values live (a site overrides them in its own stylesheet,
loaded last). Anywhere else a literal is a value a dark theme or a brand change cannot reach,
which forced site-local overrides for the button hover and the footer text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
VENDORED = REPO_ROOT / "app" / "site" / "static" / "_vendored"
TOKEN_FILE = "site-tokens.css"

NAMED = frozenset(
    """aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown
    burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan
    darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid
    darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet
    deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro
    ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki
    lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow
    lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray
    lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine
    mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise
    mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab
    orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru
    pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown
    seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan
    teal thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen""".split()
)
COLOUR_PROPERTY = re.compile(
    r"(?:^|-)(?:color|background|border|outline|fill|stroke|shadow|decoration)(?:-[a-z]+)*$"
)
HEX = re.compile(r"#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b")
FUNCTION = re.compile(r"\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.IGNORECASE)
BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
LINE_COMMENT = re.compile(r"^\s*//.*$", re.MULTILINE)
URL = re.compile(r"url\([^)]*\)")


def literal_colours(text: str, suffix: str) -> list[str]:
    """Every literal colour in a stylesheet or script, comments and `url(...)` data excluded."""
    code = BLOCK_COMMENT.sub("", text)
    if suffix == ".js":
        code = LINE_COMMENT.sub("", code)
    code = URL.sub("url()", code)
    found = HEX.findall(code) + [m.group(0) for m in FUNCTION.finditer(code)]
    if suffix == ".css":
        for declaration in re.findall(r"([a-z-]+)\s*:\s*([^;{}]+)", code):
            prop, value = declaration
            if COLOUR_PROPERTY.search(prop):
                found += [w for w in re.findall(r"[a-z]+", value.lower()) if w in NAMED]
    return found


def component_files() -> list[Path]:
    files = [
        p for p in sorted(VENDORED.glob("site-*/*"))
        if p.suffix in {".css", ".js"} and p.name != TOKEN_FILE
    ]
    assert files, "the vendored static-site components were not found"
    return files


@pytest.mark.parametrize("path", component_files(), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_a_vendored_component_holds_no_literal_colour(path: Path) -> None:
    assert literal_colours(path.read_text(encoding="utf-8"), path.suffix) == []


def test_the_token_file_still_carries_the_colour_values() -> None:
    assert literal_colours((VENDORED / "site-tokens" / TOKEN_FILE).read_text(encoding="utf-8"), ".css")


@pytest.mark.parametrize(
    ("css", "expected"),
    [
        (".btn:hover { background: #333; }", ["#333"]),
        (".a { color: #EDEDED; }", ["#EDEDED"]),
        (".a { text-decoration-color: rgba(255, 255, 255, 0.5); }", ["rgba("]),
        (".a { color: white; }", ["white"]),
        (".a { border: 1px solid red; }", ["red"]),
        (".a { background: oklch(0.5 0.1 200); }", ["oklch("]),
        (".a { color: var(--ink); border-color: transparent; fill: currentColor; }", []),
        (".a { background: url(\"data:image/svg+xml,%3Csvg fill='%23111'/%3E\"); }", []),
        ("/* the page is #fff on white */ .a { margin: 0; font-family: Arial; }", []),
        (".a { content: \"red\"; }", []),
    ],
)
def test_the_check_names_a_literal_and_passes_tokens(css: str, expected: list[str]) -> None:
    assert literal_colours(css, ".css") == expected


def test_the_check_reads_scripts_too() -> None:
    assert literal_colours("el.style.color = '#fff';", ".js") == ["#fff"]
    assert literal_colours("// #fff is a comment\nel.hidden = true;", ".js") == []


def test_a_button_group_wraps_with_the_standard_gap() -> None:
    css = (VENDORED / "site-button" / "site-button.css").read_text(encoding="utf-8")
    rule = re.search(r"\.btns\s*\{([^}]*)\}", css)
    assert rule, "the .btns rule is missing"
    body = rule.group(1)
    assert "display: flex" in body and "flex-wrap: wrap" in body and "gap: var(--gap)" in body
