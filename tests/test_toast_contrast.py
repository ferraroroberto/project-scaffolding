"""The toast's error text clears WCAG AA (4.5:1) in both themes, on any page ground.

Computes the contrast of ``.toast.error``'s ``color`` against its ``background``
straight from ``toast.css``, with token values taken from the component gallery
(``demo.html``, which transcribes the design spec's light and dark palettes).
A translucent fill is composited over every page ground an app can put behind
the toast, so a regression to a see-through fill fails here, not on a device.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_VENDORED = Path(__file__).resolve().parent.parent / "app" / "webapp" / "static" / "_vendored"
_TOAST_CSS = _VENDORED / "toast" / "toast.css"
_DEMO = _VENDORED / "demo.html"

_MIN_RATIO = 4.5
_NAMED = {"black": "#000000", "white": "#ffffff", "transparent": "rgba(0,0,0,0)"}

Rgba = tuple[float, float, float, float]


def _block(text: str, selector: str) -> dict[str, str]:
    """Custom properties declared in the first ``selector { ... }`` rule."""
    match = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", text)
    assert match, f"{selector} block not found"
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", match.group(1)))


def _tokens() -> dict[str, dict[str, str]]:
    demo = _DEMO.read_text(encoding="utf-8")
    light = _block(demo, ":root")
    dark = {**light, **_block(demo, '[data-theme="dark"]')}
    return {"light": light, "dark": dark}


def _declaration(css: str, selector: str, prop: str) -> str:
    rule = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert rule, f"{selector} rule not found in toast.css"
    decl = re.search(r"(?<![\w-])" + prop + r"\s*:\s*([^;]+);", rule.group(1))
    assert decl, f"{selector} has no {prop}"
    return decl.group(1).strip()


def _split_args(text: str) -> list[str]:
    parts, depth, cur = [], 0, ""
    for ch in text:
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
            continue
        depth += (ch == "(") - (ch == ")")
        cur += ch
    parts.append(cur.strip())
    return parts


def _parse(value: str, tokens: dict[str, str]) -> Rgba:
    """A CSS colour to (r, g, b, a), r/g/b in 0-255; resolves var() and color-mix()."""
    value = value.strip()
    if value in _NAMED:
        value = _NAMED[value]
    var = re.fullmatch(r"var\((--[\w-]+)\)", value)
    if var:
        return _parse(tokens[var.group(1)], tokens)
    if value.startswith("#") and len(value) == 7:
        r, g, b = (int(value[i : i + 2], 16) for i in (1, 3, 5))
        return (r, g, b, 1.0)
    rgba = re.fullmatch(r"rgba?\(([^)]*)\)", value)
    if rgba:
        nums = [float(n) for n in re.split(r"[,\s/]+", rgba.group(1).strip())]
        return (nums[0], nums[1], nums[2], nums[3] if len(nums) > 3 else 1.0)
    mix = re.fullmatch(r"color-mix\(in srgb,(.*)\)", value)
    if mix:
        first, second = _split_args(mix.group(1))
        c1, p1 = _mix_stop(first, None)
        c2, p2 = _mix_stop(second, 100 - p1 if p1 is not None else None)
        if p1 is None:
            p1 = 100 - p2 if p2 is not None else 50
        p2 = 100 - p1
        return _premultiplied_mix(_parse(c1, tokens), p1 / 100, _parse(c2, tokens), p2 / 100)
    raise AssertionError(f"unsupported colour: {value!r}")


def _mix_stop(stop: str, default: float | None) -> tuple[str, float | None]:
    pct = re.search(r"\s(\d+(?:\.\d+)?)%$", stop)
    if pct:
        return stop[: pct.start()].strip(), float(pct.group(1))
    return stop, default


def _premultiplied_mix(a: Rgba, wa: float, b: Rgba, wb: float) -> Rgba:
    alpha = a[3] * wa + b[3] * wb
    if alpha == 0:
        return (0.0, 0.0, 0.0, 0.0)
    rgb = tuple((a[i] * a[3] * wa + b[i] * b[3] * wb) / alpha for i in range(3))
    return (rgb[0], rgb[1], rgb[2], alpha)


def _over(top: Rgba, ground: Rgba) -> Rgba:
    a = top[3]
    return (
        top[0] * a + ground[0] * (1 - a),
        top[1] * a + ground[1] * (1 - a),
        top[2] * a + ground[2] * (1 - a),
        1.0,
    )


def _luminance(c: Rgba) -> float:
    def lin(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def _ratio(a: Rgba, b: Rgba) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _error_ratios(theme: str, ground_theme: str) -> list[tuple[str, float]]:
    """Contrast of the error text over each ground the ``ground_theme`` page paints."""
    css = _TOAST_CSS.read_text(encoding="utf-8")
    tokens = _tokens()[theme]
    fill = _parse(_declaration(css, ".toast.error", "background"), tokens)
    text = _parse(_declaration(css, ".toast.error", "color"), tokens)
    grounds = _tokens()[ground_theme]
    return [
        (name, _ratio(text, _over(fill, _parse(grounds[name], grounds))))
        for name in ("--bg", "--card", "--card-off")
    ]


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("ground_theme", ["light", "dark"])
def test_error_toast_text_clears_aa_on_every_ground(theme: str, ground_theme: str) -> None:
    """White error text is >= 4.5:1 however light or dark the page behind the toast is."""
    for ground, ratio in _error_ratios(theme, ground_theme):
        assert ratio >= _MIN_RATIO, (
            f"{theme} toast over the {ground_theme} {ground} ground: {ratio:.2f}:1 < {_MIN_RATIO}:1"
        )


def test_contrast_check_fails_on_the_old_translucent_fill() -> None:
    """The checker itself bites: the former 75% translucent danger fill is below AA."""
    tokens = _tokens()["light"]
    old = _parse("color-mix(in srgb, var(--deficit) 75%, transparent)", tokens)
    text = _parse("var(--accent-fg)", tokens)
    assert _ratio(text, _over(old, _parse("#ffffff", tokens))) < _MIN_RATIO


def test_error_border_stays_the_spec_danger_token() -> None:
    """The fill is darkened in the toast; --deficit itself is read, never redefined."""
    css = _TOAST_CSS.read_text(encoding="utf-8")
    assert _declaration(css, ".toast.error", "border-color") == "var(--deficit)"
    assert "--deficit:" not in css
