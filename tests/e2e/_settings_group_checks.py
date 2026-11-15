"""Checks for the native select and the settings-group component.

Each check takes a freshly loaded `demo.html` gallery; `test_vendored_components.py`
runs them as cases. A select has two shapes: the bordered `select-native` form
control, and inside a Settings row the borderless muted value. The settings-group
checks pin what the fleet's hand-built Settings panes got wrong at 390px: an
overline that rode into its card's border, labels that wrapped, values drawn as
bordered pills and number fields of different widths and sizes.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager

from playwright.sync_api import Page, expect

from tests.e2e._cases import Cases
from tests.e2e._color_assertions import set_theme as _set_theme
from tests.e2e._color_assertions import style as _style
from tests.e2e._geometry import assert_no_horizontal_overflow

_PHONE = {"width": 390, "height": 844}


def _gap(gallery: Page, head: str, card: str) -> float:
    """Pixels between the bottom of a header and the top of its card (negative = overlap)."""
    return float(
        gallery.evaluate(
            "([h, c]) => document.querySelector(c).getBoundingClientRect().top"
            " - document.querySelector(h).getBoundingClientRect().bottom",
            [head, card],
        )
    )


def _lines(gallery: Page, selector: str) -> int:
    """How many line boxes an element's text occupies."""
    return int(
        gallery.evaluate(
            "(s) => { const r = document.createRange(); r.selectNodeContents(document.querySelector(s));"
            " return new Set([...r.getClientRects()].filter(q => q.width > 1).map(q => Math.round(q.top))).size; }",
            selector,
        )
    )


def check_select_native_contract(gallery: Page) -> None:
    """select-native: control-height (36px via explicit height, not min-height), control-border border, input-bg fill."""
    # THE iOS decision: height is an explicit `height` (respected), never
    # `min-height` (ignored on a bare <select>, rendering it stubby).
    assert _style(gallery, "#demoSelectNative", "height") == "36px"
    assert _style(gallery, "#demoSelectNative", "borderRadius") == "12px"
    assert _style(gallery, "#demoSelectNative", "borderTopWidth") == "1px"
    assert _style(gallery, "#demoSelectNative", "borderTopColor") == "rgb(129, 139, 152)"  # control-border
    # input-bg is card-off in light (var(--card-off) = #f6f8fa).
    assert _style(gallery, "#demoSelectNative", "backgroundColor") == "rgb(246, 248, 250)"
    assert _style(gallery, "#demoSelectNative", "color") == "rgb(31, 35, 40)"


def check_settings_group_header_sits_above_its_card(gallery: Page) -> None:
    """settings-group: the overline is outside the card with a positive gap, at every text size."""
    gallery.set_viewport_size(_PHONE)
    head = "#demoSettingsHead"
    assert _style(gallery, head, "textTransform") == "uppercase"
    assert _style(gallery, head, "fontSize") == "12px"
    assert _style(gallery, head, "color") == "rgb(101, 109, 118)"  # --muted
    # The header is not inside the card it names.
    assert gallery.locator("#demoSettingsGroup #demoSettingsHead").count() == 0
    for root_px in ("16px", "18px", "20px"):
        gallery.evaluate("(px) => { document.documentElement.style.fontSize = px; }", root_px)
        for h, c in (("#demoSettingsHead", "#demoSettingsGroup"), ("#demoSettingsHead2", "#demoSettingsGroup2")):
            gap = _gap(gallery, h, c)
            assert gap >= 4, f"{h} is {gap}px from its card at a {root_px} root"
        assert _lines(gallery, "#demoSettingsSwitchRow .settings-row-label") == 1
    assert_no_horizontal_overflow(gallery)


def check_settings_group_rows_and_value(gallery: Page) -> None:
    """settings-group: inset card, 52px rows on a hairline, a muted unboxed value, a chevron."""
    gallery.set_viewport_size(_PHONE)
    assert _style(gallery, "#demoSettingsGroup", "paddingTop") == "0px"
    assert _style(gallery, "#demoSettingsGroup", "overflow") == "hidden"
    box = gallery.locator("#demoSettingsLink").bounding_box()
    assert box is not None and box["height"] >= 52, box
    # The first row draws no divider; the next one does, in line-muted.
    assert _style(gallery, "#demoSettingsLink", "borderTopWidth") == "0px"
    assert _style(gallery, "#demoSettingsLong", "borderTopWidth") == "1px"
    assert _style(gallery, "#demoSettingsLong", "borderTopColor") == "rgb(216, 222, 228)"
    assert _style(gallery, "#demoSettingsLink .settings-row-icon", "width") == "18px"
    assert _style(gallery, "#demoSettingsLink .settings-row-chevron", "width") == "16px"
    # The value is muted text, never a bordered pill.
    assert _style(gallery, "#demoSettingsValue", "color") == "rgb(101, 109, 118)"
    assert _style(gallery, "#demoSettingsValue", "fontSize") == "14px"
    assert _style(gallery, "#demoSettingsValue", "borderTopWidth") == "0px"
    # A long value ellipsizes first; the label stays whole on one line.
    assert gallery.evaluate(
        "() => { const v = document.querySelector('#demoSettingsLongValue'); return v.scrollWidth > v.clientWidth; }"
    )
    assert gallery.evaluate(
        "() => { const l = document.querySelector('#demoSettingsLongLabel'); return l.scrollWidth <= l.clientWidth; }"
    )
    assert _style(gallery, "#demoSettingsToneValue", "color") == "rgb(125, 78, 0)"  # --attention-text
    # The hint line under a label is muted and single-line.
    assert _style(gallery, "#demoSettingsHint", "color") == "rgb(101, 109, 118)"
    assert _lines(gallery, "#demoSettingsHint") == 1


def check_settings_group_select_is_the_muted_value(gallery: Page) -> None:
    """settings-group: a select in a row is drawn as the value (borderless, muted, full-height target)."""
    sel = "#demoSettingsSelect"
    assert _style(gallery, sel, "borderTopWidth") == "0px"
    assert _style(gallery, sel, "backgroundColor") == "rgba(0, 0, 0, 0)"
    assert _style(gallery, sel, "color") == "rgb(101, 109, 118)"
    assert _style(gallery, sel, "fontSize") == "14px"
    assert _style(gallery, sel, "height") == "44px"
    assert _style(gallery, sel, "appearance") == "none"


def check_settings_group_switch_row_toggles_from_the_row(gallery: Page) -> None:
    """settings-group: the switch row is a label, so a tap on its text toggles the switch."""
    switch = gallery.locator("#demoSettingsSwitch")
    expect(switch).to_have_attribute("aria-checked", "false")
    expect(switch).to_have_accessible_name("Translate to English Any language in, English out")
    gallery.locator("#demoSettingsSwitchRow .settings-row-label").click()
    expect(gallery.locator("#demoSettingsSwitch")).to_have_attribute("aria-checked", "true")
    gallery.locator("#demoSettingsSwitch").click()
    expect(gallery.locator("#demoSettingsSwitch")).to_have_attribute("aria-checked", "false")


def check_settings_group_number_fields_are_one_shape(gallery: Page) -> None:
    """settings-group: every number field is 80px, 16px text (no iOS zoom), right-aligned figures."""
    for sel in ("#demoSettingsNumber", "#demoSettingsNumber2"):
        assert _style(gallery, sel, "width") == "80px", sel
        assert _style(gallery, sel, "fontSize") == "16px", sel
        assert _style(gallery, sel, "textAlign") == "right", sel
        assert _style(gallery, sel, "fontVariantNumeric") == "tabular-nums", sel
        assert _style(gallery, sel, "borderTopColor") == "rgb(129, 139, 152)", sel  # --control-border
    assert _style(gallery, "#demoSettingsNumberRow .settings-row-unit", "color") == "rgb(101, 109, 118)"


def check_settings_group_dark(gallery: Page) -> None:
    """settings-group: the dark theme re-skins header, value, divider and field from the tokens."""
    _set_theme(gallery, "dark")
    assert _style(gallery, "#demoSettingsHead", "color") == "rgb(125, 133, 144)"
    assert _style(gallery, "#demoSettingsValue", "color") == "rgb(125, 133, 144)"
    assert _style(gallery, "#demoSettingsLong", "borderTopColor") == "rgb(33, 38, 45)"
    assert _style(gallery, "#demoSettingsGroup", "backgroundColor") == "rgb(22, 27, 34)"
    assert _style(gallery, "#demoSettingsNumber", "backgroundColor") == "rgb(33, 38, 45)"
    assert _style(gallery, "#demoSettingsToneValue", "color") == "rgb(227, 179, 65)"


_CHECKS = (
    check_settings_group_header_sits_above_its_card,
    check_settings_group_rows_and_value,
    check_settings_group_select_is_the_muted_value,
    check_settings_group_switch_row_toggles_from_the_row,
    check_settings_group_number_fields_are_one_shape,
    check_settings_group_dark,
)


def run_settings_group_cases(c: Cases, new_gallery: Callable[[], AbstractContextManager[Page]]) -> None:
    """Run every settings-group check as its own case, each on a freshly loaded gallery."""
    for check in _CHECKS:
        with c.case(check.__name__.removeprefix("check_")), new_gallery() as gallery:
            check(gallery)
